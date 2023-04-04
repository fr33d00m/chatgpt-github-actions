# Automated Code Review using the ChatGPT language model

# Import statements
import argparse
import openai
import os
import requests
import difflib
import base64


from github import Github

# Adding command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
parser.add_argument('--openai_engine', default="gpt-3.5-turbo",
                    help='Chat model to use. Options: any of the chat models')
parser.add_argument('--openai_temperature', default=0.5,
                    help='Sampling temperature to use. Higher values means the model will take more risks. Recommended: 0.5')
parser.add_argument('--openai_max_tokens', default=2048,
                    help='The maximum number of tokens to generate in the completion.')
args = parser.parse_args()

# Authenticating with the OpenAI API
openai.api_key = args.openai_api_key

text_file_extensions = [
    '.txt', '.md', '.rst', '.asciidoc',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.js', '.jsx', '.ts', '.tsx', '.coffee',
    '.py', '.pyw', '.pyx', '.pyo', '.pyc', '.pyd', '.pyi',
    '.c', '.h', '.cpp', '.hpp', '.cc', '.cxx', '.hh', '.hxx', '.h++',
    '.m', '.mm', '.cs', '.fs', '.fsx',
    '.java', '.scala', '.kt', '.kts',
    '.rb', '.php', '.php3', '.php4', '.php5', '.php7', '.phtml',
    '.go', '.rs', '.swift',
    '.sh', '.bash', '.zsh', '.ksh', '.csh', '.tcsh', '.fish',
    '.pl', '.pm', '.t', '.pod', '.perl',
    '.html', '.htm', '.xhtml', '.css', '.scss', '.sass', '.less',
    '.sql', '.psql', '.pgsql',
    '.lua', '.r', '.groovy', '.gradle', '.dart', '.elm', '.purs', '.svelte',
    '.v', '.zig', '.cr', '.nim', '.jai', '.wren', '.odin', '.hx', '.hs', '.jl', '.ex', '.exs',
    '.erl', '.hrl', '.beam', '.lfe', '.clj', '.cljs', '.cljc', '.clojure',
    '.vbs', '.vb', '.bas', '.cls', '.frm', '.ctl', '.pag', '.dsr', '.dob', '.dsn',
    '.pas', '.pp', '.inc', '.dpr', '.dpk', '.dfm', '.xfm', '.nfm', '.rpy', '.rpyc',
    '.cob', '.cbl', '.cpy', '.ads', '.adb', '.asm', '.s', '.for', '.f', '.f77', '.f90', '.f95',
    '.ada', '.adb', '.als', '.mli', '.ml', '.mll', '.mly', '.sml', '.fsi', '.fs', '.mlir', '.ll',
    '.cmake', '.make', '.mak', '.mk', '.bashrc', '.zshrc', '.vimrc', '.gvimrc', '.ideavimrc',
    '.inputrc', '.bash_profile', '.profile', '.aliases', '.zshenv', '.zprofile', '.zlogin',
    '.zlogout', '.zshrc', '.gitconfig', '.gitignore', '.dockerignore', '.hgignore',
    '.cvsignore', '.svnignore', '.bzrignore',
]


# Authenticating with the Github API
g = Github(args.github_token)

def find_previous_review_comment(pr_comments, filename, bot_username):
    previous_comment = None
    previous_comment_timestamp = None
    count = 0

    # Sort the comments by their creation time
    sorted_pr_comments = sorted(pr_comments, key=lambda comment: comment.created_at)

    for comment in sorted_pr_comments:
        if comment.user.login == bot_username and f"`{filename}`" in comment.body:
            previous_comment = comment.body
            previous_comment_timestamp = comment.created_at
            count += 1

    return previous_comment, count, previous_comment_timestamp


def files():
    repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
    pull_request = repo.get_pull(int(args.github_pr_id))
    
    try:
      authenticated_user = g.get_user()
      bot_username = authenticated_user.login
    except Exception as e:
      print(f"Failed to get authenticated user's username, falling back to 'github-actions'")
      bot_username = "github-actions"

    pr_comments = pull_request.get_issue_comments()

    last_commit_shas = {}
    commits = pull_request.get_commits()
    
    for commit in commits:
        # Getting the modified files in the commit
        files = commit.files
        for file in files:
            # Update the last commit SHA for the file
            last_commit_shas[file.filename] = commit.sha

    # Define a file size threshold (in bytes) for sending only the diff
    file_size_threshold = 6000  # Let's assume that 6k characters is too much for 2k tokens.

    # Process each file and its corresponding last commit SHA
    for filename, sha in last_commit_shas.items():
        print(f"Processing file: {filename}")
        # Getting the file content from the PR's last commit
        file_pr = repo.get_contents(filename, ref=sha)

        # Check if the file is a text file based on its encoding
        filename = file_pr.path
        file_extension = os.path.splitext(filename)[1]
        if file_extension not in text_file_extensions:
          print(f"Skipping non-text file: {filename}")
          continue

        # Getting the file content from the main branch, should parametrize later on.
        try:
            file_main = repo.get_contents(filename, ref="main")
            content_main = file_main.decoded_content
        except Exception:
            print(f"File {filename} not found in main branch, assuming it's a new file.")
            content_main = ""
        
        content_pr = file_pr.decoded_content
        
        # Create a diff between the main branch and the PR's last commit
        unified_diff = list(difflib.unified_diff(content_main.decode().splitlines(), content_pr.decode().splitlines()))
        
        if not unified_diff:
          print(f"No changes found in file: {filename}, skipping.")
          continue
        
        diff = "\n".join(unified_diff)

        # Get relevant context from the original content if the file size is below the threshold
        context_lines = []
        if len(content_main.encode('utf-8')) < file_size_threshold:
            for line in unified_diff:
                if line.startswith('+') and not line.startswith('+++'):
                    context_lines.append(line[1:].strip())

            context = "\n".join(context_lines)
            print(f"Sending context and diff for file: {filename}")
            user_message = f"Review this code patch and suggest improvements and issues - be concise:\n\nOriginal Context:\n```{context}```\n\nDiff:\n```{diff}```"
        else:
            print(f"Sending diff only for file: {filename}")
            user_message = f"Review this code patch and suggest improvements and issues:\n\nDiff:\n```{diff}```"
            
        previous_comment, review_count, previous_comment_timestamp = find_previous_review_comment(pr_comments, filename, bot_username)
        
        last_commit = repo.get_commit(sha)
        last_commit_timestamp = last_commit.commit.committer.date

        # Check if the file hasn't been changed since the last review
        if previous_comment_timestamp and last_commit_timestamp <= previous_comment_timestamp:
          print(f"No updates found in file: {filename} since the last review, skipping.")
          continue

        if previous_comment:
            user_message = f"You previously reviewed this code patch and suggested improvements and issues:\n\n{previous_comment}\n Changes were made, BE more concise than the last time. Were the comments addressed?  {user_message}"

            # Set max_tokens based on the review_count
        max_tokens = args.openai_max_tokens if review_count == 0 else max(30, args.openai_max_tokens // review_count)

        # Sending the diff and context (if applicable) to ChatGPT
        response = openai.ChatCompletion.create(
            model=args.openai_engine,
            messages=[
                {"role": "system", "content": "You are a senior developer/architect and a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            temperature=float(args.openai_temperature),
            max_tokens=int(args.openai_max_tokens)
        )
        print(f"Received response from ChatGPT for file: {filename}")

        # Adding a comment to the pull request with ChatGPT's response
        pull_request.create_issue_comment(
          f"ChatGPT's response about `{file.filename}`:\n {response.choices[0].message.content}")

        print(f"Added comment to pull request for file: {filename}")

files()
