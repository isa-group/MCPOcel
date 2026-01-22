import requests
import time


def fetch_github_data(owner, repo, token):
    """
    Trae Issues, PRs y REVIEWS.
    """
    query = """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        issues(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: ASC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            number title state createdAt closedAt
            author { login }
            labels(first: 5) {
              nodes { name color }
            }
          }
        }
        pullRequests(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: ASC}) {
            pageInfo { hasNextPage endCursor }
            nodes {
                number title state createdAt closedAt merged mergedAt baseRefName headRefName
                author { login }
                labels(first: 5) {
                  nodes { name color }
                }
                reviews(first: 10) {
                    nodes {
                        state
                        submittedAt
                        author { login }
                    }
                }
            }
        }
      }
    }
    """

    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {token}"}
    all_items = []
    cursor = None
    has_next = True

    print("Starting GraphQL...")
    while has_next:
        variables = {"owner": owner, "repo": repo, "cursor": cursor}
        try:
            resp = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
            if resp.status_code != 200:
                print(f"Error HTTP {resp.status_code}")
                break

            payload = resp.json()
            if "errors" in payload:
                print(f"Error GraphQL: {payload['errors'][0]['message']}")
                break

            data = payload.get("data", {}).get("repository", {})
            if not data: break

            page_issues = data.get("issues", {})
            page_prs = data.get("pullRequests", {})

            # Label the original to facilitate mapping
            for i in page_issues.get("nodes", []): i["type"] = "Issue"
            for p in page_prs.get("nodes", []): p["type"] = "PullRequest"

            nodes = page_issues.get("nodes", []) + page_prs.get("nodes", [])
            all_items.extend(nodes)

            cursor = page_issues.get("pageInfo", {}).get("endCursor")
            has_next = page_issues.get("pageInfo", {}).get("hasNextPage") or page_prs.get("pageInfo", {}).get(
                "hasNextPage")

            print(f"   -> {len(all_items)} accumulated items...")
            if len(all_items) > 1000: break

        except Exception as e:
            print(f"Excepción en GraphQL: {e}")
            break

    return all_items