#!/bin/sh -l
python /main.py --openai_api_key "$1" --github_token "$2" --github_summary_token "$3" --github_pr_id "$4" --openai_engine "$5" --openai_temperature "$6" --openai_max_tokens "$7"
