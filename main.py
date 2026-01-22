import os
from dotenv import load_dotenv

from transform.builder import OCELBuilder
from transform.mappers import process_workflow_run
from extractor.rest import fetch_workflow_runs

# Config
OUTPUT_FILE = "github.ocel_v1.json"
REPO_OWNER = "statuscompliance"
REPO_NAME = "status-backend"

def main():
    load_dotenv()
    TOKEN = os.getenv("GITHUB_TOKEN")
    if not TOKEN:
        print("Error: GITHUB_TOKEN not found.")
        return

    # Initialize Builder
    builder = OCELBuilder()
    repo_id = f"repo_{REPO_OWNER}_{REPO_NAME}"
    builder.add_object(repo_id, "Repository", {"name": REPO_NAME})

    # REST
    try:
        runs = fetch_workflow_runs(REPO_OWNER, REPO_NAME, TOKEN, pages=1)
        for run in runs:
            if run["status"] == "completed":
                process_workflow_run(run, builder, repo_id)
    except Exception as e:
        print(f"Error during execution: {e}")

    # Export
    builder.export_json(OUTPUT_FILE)
    print(f"Success! File generated: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()