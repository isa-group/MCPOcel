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
            print(f"Error in REST {resp.status_code}")
            break

        runs = resp.json().get("workflow_runs", [])
        if not runs:
            break

        all_runs.extend(runs)
        print(f"   -> Page {page}: {len(runs)} runs")

    return all_runs


def fetch_commits_rest(owner, repo, token, pages=3):

    print("Starting REST Commits...")
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    all_commits = []

    for page in range(1, pages + 1):
        resp = requests.get(url, headers=headers, params={"per_page": 30, "page": page})
        if resp.status_code != 200: break

        commits_summary = resp.json()
        if not commits_summary: break

        print(f"   -> Page {page}: Processing {len(commits_summary)} commits...")

        limit_detailed = 0
        for c in commits_summary:
            if limit_detailed >= 20 and page == 1: break
            limit_detailed += 1

            sha = c["sha"]
            det_resp = requests.get(f"{url}/{sha}", headers=headers)
            if det_resp.status_code == 200:
                all_commits.append(det_resp.json())

    return all_commits