#!/usr/bin/env python3
"""
demle — stage 1: ingest a repo's merged PRs, reviews, and open issues via GitHub GraphQL.

    export GITHUB_TOKEN=ghp_xxx
    python3 ingest.py owner/repo --prs 200 > data/repo.json
"""

import json, os, sys, urllib.request, urllib.error

TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("Set GITHUB_TOKEN. GraphQL has no anonymous access.")

PR_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(first:50, states:MERGED,
                 orderBy:{field:UPDATED_AT, direction:DESC}, after:$cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title bodyText mergedAt
        author { login }
        files(first:60) { nodes { path additions deletions } }
        reviews(first:25) {
          nodes { author { login } state bodyText }
        }
        reviewThreads(first:25) {
          nodes { comments(first:5) { nodes { author { login } bodyText path } } }
        }
        closingIssuesReferences(first:5) { nodes { number title } }
      }
    }
  }
}
"""

ISSUE_QUERY = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) {
    issues(first:40, states:OPEN, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        number title bodyText createdAt
        labels(first:8) { nodes { name } }
        comments { totalCount }
      }
    }
  }
}
"""


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:300]}")
    if "errors" in out:
        sys.exit("GraphQL error: " + json.dumps(out["errors"])[:400])
    return out["data"]


def ingest(repo, max_prs):
    owner, name = repo.split("/")
    prs, cursor = [], None

    while len(prs) < max_prs:
        data = gql(PR_QUERY, {"owner": owner, "name": name, "cursor": cursor})
        page = data["repository"]["pullRequests"]
        for pr in page["nodes"]:
            if not pr.get("author"):
                continue  # deleted account

            threads = []
            for t in pr["reviewThreads"]["nodes"]:
                for c in t["comments"]["nodes"]:
                    if c.get("author"):
                        threads.append({
                            "login": c["author"]["login"],
                            "path": c.get("path"),
                            "body": (c.get("bodyText") or "")[:300],
                        })

            prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "body": (pr.get("bodyText") or "")[:800],
                "author": pr["author"]["login"],
                "merged_at": pr["mergedAt"],
                "files": [f["path"] for f in pr["files"]["nodes"]],
                "additions": sum(f["additions"] for f in pr["files"]["nodes"]),
                "reviews": [
                    {"login": r["author"]["login"], "state": r["state"],
                     "body": (r.get("bodyText") or "")[:300]}
                    for r in pr["reviews"]["nodes"] if r.get("author")
                ],
                "review_comments": threads,
                "closes_issues": [i["number"] for i in pr["closingIssuesReferences"]["nodes"]],
            })
        print(f"  {len(prs)} PRs…", file=sys.stderr)
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    prs = prs[:max_prs]

    issues = gql(ISSUE_QUERY, {"owner": owner, "name": name})["repository"]["issues"]["nodes"]
    issues = [{
        "number": i["number"], "title": i["title"],
        "body": (i.get("bodyText") or "")[:1200],
        "labels": [l["name"] for l in i["labels"]["nodes"]],
        "comments": i["comments"]["totalCount"],
        "created_at": i["createdAt"],
    } for i in issues]

    people = {}
    for pr in prs:
        p = people.setdefault(pr["author"], {"login": pr["author"], "prs": 0,
                                             "reviews": 0, "files": {}, "last_seen": None})
        p["prs"] += 1
        if pr["merged_at"] and (not p["last_seen"] or pr["merged_at"] > p["last_seen"]):
            p["last_seen"] = pr["merged_at"]
        for f in pr["files"]:
            p["files"][f] = p["files"].get(f, 0) + 1
        for r in pr["reviews"]:
            if r["login"] != pr["author"]:
                q = people.setdefault(r["login"], {"login": r["login"], "prs": 0,
                                                   "reviews": 0, "files": {}, "last_seen": None})
                q["reviews"] += 1
                if pr["merged_at"] and (not q["last_seen"] or pr["merged_at"] > q["last_seen"]):
                    q["last_seen"] = pr["merged_at"]

    for p in people.values():
        p["top_files"] = sorted(p["files"].items(), key=lambda x: -x[1])[:15]
        del p["files"]

    return {"repo": repo, "pr_count": len(prs),
            "people": sorted(people.values(), key=lambda p: -(p["prs"] + p["reviews"])),
            "prs": prs, "open_issues": issues}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: ingest.py owner/repo [--prs N]")
    n = 200
    if "--prs" in sys.argv:
        n = int(sys.argv[sys.argv.index("--prs") + 1])
    print(f"ingesting {sys.argv[1]}…", file=sys.stderr)
    out = ingest(sys.argv[1], n)
    print(f"done: {out['pr_count']} PRs, {len(out['people'])} contributors, "
          f"{len(out['open_issues'])} open issues", file=sys.stderr)
    print(json.dumps(out, indent=2))
