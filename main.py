# Automated Code Review using the ChatGPT language model

# Import statements
import argparse
import openai
import os

from github import Github

# Adding command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_summary_token', help='Your Github Summary Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
parser.add_argument('--openai_engine', default="gpt-3.5-turbo",
                    help='Chat model to use. Options: any of the chat models')
parser.add_argument('--openai_temperature', default=0.5,
                    help='Sampling temperature to use. Higher values means the model will take more risks. Recommended: 0.5')
parser.add_argument('--openai_max_tokens', default=2048,
                    help='The maximum number of tokens to generate in the completion.')
args = parser.parse_args()

if not args.github_summary_token:
    args.github_summary_token = args.github_token

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
    # Authenticating with the Github API
    g = Github(args.github_token)
    repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
    pull_request = repo.get_pull(int(args.github_pr_id))
    
    try:
      authenticated_user = g.get_user()
      bot_username = authenticated_user.login
    except Exception as e:
      print(f"Failed to get authenticated user's username, falling back to 'github-actions[bot]'")
      bot_username = "github-actions[bot]"

    pr_comments = pull_request.get_issue_comments()

    gpt_responses = []
    last_commit_shas = {}
    commits = pull_request.get_commits()
    final_files = pull_request.get_files();
    print("PR file list:\n")
    print("\n".join([file.filename for file in final_files]))

    for commit in commits:
        # Getting the modified files in the commit
        files = commit.files
        for file in files:
            if file.filename not in [f.filename for f in final_files]:
              print(f"Skipping files not in final changeset: {file.filename}")
              continue
              
            # Update the last commit SHA for the file
            if file.status == "removed":
                last_commit_shas.pop(file.filename, None)
            else:
                last_commit_shas[file.filename] = {'sha': commit.sha, 'patch': file.patch}

    # Define a file size threshold (in bytes) for sending only the diff
    file_size_threshold = 6000  # Let's assume that 6k characters is too much for 2k tokens.

    for filename, file_info in last_commit_shas.items():
        sha = file_info['sha']
        diff = file_info['patch']
        print(f"Processing file: {filename}")

        file_extension = os.path.splitext(filename)[1]
        if file_extension not in text_file_extensions:
            print(f"Skipping non-text file: {filename}")
            continue

        # Getting the file content from the PR's last commit
        file_pr = repo.get_contents(filename, ref=sha)

        content_pr = file_pr.decoded_content.decode("utf-8")

        if not diff:
            print(f"No changes found in file: {filename}, skipping.")
            continue

        # Get relevant context from the original content if the file size is below the threshold
        if len(content_pr) < file_size_threshold:
            print(f"Sending context and diff for file: {filename}")
            user_message = f"No wishy-washy shoulda-woulda-coulda, only actionable items. If the change is good, just type a single sentence starting with LGTM. Avoid outputing code - keep it brief if you do. Review this code patch and suggest improvements and issues:\n\nLatest file Context:\n```{content_pr}```\n\nDiff from main:\n```{diff}```"
        else:
            print(f"Sending diff only for file: {filename}")
            user_message = f"No wishy-washy shoulda-woulda-coulda, only actionable items. If the change is good, just type a single sentence starting with LGTM. Avoid outputing code - keep it brief if you do. Review this code patch and suggest improvements and issues:\n\nDiff:\n```{diff}```"
            
        previous_comment, review_count, previous_comment_timestamp = find_previous_review_comment(pr_comments, filename, bot_username)
        print(f"For file {filename} found {review_count} review comments. Last timestamp: {previous_comment_timestamp} ")

        last_commit = repo.get_commit(sha)
        last_commit_timestamp = last_commit.commit.committer.date

        # Check if the file hasn't been changed since the last review
        if previous_comment_timestamp and last_commit_timestamp <= previous_comment_timestamp:
          print(f"No updates found in file: {filename} since the last review, skipping.")
          continue

        if previous_comment:
            print(f"Adjusting the message for previous review!!")
            user_message = f"You previously reviewed this code patch and suggested improvements and issues:\n\n{previous_comment}\n Changes were made, BE MORE concise than the last time. Were the comments addressed?  {user_message}"

            # Set max_tokens based on the review_count
        max_tokens = args.openai_max_tokens if review_count == 0 else max(30, int(args.openai_max_tokens) // review_count)

        # Sending the diff and context (if applicable) to ChatGPT
        try:
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
          gpt_response = response.choices[0].message.content
          gpt_responses.append(gpt_response)
          # Adding a comment to the pull request with ChatGPT's response
          pull_request.create_issue_comment(
            f"ChatGPT's response about `{filename}`:\n {gpt_response}")

          print(f"Added comment to pull request for file: {filename}")
        except Exception as e:
          print(f"Error on GPT: {e}")
          
          
    if len(gpt_responses) == 0:
      return
    
    max_len = 8000
    all_responses = '\n'.join(gpt_responses)[:max_len]
    
    try:
        response = openai.ChatCompletion.create(
            model=args.openai_engine,
            messages=[
                {"role": "system", "content": "You are an elite developer and CTO, but you're also Joe Rogan - the popular podcaster."},
                {"role": "user", "content": f"Summarize in an Executive Review the following Pull Request feedback and give your overall approval like you were Joe Rogan, use emoticons where applicable. On really bad PRs, Joe goes ape shit. Your team of senior developers reviewed the current PR, these are THEIR comments on each file changed: `{all_responses}`"}
            ],
            temperature=float(0.8),
            max_tokens=int(args.openai_max_tokens)
        )
        print(f"Received response from ChatGPT for executive summary ")
        gpt_response = response.choices[0].message.content

        g = Github(args.github_summary_token)
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pull_request = repo.get_pull(int(args.github_pr_id))

        pull_request.create_issue_comment(
          f"PR AI Executive Review: \n\n {gpt_response}")

        print(f"Added executive summary.")
    except Exception as e:
        print(f"Error on GPT PR summary: {e}")

files()
