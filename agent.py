#!/usr/bin/env python3
"""
demle — stage 3: the live agent.

    export ANTHROPIC_API_KEY=sk-ant-xxx
    python3 agent.py            # → http://localhost:8000
    python3 agent.py --test     # run one issue end to end, print the trace

Serves every repo under data/<owner>__<repo>/. Tools run over the cached
graphs; cross-repo recall lets a person thin in one repo surface on the
strength of their work in another. Never calls GitHub except when adding a
new repo (POST /api/repos), which shells out to ingest.py + extract.py.

Endpoints
    GET  /api/repos              ingested repos + headline stats
    GET  /api/graph?repo=<slug>  capability register for one repo
    GET  /api/issues?repo=<slug> open issues for one repo
    POST /api/assign             SSE: trace steps, then recommendations
    POST /api/repos              SSE: ingest+extract a pasted GitHub URL
"""

import json, os, re, sys, asyncio, subprocess, urllib.request
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

KEY = os.environ["ANTHROPIC_API_KEY"]
DATA = Path("data")
PROFILES = json.load(open(DATA / "profiles.json"))

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── repo registry ────────────────────────────────────────────────
# One entry per data/<slug>/ dir holding graph.json + repo.json.

def slug_for(repo):
    return repo.replace("/", "__")


def load_repo(slug):
    d = DATA / slug
    graph = json.load(open(d / "graph.json"))
    repo = json.load(open(d / "repo.json"))
    return {
        "slug": slug, "name": graph["repo"], "graph": graph, "repo": repo,
        "people": {p["login"]: p for p in graph["people"]},
        "areas": {a["area"]: a for a in graph["areas"]},
    }


REPOS = {}


def load_all():
    REPOS.clear()
    for d in sorted(DATA.iterdir()):
        if d.is_dir() and (d / "graph.json").exists() and (d / "repo.json").exists():
            REPOS[d.name] = load_repo(d.name)


load_all()
DEFAULT_REPO = next(iter(REPOS), None)


def person_history(login):
    """Everything one login has demonstrated across every ingested repo."""
    out = []
    for slug, R in REPOS.items():
        p = R["people"].get(login)
        if not p:
            continue
        for a in p["areas"]:
            out.append({
                "repo": R["name"], "slug": slug, "area": a["area"],
                "confidence": a["confidence"],
                "pr_count": a.get("pr_count", len(a.get("prs", []))),
                "review_count": a.get("review_count", 0),
                "artifacts": a.get("artifacts", [])[:3],
                "months_inactive": p.get("months_inactive"),
            })
    return out


# ── tools — pure functions over the cached graphs, no network ─────

def _tokens(s):
    return {t for t in re.split(r"[^a-z0-9+]+", (s or "").lower()) if len(t) > 2}


def analyze_issue(text: str, repo: str = None):
    return {"note": "model-derived", "areas": text}


def search_evidence(capability: str, repo: str = None):
    """Contributors with demonstrated work in a capability, across ALL repos.
    Each hit is tagged with its repo and whether it is the issue's own repo,
    so a person thin here but strong elsewhere still surfaces."""
    cap = capability.lower()
    terms = _tokens(cap)
    hits = []
    for slug, R in REPOS.items():
        for login, p in R["people"].items():
            for a in p["areas"]:
                al = a["area"].lower()
                if cap in al or al in cap or any(t in al for t in terms):
                    hits.append({
                        "login": login, "repo": R["name"], "slug": slug,
                        "same_repo": slug == repo,
                        "area": a["area"],
                        "pr_count": a.get("pr_count", len(a.get("prs", []))),
                        "review_count": a.get("review_count", 0),
                        "confidence": a["confidence"],
                        "artifacts": a.get("artifacts", [])[:3],
                        "months_inactive": p.get("months_inactive"),
                    })
    hits.sort(key=lambda h: (
        0 if h["same_repo"] else 1,
        {"strong": 0, "moderate": 1, "thin": 2}[h["confidence"]],
        -(h["pr_count"] + h["review_count"] * 0.6),
    ))
    return {"capability": capability, "contributors": hits[:8], "count": len(hits)}


def recall_across_repos(login: str, repo: str = None):
    """Full cross-repo history for one contributor. Call this before
    recommending someone whose evidence in the issue's repo is thin —
    they may be strong in the same area in another repo."""
    hist = person_history(login)
    repos = sorted({h["repo"] for h in hist})
    strong = [h for h in hist if h["confidence"] == "strong"]
    return {"login": login, "repos_active_in": repos,
            "evidence": hist, "strong_areas": [h["area"] for h in strong]}


def get_workload(login: str, repo: str = None):
    """Current load for a login: open PRs authored + issues assigned to them,
    summed across every repo; activity from the most recent graph."""
    open_prs, assigned = [], []
    months = None
    for slug, R in REPOS.items():
        for pr in R["repo"]["prs"]:
            if pr["author"] == login and not pr.get("merged_at"):
                open_prs.append(pr["title"])
        for i in R["repo"]["open_issues"]:
            if login in (i.get("assignees") or []):
                assigned.append(i["title"])
        p = R["people"].get(login)
        if p and p.get("months_inactive") is not None:
            months = p["months_inactive"] if months is None else min(months, p["months_inactive"])
    return {"login": login, "open_prs": open_prs[:5], "assigned_issues": assigned[:5],
            "load": len(open_prs) + len(assigned), "months_inactive": months,
            "active": (months or 99) < 6}


def get_development_profile(login: str, repo: str = None):
    """Stated intent. NEVER inferred — self-reported or from a meeting note."""
    prof = PROFILES.get(login)
    if not prof:
        return {"login": login, "stated": False, "note": "no stated goals on file"}
    return {"login": login, "stated": True, "wants": prof.get("wants", []),
            "goal": prof.get("goal", ""), "source": prof.get("source", "self-reported")}


def get_learning_trajectory(login: str, area: str = "", repo: str = None):
    """Review rounds over time across repos. High iteration means a hard
    problem or a thorough reviewer as often as struggle — trajectory,
    not deficiency."""
    prs = []
    for R in REPOS.values():
        prs += [pr for pr in R["repo"]["prs"] if pr["author"] == login and pr.get("merged_at")]
    if area:
        prs = [pr for pr in prs if any(area.split()[0].lower() in f.lower() for f in pr["files"])]
    prs.sort(key=lambda p: p["merged_at"] or "")
    seq = [{"pr": pr["number"], "merged": (pr["merged_at"] or "")[:10],
            "change_requests": sum(1 for r in pr["reviews"] if r["state"] == "CHANGES_REQUESTED"),
            "review_comments": len(pr["review_comments"])} for pr in prs]
    if len(seq) < 3:
        return {"login": login, "area": area, "sequence": seq, "trend": "insufficient history"}
    half = len(seq) // 2
    early = sum(s["change_requests"] for s in seq[:half]) / max(half, 1)
    late = sum(s["change_requests"] for s in seq[half:]) / max(len(seq) - half, 1)
    trend = ("improving" if late < early - 0.5 else
             "steady" if abs(late - early) <= 0.5 else "increasing")
    return {"login": login, "area": area, "sequence": seq[-8:],
            "early_avg_change_requests": round(early, 1),
            "recent_avg_change_requests": round(late, 1), "trend": trend}


def check_bus_factor(area: str, repo: str = None):
    """Bus factor for an area, scoped to the issue's repo when given, so a
    critical gap here is not masked by another repo owning the same area."""
    R = REPOS.get(repo)
    pool = R["areas"] if R else {a: v for Rx in REPOS.values() for a, v in Rx["areas"].items()}
    for name, a in pool.items():
        if area.lower() in name.lower() or name.lower() in area.lower():
            return {"area": name, "holders": a["holder_count"],
                    "active_holders": a["active_count"], "risk": a["risk"],
                    "detail": a["holders"]}
    return {"area": area, "holders": 0, "active_holders": 0, "risk": "critical",
            "detail": "no contributor has demonstrated work in this area"}


def generate_skills_file(area: str, repo: str = None):
    """Reconstruct what departed owners knew, from review conversation."""
    notes, files = [], {}
    pool = [REPOS[repo]["repo"]] if repo in REPOS else [R["repo"] for R in REPOS.values()]
    for rp in pool:
        for pr in rp["prs"]:
            if not any(area.split()[0].lower() in f.lower() for f in pr["files"]):
                continue
            for f in pr["files"]:
                files[f] = files.get(f, 0) + 1
            for c in pr["review_comments"]:
                if len(c["body"]) > 40:
                    notes.append({"pr": pr["number"], "by": c["login"],
                                  "path": c.get("path"), "note": c["body"][:300]})
    return {"area": area, "review_notes": notes[:60],
            "top_files": sorted(files.items(), key=lambda x: -x[1])[:15]}


TOOLS = {
    "analyze_issue": analyze_issue,
    "search_evidence": search_evidence,
    "recall_across_repos": recall_across_repos,
    "get_workload": get_workload,
    "get_development_profile": get_development_profile,
    "get_learning_trajectory": get_learning_trajectory,
    "check_bus_factor": check_bus_factor,
    "generate_skills_file": generate_skills_file,
}

TOOL_KIND = {
    "analyze_issue": "evidence", "search_evidence": "evidence",
    "recall_across_repos": "intent", "get_workload": "evidence",
    "get_learning_trajectory": "evidence", "get_development_profile": "intent",
    "check_bus_factor": "risk", "generate_skills_file": "risk",
}

SCHEMA = [
    {"name": "analyze_issue",
     "description": "Record the technical capabilities an issue requires. Call this first with a comma-separated list of areas you identified.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "search_evidence",
     "description": "Find contributors with demonstrated work in a capability, across ALL repos. Each result is tagged with its repo and same_repo (true if it is the issue's own repo). Someone strong in this capability in ANOTHER repo is a real candidate — surface them.",
     "input_schema": {"type": "object", "properties": {"capability": {"type": "string"}}, "required": ["capability"]}},
    {"name": "recall_across_repos",
     "description": "Full cross-repo history for one contributor. Call this before recommending anyone whose evidence in the issue's repo is thin — they may be strong in the same area in another repo, and that cross-repo evidence should be cited.",
     "input_schema": {"type": "object", "properties": {"login": {"type": "string"}}, "required": ["login"]}},
    {"name": "get_workload",
     "description": "What a contributor is currently working on across all repos, and whether they are still active.",
     "input_schema": {"type": "object", "properties": {"login": {"type": "string"}}, "required": ["login"]}},
    {"name": "get_development_profile",
     "description": "A contributor's STATED interests and growth goals. Self-reported, never inferred. Use this to identify stretch assignments.",
     "input_schema": {"type": "object", "properties": {"login": {"type": "string"}}, "required": ["login"]}},
    {"name": "get_learning_trajectory",
     "description": "How a contributor's review iteration has changed over time in an area. Improving trend means they are picking it up. Do NOT read high iteration as poor performance — it tracks problem difficulty too.",
     "input_schema": {"type": "object", "properties": {"login": {"type": "string"}, "area": {"type": "string"}}, "required": ["login"]}},
    {"name": "check_bus_factor",
     "description": "How concentrated knowledge of an area is in the issue's repo, and whether the holders are still active.",
     "input_schema": {"type": "object", "properties": {"area": {"type": "string"}}, "required": ["area"]}},
    {"name": "generate_skills_file",
     "description": "Reconstruct a subsystem's conventions from review conversation. Call ONLY when check_bus_factor returns critical — the owners are gone but their knowledge is in the review history.",
     "input_schema": {"type": "object", "properties": {"area": {"type": "string"}}, "required": ["area"]}},
]

SYSTEM = """You assign engineering work across a team that maintains several related repositories.

You have two different kinds of signal and must never confuse them:
  EVIDENCE — what someone has demonstrably built. Derived from PRs and reviews.
  INTENT   — where someone wants to go. Stated by them. Never inferred, never guessed.

The team works across multiple repos. A person's capability is the SUM of what
they have shipped everywhere, not only in the repo the issue was filed in.
  - search_evidence returns hits across every repo, tagged same_repo.
  - When a promising candidate is thin in this repo, call recall_across_repos to
    check whether they are strong in the same capability in another repo. If they
    are, that is strong evidence — cite the other repo's PRs explicitly.

Your job for each issue: produce exactly two recommendations.
  ships_fast — strongest evidence (this repo or another), currently active, has room
  develops   — stated interest in this area, thinner evidence, paired with a
               mentor who has strong evidence in it

Rules:
- Always check workload before recommending. Do not recommend someone inactive
  for more than six months, or already saturated.
- Check bus factor for every area the issue touches. If an area is critical,
  call generate_skills_file.
- Report demonstrated work as counts with artifact titles, and name the repo each
  artifact came from. Never emit a percentage, match score, or skill rating.
- Never describe a contributor as weak, deficient, or lacking. Review iteration
  reflects problem difficulty as much as skill. Speak in terms of trajectory.
- One sentence of reasoning per recommendation, citing specific evidence and its repo.

When done, output ONLY this JSON, no fences:
{"recommendations":[{"kind":"ships_fast|develops","person":"","confidence":"strong|moderate|thin",
"reasoning":"","stats":[["5","PRs"],["3","reviews"],["2","open"]],
"artifacts":["repo#123 title"],"mentor":{"name":"","why":""}}],
"risks":[{"area":"","holders":0,"activeHolders":0,"level":"ok|high|critical","detail":""}]}"""


def call_claude(messages):
    body = json.dumps({
        "model": "claude-sonnet-4-6", "max_tokens": 2500,
        "system": SYSTEM, "tools": SCHEMA, "messages": messages,
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
    req.add_header("x-api-key", KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def summarize(tool, result):
    if tool == "search_evidence":
        n = result["count"]
        top = result["contributors"][0] if result["contributors"] else None
        tag = f" · {top['login']} ({top['repo']}: {top['confidence']})" if top else ""
        return f"{n} hit{'s' if n != 1 else ''}{tag}"
    if tool == "recall_across_repos":
        r = result["repos_active_in"]
        return f"{result['login']} across {len(r)} repo{'s' if len(r) != 1 else ''}: {', '.join(r)}"
    if tool == "get_workload":
        return (f"{result['load']} open · inactive {result['months_inactive']}mo"
                if not result["active"] else f"{result['load']} open · available")
    if tool == "get_development_profile":
        return ("wants: " + ", ".join(result["wants"]) + " · stated"
                if result["stated"] else "no stated goals")
    if tool == "get_learning_trajectory":
        return f"trend: {result['trend']}"
    if tool == "check_bus_factor":
        return (f"⚠ {result['active_holders']} active owner(s) · {result['risk']}"
                if result["risk"] != "ok" else f"{result['active_holders']} active owners")
    if tool == "generate_skills_file":
        return f"reconstructing · {len(result['review_notes'])} threads"
    return "ok"


async def run_agent(issue_text: str, repo: str):
    messages = [{"role": "user", "content":
                 f"An issue was opened in the `{REPOS[repo]['name']}` repository:\n\n"
                 f"{issue_text}\n\nDecide who should take it."}]

    for _ in range(14):
        data = await asyncio.to_thread(call_claude, messages)
        tool_uses = [b for b in data["content"] if b["type"] == "tool_use"]
        text = "".join(b["text"] for b in data["content"] if b["type"] == "text")

        if not tool_uses:
            cleaned = text.replace("```json", "").replace("```", "")
            start, end = cleaned.find("{"), cleaned.rfind("}")
            try:
                payload = json.loads(cleaned[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                payload = {"recommendations": [], "risks": [], "raw": text}
            yield {"type": "done", **payload}
            return

        messages.append({"role": "assistant", "content": data["content"]})
        results = []
        for tu in tool_uses:
            fn = TOOLS[tu["name"]]
            out = fn(**tu["input"], repo=repo)
            yield {"type": "step", "tool": tu["name"],
                   "arg": str(list(tu["input"].values())[0])[:40] if tu["input"] else "",
                   "result": summarize(tu["name"], out),
                   "kind": TOOL_KIND.get(tu["name"], "evidence")}
            await asyncio.sleep(0.25)
            results.append({"type": "tool_result", "tool_use_id": tu["id"],
                            "content": json.dumps(out)[:6000]})
        messages.append({"role": "user", "content": results})

    yield {"type": "done", "recommendations": [], "risks": [], "error": "hit turn limit"}


# ── routes ───────────────────────────────────────────────────────

def repo_card(R):
    prs = R["repo"]["prs"]
    return {"slug": R["slug"], "repo": R["name"],
            "contributors": len(R["graph"]["people"]),
            "prs": len(prs), "reviews": sum(len(pr["reviews"]) for pr in prs),
            "issues": len(R["repo"]["open_issues"])}


@app.get("/api/repos")
def repos():
    return JSONResponse([repo_card(R) for R in REPOS.values()])


@app.get("/api/graph")
def graph(repo: str = None):
    R = REPOS.get(repo) or REPOS.get(DEFAULT_REPO)
    prs = R["repo"]["prs"]
    return JSONResponse({
        "repo": R["name"], "slug": R["slug"],
        "stats": {"prs": len(prs), "reviews": sum(len(pr["reviews"]) for pr in prs),
                  "contributors": len(R["graph"]["people"])},
        "people": [{
            "id": p["login"], "name": p["login"],
            "monthsInactive": p.get("months_inactive"),
            "load": get_workload(p["login"])["load"],
            "evidence": {a["area"]: {"prs": a.get("pr_count", 0),
                                     "reviews": a.get("review_count", 0),
                                     "confidence": a["confidence"]}
                         for a in p["areas"]},
            "otherRepos": sorted({h["repo"] for h in person_history(p["login"])
                                  if h["repo"] != R["name"]}),
            "wants": PROFILES.get(p["login"], {}).get("wants", []),
            "goal": PROFILES.get(p["login"], {}).get("goal", ""),
            "goalSource": PROFILES.get(p["login"], {}).get("source", ""),
        } for p in R["graph"]["people"]],
        "areas": [{"area": a["area"], "risk": a["risk"],
                   "holders": a["holder_count"], "active": a["active_count"]}
                  for a in R["graph"]["areas"]],
    })


@app.get("/api/issues")
def issues(repo: str = None):
    R = REPOS.get(repo) or REPOS.get(DEFAULT_REPO)
    return JSONResponse(R["graph"]["open_issues"][:20])


@app.get("/api/skill")
def skill(area: str = "", repo: str = None):
    """Reconstruct a SKILL.md from the real review conversation on an area.
    Reuses the same tools the agent calls and renders their output as Markdown —
    nothing invented; every line traces to a PR thread."""
    slug = repo if repo in REPOS else DEFAULT_REPO
    bus = check_bus_factor(area, slug)
    canonical = bus["area"]
    data = generate_skills_file(canonical, slug)
    notes, top_files = data["review_notes"], data["top_files"]
    repo_name = REPOS[slug]["name"] if slug in REPOS else "multiple repos"

    lines = [f"# SKILL — {canonical}", "",
             f"Reconstructed by demle for `{repo_name}`.",
             f"Risk: **{bus['risk']}** · {bus['active_holders']} active holder(s) of {bus['holders']} total.",
             f"Sources: {len(notes)} review thread(s) across {len(top_files)} files.",
             "Nothing here is inferred; every note is a real reviewer comment.", ""]
    if top_files:
        lines += ["## Load-bearing files", ""]
        lines += [f"- `{f}` — touched in {n} PR(s)" for f, n in top_files]
        lines.append("")
    if notes:
        lines += ["## What reviewers actually said", ""]
        for c in notes:
            where = f" · `{c['path']}`" if c.get("path") else ""
            lines += [f"- **PR #{c['pr']}** — @{c['by']}{where}", f"  > {' '.join(c['note'].split())}", ""]
    else:
        lines += ["## What reviewers actually said", "", "_No review conversation found for this area._", ""]

    md = "\n".join(lines)
    fname = "SKILL-" + re.sub(r"[^a-z0-9]+", "-", canonical.lower()).strip("-") + ".md"
    return Response(md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/assign")
async def assign(req: Request):
    body = await req.json()
    text = body.get("issue", "")
    repo = body.get("repo") or DEFAULT_REPO

    async def stream():
        try:
            async for ev in run_agent(text, repo):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/repos")
async def add_repo(req: Request):
    body = await req.json()
    url = (body.get("url") or "").strip()
    m = re.search(r"github\.com[/:]([^/]+)/([^/.\s]+)", url)
    if not m:
        return JSONResponse({"error": "not a github url"}, status_code=400)
    full = f"{m.group(1)}/{m.group(2)}"
    slug = slug_for(full)

    async def stream():
        def ev(t, **kw):
            return f"data: {json.dumps({'type': t, **kw})}\n\n"
        if slug in REPOS:
            yield ev("done", slug=slug, repo=full, note="already loaded")
            return
        d = DATA / slug
        d.mkdir(exist_ok=True)
        try:
            yield ev("progress", stage="ingest", msg=f"reading {full} from GitHub…")
            ok = False
            for attempt in range(3):
                r = await asyncio.to_thread(subprocess.run,
                    [sys.executable, "ingest.py", full, "--prs", "100"],
                    capture_output=True, text=True, env={**os.environ})
                if r.returncode == 0 and r.stdout.strip():
                    (d / "repo.json").write_text(r.stdout)
                    ok = True
                    break
                yield ev("progress", stage="ingest", msg=f"retry {attempt + 1} (github hiccup)…")
            if not ok:
                yield ev("error", message="ingest failed after retries")
                return
            yield ev("progress", stage="extract", msg="building capability graph with Claude…")
            r = await asyncio.to_thread(subprocess.run,
                [sys.executable, "extract.py", str(d / "repo.json")],
                capture_output=True, text=True, env={**os.environ})
            if r.returncode != 0 or not r.stdout.strip():
                yield ev("error", message="extract failed: " + r.stderr[-200:])
                return
            (d / "graph.json").write_text(r.stdout)
            REPOS[slug] = load_repo(slug)
            yield ev("done", **repo_card(REPOS[slug]))
        except Exception as e:
            yield ev("error", message=str(e))

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _test(issue_text, repo):
    async for ev in run_agent(issue_text, repo):
        if ev["type"] == "step":
            print(f"▸ {ev['tool']}({ev['arg']}) → {ev['result']}")
        else:
            print(json.dumps(ev, indent=2))


if __name__ == "__main__":
    if "--test" in sys.argv:
        repo = DEFAULT_REPO
        i = REPOS[repo]["graph"]["open_issues"][0]
        print(f"repo: {REPOS[repo]['name']} · issue: #{i['number']} {i['title']}")
        asyncio.run(_test(f"#{i['number']} {i['title']}\n\n{i['body']}", repo))
        sys.exit(0)
    import uvicorn
    print(f"repos: {', '.join(f'{s} ({len(R['graph']['people'])}p)' for s, R in REPOS.items())}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
