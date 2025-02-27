# Automated Code Review using the ChatGPT language model

# Import statements
import argparse
import openai
import os
import tiktoken


from github import Github

# Adding command-line arguments
# Max input tokens can the PR reviewers process
# PR review is not made if there are more.
MAX_INPUT_TOKENS = 3800
# How many input tokens can the executive reviewer process
MAX_INPUT_SUMMARY_TOKENS = 2000

parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_summary_token', help='Your Github Summary Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
parser.add_argument('--openai_engine', default="gpt-3.5-turbo",
                    help='Chat model to use. Options: any of the chat models')
parser.add_argument('--openai_temperature', default=0.5,
                    help='Sampling temperature to use. Higher values means the model will take more risks. Recommended: 0.5')
parser.add_argument('--openai_max_tokens', default=512,
                    help='The maximum number of tokens to generate in the completion.')
args = parser.parse_args()

if not args.github_summary_token:
    args.github_summary_token = args.github_token

# Authenticating with the OpenAI API
openai.api_key = args.openai_api_key

text_file_extensions = [
    '.txt', '.md', '.rst', '.asciidoc',
    '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg',
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
    '.cvsignore', '.svnignore', '.bzrignore', '.sol',
]


def main():
    # Authenticating with the Github API
    g = Github(args.github_token)

    try:
        authenticated_user = g.get_user()
        bot_username = authenticated_user.login
    except Exception as e:
        print(f"Failed to get authenticated user's username, falling back to 'github-actions[bot]'")
        bot_username = "github-actions[bot]"

    repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
    pull_request = repo.get_pull(int(args.github_pr_id))
    pr_comments = pull_request.get_issue_comments()
    human_comments = pull_request.get_review_comments()

    gpt_responses = []
    last_commit_shas = {}
    commits = pull_request.get_commits()
    final_files = pull_request.get_files();

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

    input_prompts = []
    total_input_tokens = 0
    for filename, file_info in last_commit_shas.items():
        file_data = process_file(filename, file_info, repo, pr_comments, bot_username, human_comments)

        if file_data is None:
            continue

        user_message = prepare_user_message(file_data)
        user_message_tokens = count_tokens(user_message)
        total_input_tokens += user_message_tokens

        input_prompts.append((filename, user_message, file_data))

    if ((total_input_tokens > MAX_INPUT_TOKENS * 2 and args.openai_engine == 'gpt-4')
       or (total_input_tokens > MAX_INPUT_TOKENS and args.openai_engine != 'gpt-4')):
        print(f"!!! Large amount of tokens detected ({total_input_tokens}): Reviewing Only Diff")
        single_user_message = "No wishy-washy shoulda-woulda-coulda, only actionable items. If the change is good write LGTM in the message. " \
                              "Don't START the review with LGTM if you have insights or potential issues to share. " \
                              "If your response starts with LGTM, summarize the change in 1-2 sentances." \
                              "Keep any code you write to a minimum." \
                              "This is the list of files and changes below them, no need to give an overall review. Review each file in order:"

        for file_name, user_message, file_data in input_prompts:
            single_user_message_part = prepare_single_review_all_files(file_data.diff, file_name)
            single_user_message += f"\n\n{single_user_message_part}"

        input_prompts = [(None, single_user_message, None)]

        # Recount the tokens
        total_input_tokens = count_tokens(single_user_message)
        print(f"Optimized token count: ({total_input_tokens})")

        if ((total_input_tokens > MAX_INPUT_TOKENS * 2 and args.openai_engine == 'gpt-4')
                or (total_input_tokens > MAX_INPUT_TOKENS and args.openai_engine != 'gpt-4')):
            print(f"!!!WARNING!!!: Too many tokens ({total_input_tokens}) to process, skipping review.")
            return

    # Second loop: Process the prepared messages with ChatGPT
    for filename, user_message, file_data in input_prompts:
        gpt_response = engineering_gpt(user_message)

        if gpt_response is None:
            continue

        if filename is None:
            gpt_responses.append(f"> **Warning** Large amount of content detected: Diff only Review:\n\n"
                                 f"{gpt_response}\n\n")
            continue

        print(f"Received response from ChatGPT for file: {filename}")
        gpt_responses.append(f"### `{filename}`:\n"
                                    f"{gpt_response}\n\n")

    print("Total Response count: " + str(len(gpt_responses)))

    if len(gpt_responses) == 0:
        print("No responses to process, exiting.")
        return

    all_responses = '\n'.join(gpt_responses)

    tokens = count_tokens(all_responses)
    if ((tokens > MAX_INPUT_SUMMARY_TOKENS * 2 and args.openai_engine == 'gpt-4')
            or (tokens > MAX_INPUT_SUMMARY_TOKENS and args.openai_engine != 'gpt-4')):

        print(f"Response too big ({tokens}) from ChatGPT. Skipping exec review")
        g = Github(args.github_summary_token)
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pull_request = repo.get_pull(int(args.github_pr_id))

        combined_feedback = (
                f"## GPT Engineering Feedback:\n\n" + "\n".join(all_responses) + "\n\n"
        )
        pull_request.create_issue_comment(combined_feedback)
        return

    previous_exec_feedback, _ = find_previous_review_comment(pr_comments, "Executive Review", bot_username, True)
    if previous_exec_feedback:
        print(f"Including previous exec response.")
        user_message = f"Summarize in an Executive Review the following Pull Request feedback and give your overall approval. " \
                       f"Don't just repeat verbotim what your senior devs said. When referencing files, don't write full file paths - just the name." \
                       f"Review like you were Joe Rogan, use emoticons where applicable. On really bad PRs, Joe goes ape shit." \
                       f"You don't need to introduce yourself. \n" \
                       f"Last time, you summarized the feedback like this:\n\n{previous_exec_feedback}\n\n" \
                       f"This time, your team of senior developers reviewed the current PR, " \
                       f"and these are THEIR comments on each file changed: `{all_responses}`"
    else:
        user_message = f"Summarize in an Executive Review the following Pull Request feedback and give your overall approval. " \
                       f"Don't just repeat verbotim what your senior devs said. When referencing files, don't write full file paths - just the name" \
                       f"Review like you were Joe Rogan, use emoticons where applicable. On really bad PRs, Joe goes ape shit. " \
                       f"You don't need to introduce yourself. " \
                       f"Your team of senior developers reviewed the current PR, " \
                       f"these are THEIR comments on each file changed: `{all_responses}`"

    try:
        response = openai.ChatCompletion.create(
            model=args.openai_engine,
            messages=[
                {"role": "system",
                 "content": "You are an elite developer and CTO, but you're also Joe Rogan - the popular podcaster."},
                {"role": "user", "content": user_message}
            ],
            temperature=float(0.8),
            max_tokens=int(args.openai_max_tokens)
        )
        print(f"Received response from ChatGPT for executive summary ")
        gpt_response = response.choices[0].message.content

        g = Github(args.github_summary_token)
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pull_request = repo.get_pull(int(args.github_pr_id))

        combined_feedback = (
                f"## GPT Engineering Feedback:\n\n{all_responses}\n\n"
                f"## Executive Review:\n\n{gpt_response}"
        )
        pull_request.create_issue_comment(combined_feedback)

        print(f"Added executive summary.")
    except Exception as e:
        print(f"Error on GPT PR summary: {e}")


def process_file(filename, file_info, repo, pr_comments, bot_username, pr_human_comments):
    sha = file_info['sha']
    diff = file_info['patch']
    print(f"Pre-Processing file: {filename}")

    file_extension = os.path.splitext(filename)[1]
    if file_extension not in text_file_extensions:
        print(f"Skipping non-text file: {filename}")
        return None

    file_pr = repo.get_contents(filename, ref=sha)
    content_pr = file_pr.decoded_content.decode("utf-8")

    if not diff:
        print(f"No changes found in file: {filename}, skipping.")
        return None

    previous_comment, previous_comment_timestamp = find_previous_review_comment(pr_comments, filename, bot_username)

    last_commit = repo.get_commit(sha)
    last_commit_timestamp = last_commit.commit.committer.date

    if previous_comment_timestamp and last_commit_timestamp <= previous_comment_timestamp:
        print(f"No updates found in file: {filename} since the last review, skipping.")
        return None

    human_comments = get_human_comments_since_last_review(pr_human_comments, filename, bot_username, previous_comment_timestamp)
    file_data = FileData(content_pr, diff, filename, previous_comment, previous_comment_timestamp, human_comments)
    return file_data


def prepare_user_message(file_data):
    user_message = f"No wishy-washy shoulda-woulda-coulda, only actionable items. If the change is good write LGTM in the message. " \
                       f"Don't START the review with LGTM if you have insights or potential issues to share." \
                       f"The message you write when starting with LGTM will only be used in summary and not directly displayed to the programmer." \
                       f"Keep any code you write to a minimum." \
                       f"Review this code patch and suggest improvements and raise potential issues:\n\nLatest file Context:\n```{file_data.content_pr}```\n\nDiff from main:\n```{file_data.diff}```"

    return append_previous_reviews(file_data, user_message)


def append_previous_reviews(file_data, user_message):
    if file_data.human_comments:
        human_comments_str = "\n".join(file_data.human_comments)
        user_message = f"{user_message}\n\n. Additionally, these are human reviewer comments on the pull request - are they addresed? \n\n{human_comments_str}"
    if file_data.previous_comment:
        gpt_engineer_feedback = file_data.previous_comment.split(f"### `{file_data.filename}`:")[-1].split("### ")[0].strip()
        user_message = f"You previously reviewed this code patch and suggested improvements and issues:\n\n{gpt_engineer_feedback}\n " \
                       f"Changes were made, BE MORE concise than the last time. Were the comments addressed?  {user_message}"
    return user_message


def prepare_single_review_all_files(diff, filename):
    user_message = f"### `{filename}`:\n" \
                   f"Diff:\n```{diff}```"
    return user_message


def engineering_gpt(user_message):
    try:
        response = openai.ChatCompletion.create(
            model=args.openai_engine,
            messages=[
                {"role": "system", "content": "You are a senior developer & architect and a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            temperature=float(args.openai_temperature),
            max_tokens=int(int(args.openai_max_tokens) / 2)
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"Error on GPT: {e}")
        return None


def get_human_comments_since_last_review(review_comments, filename, bot_username, last_review_timestamp):
    human_comments = []

    for comment in review_comments:
        if comment.user.login != bot_username \
                and comment.path == filename and \
                (last_review_timestamp is None or comment.created_at > last_review_timestamp):
            human_comments.append(f"{comment.user.login} (line {comment.position}): {comment.body}")

    return human_comments


def find_previous_review_comment(pr_comments, filename, bot_username, search_for_exec_review=False):
    previous_comment = None
    previous_comment_timestamp = None

    # Sort the comments by their creation time
    sorted_pr_comments = sorted(pr_comments, key=lambda comment: comment.created_at)

    for comment in sorted_pr_comments:
        if comment.user.login == bot_username:
            if search_for_exec_review:
                if "Executive Review" in comment.body:
                    previous_comment = comment.body.split("Executive Review:")[-1].strip()
                    previous_comment_timestamp = comment.created_at
            else:
                if f"`{filename}`" in comment.body:
                    previous_comment = comment.body
                    previous_comment_timestamp = comment.created_at

    return previous_comment, previous_comment_timestamp


def count_tokens(text):
    enc = tiktoken.encoding_for_model("gpt-4")
    try:
        tokens = enc.encode(text)
        token_count = len(list(tokens))
    except Exception:
        token_count = 0
    return token_count


class FileData:
    def __init__(self, content_pr, diff, filename, previous_comment,previous_comment_timestamp, human_comments):
        self.content_pr = content_pr
        self.diff = diff
        self.filename = filename
        self.previous_comment = previous_comment
        self.human_comments = human_comments
        self.previous_comment_timestamp = previous_comment_timestamp


main()
