import requests

def fetch_workflow_runs(owner, repo, token, pages=3):

    print("Starting REST Workflows...")
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    all_runs = []
    for page in range(1, pages + 1):
        resp = requests.get(url, headers=headers, params={"per_page": 50, "page": page})
        if resp.status_code != 200:
            print(f"REST Error: {resp.status_code}")
            break

        runs = resp.json().get("workflow_runs", [])
        if not runs:
            break

        all_runs.extend(runs)
        print(f"   -> Page {page}: {len(runs)} runs fetched")

    return all_runs