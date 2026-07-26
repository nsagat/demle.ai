#!/usr/bin/env python3
"""
demle — stage 2: build the capability graph from ingested repo data.

    export ANTHROPIC_API_KEY=sk-ant-xxx
    python3 extract.py data/repo.json > data/graph.json

Run once per repo; the live agent reads the cached graph.
"""

import json, os, sys, urllib.request
from datetime import datetime, timezone

KEY = os.environ.get("ANTHROPIC_API_KEY")
if not KEY:
    sys.exit("Set ANTHROPIC_API_KEY")


def claude(prompt, max_tokens=4000):
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
    req.add_header("x-api-key", KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req) as r:
        d = json.load(r)
    text = "".join(b["text"] for b in d["content"] if b["type"] == "text")
    return json.loads(text.replace("```json", "").replace("```", "").strip())


def months_since(iso):
    if not iso:
        return None
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return round((datetime.now(timezone.utc) - then).days / 30.4, 1)


def main(path):
    repo = json.load(open(path))
    people = repo["people"]

    # one batch per ~8 contributors keeps each prompt well inside limits
    graph = {"repo": repo["repo"], "people": []}
    batch = 8

    for i in range(0, len(people), batch):
        chunk = people[i:i + batch]
        logins = {p["login"] for p in chunk}

        evidence = []
        for pr in repo["prs"]:
            touches = pr["author"] in logins or any(r["login"] in logins for r in pr["reviews"])
            if not touches:
                continue
            evidence.append({
                "n": pr["number"], "title": pr["title"],
                "author": pr["author"],
                "files": pr["files"][:20],
                "reviewers": [r["login"] for r in pr["reviews"] if r["login"] != pr["author"]],
                "review_notes": [c["body"][:160] for c in pr["review_comments"]
                                 if c["login"] in logins][:4],
            })

        prompt = f"""Engineering activity from the open-source repository {repo['repo']}.

Contributors in this batch:
{json.dumps([{"login": p["login"], "prs": p["prs"], "reviews": p["reviews"],
              "top_files": p["top_files"]} for p in chunk], indent=1)}

Pull requests touching them:
{json.dumps(evidence[:70], indent=1)}

For each contributor, identify the technical areas they have DEMONSTRATED work in.
Derive areas from file paths and PR content — subsystems, technologies, concerns.
Use the repository's own vocabulary, not a generic skill taxonomy.

Rules:
- Demonstrated work only. Never assign a level, rating, score, or percentage.
- Cite the PR numbers supporting each area.
- Review work counts as demonstrated experience, weighted below authorship.
- If evidence is thin, mark it thin rather than inflating it.
- 2-6 areas per person. Skip contributors with no meaningful signal.

Return ONLY valid JSON, no fences, no preamble:
{{"people":[{{"login":"","areas":[{{"area":"","prs":[0],"pr_count":0,
"review_count":0,"confidence":"strong|moderate|thin",
"summary":"one specific sentence citing what they built"}}]}}]}}"""

        print(f"  batch {i//batch + 1}: {len(chunk)} contributors…", file=sys.stderr)
        try:
            out = claude(prompt)
            graph["people"].extend(out["people"])
        except Exception as e:
            print(f"  ! batch failed: {e}", file=sys.stderr)

    by_login = {p["login"]: p for p in repo["people"]}
    titles = {pr["number"]: pr["title"] for pr in repo["prs"]}
    for p in graph["people"]:
        src = by_login.get(p["login"], {})
        p["last_seen"] = src.get("last_seen")
        p["months_inactive"] = months_since(src.get("last_seen"))
        p["total_prs"] = src.get("prs", 0)
        p["total_reviews"] = src.get("reviews", 0)
        for a in p["areas"]:
            a["artifacts"] = [f"#{n} {titles.get(n,'')}" for n in a.get("prs", [])[:4]]

    areas = {}
    for p in graph["people"]:
        for a in p["areas"]:
            e = areas.setdefault(a["area"], {"area": a["area"], "holders": []})
            e["holders"].append({
                "login": p["login"], "confidence": a["confidence"],
                "months_inactive": p["months_inactive"],
            })
    for e in areas.values():
        strong = [h for h in e["holders"] if h["confidence"] == "strong"]
        active = [h for h in strong if (h["months_inactive"] or 99) < 6]
        e["holder_count"] = len(strong)
        e["active_count"] = len(active)
        e["risk"] = ("critical" if len(active) == 0 and strong else
                     "high" if len(active) == 1 else "ok")
    graph["areas"] = sorted(areas.values(), key=lambda a: -len(a["holders"]))
    graph["open_issues"] = repo["open_issues"]

    print(f"done: {len(graph['people'])} profiles, {len(graph['areas'])} areas",
          file=sys.stderr)
    print(json.dumps(graph, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/repo.json")
