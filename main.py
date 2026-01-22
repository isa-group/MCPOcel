import os
from dotenv import load_dotenv

from transform.builder import OCELBuilder
from transform.mappers import process_workflow_run, process_issue_node
from extractor.rest import fetch_workflow_runs
from extractor.graphql import fetch_github_data
from validate.validate_ocel import validate_ocel

# Config
OUTPUT_FILE = "./storage/github.ocel_v1.json"
REPO_OWNER = "statuscompliance"
REPO_NAME = "status-backend"


def main():
    load_dotenv()
    TOKEN = os.getenv("GITHUB_TOKEN")
    if not TOKEN:
        print("Error: Github token not found in environment variables.")
        return

    builder = OCELBuilder()
    repo_id = f"repo_{REPO_OWNER}_{REPO_NAME}"
    builder.add_object(repo_id, "Repository", {"name": REPO_NAME})

    #  GraphQL
    try:
        nodes = fetch_github_data(REPO_OWNER, REPO_NAME, TOKEN)
        for node in nodes:
            process_issue_node(node, builder, repo_id)
    except Exception as e:
        print(f"Error GraphQL: {e}")

    # REST Workflows
    try:
        runs = fetch_workflow_runs(REPO_OWNER, REPO_NAME, TOKEN, pages=2)
        for run in runs:
            if run["status"] == "completed":
                process_workflow_run(run, builder, repo_id)
    except Exception as e:
        print(f"Error REST Workflows: {e}")

    # REST Commits
    try:
        commits = fetch_commits_rest(REPO_OWNER, REPO_NAME, TOKEN, pages=1) # Only 1 page
        for commit in commits:
            process_commit_rest(commit, builder, repo_id)
    except Exception as e:
        print(f"Error in REST: {e}")

    # Export
    builder.export_json(OUTPUT_FILE)
    print(f"File output: {OUTPUT_FILE}")

    validate_ocel(OUTPUT_FILE)

if __name__ == "__main__":
    main()
