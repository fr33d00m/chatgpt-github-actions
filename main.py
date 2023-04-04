# Automated Code Review using the ChatGPT language model

# Import statements
import argparse
import openai
import os
import requests
from github import Github

# Adding command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
parser.add_argument('--openai_engine', default="text-davinci-002",
                    help='Chat model to use. Options: any of the chat models')
parser.add_argument('--openai_temperature', default=0.5,
                    help='Sampling temperature to use. Higher values means the model will take more risks. Recommended: 0.5')
parser.add_argument('--openai_max_tokens', default=2048,
                    help='The maximum number of tokens to generate in the completion.')
args = parser.parse_args()

# Authenticating with the OpenAI API
openai.api_key = args.openai_api_key

# Authenticating with the Github API
g = Github(args.github_token)


def files():
    repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
    pull_request = repo.get_pull(int(args.github_pr_id))
    
    last_commit_shas = {}
    commits = pull_request.get_commits()
    
    for commit in commits:
        # Getting the modified files in the commit
        files = commit.files
        for file in files:
            # Update the last commit SHA for the file
            last_commit_shas[file.filename] = commit.sha

    # Define a file size threshold (in bytes) for sending only the diff
    file_size_threshold = 6000  # Adjust this value as needed

    # Process each file and its corresponding last commit SHA
    for filename, sha in last_commit_shas.items():
        # Getting the file content from the PR's last commit
        file_pr = repo.get_contents(filename, ref=sha)
        content_pr = file_pr.decoded_content

        # Ignore binary 

        if file_pr.encoding == "base64":
            continue

        # Getting the file content from the main branch
        file_main = repo.get_contents(filename, ref="main")
        content_main = file_main.decoded_content

        # Create a diff between the main branch and the PR's last commit
        unified_diff = list(difflib.unified_diff(content_main.splitlines(), content_pr.splitlines()))
        diff = "\n".join(unified_diff)

        # Get relevant context from the original content if the file size is below the threshold
        context_lines = []
        if len(content_main.encode('utf-8')) < file_size_threshold:
            for line in unified_diff:
                if line.startswith('+') and not line.startswith('+++'):
                    context_lines.append(line[1:].strip())

            context = "\n".join(context_lines)
            user_message = f"Review this code patch and suggest improvements and issues:\n\nOriginal Context:\n```{context}```\n\nDiff:\n```{diff}```"
        else:
            user_message = f"Review this code patch and suggest improvements and issues:\n\nDiff:\n```{diff}```"

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
        # Adding a comment to the pull request with ChatGPT's response
        pull_request.create_issue_comment(
          f"ChatGPT's response about `{file.filename}`:\n {response.choices[0].message.content}")

files()
