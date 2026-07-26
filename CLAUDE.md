# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What demle is

Evidence-backed task delegation. demle ingests a real GitHub repo's history (merged PRs, reviews, review conversation), builds a capability graph of who has demonstrably built what, and when an issue is opened an agent proposes two assignees — the person who ships fastest and the person the work would grow — with a human making the final call.

## Hard product constraints (not style preferences)

- **Never emit a percentage, match score, or skill rating.** Confidence is `strong` / `moderate` / `thin` only.
- **Never read or model private DMs.** Public PRs, reviews, and team channels only.
- **The agent recommends; a human approves.** Nothing assigns autonomously.
- **Every claim about a person cites the artifact behind it** (PR number + title).
- Stated intent (`data/profiles.json`) is self-reported or from a meeting note — **never inferred** from behavior. Keep evidence and intent visually and semantically separate everywhere.
- Never describe a contributor as weak or deficient. Review iteration reflects problem difficulty as much as skill; speak in terms of trajectory.

## Pipeline architecture

Three offline/online stages, connected only through JSON files in `data/` (gitignored except `graph.json`):

```
ingest.py   owner/repo → data/repo.json      GitHub GraphQL: merged PRs, reviews,
                                             review threads, open issues, per-person rollups
extract.py  repo.json  → data/graph.json     Claude (claude-sonnet-4-6) derives per-person
                                             capability areas + per-area bus-factor risk.
                                             COSTS API TOKENS — run once per repo, never in a loop
agent.py    FastAPI on :8000                 Live agent. 7 pure-function tools over the cached
                                             graph (no network to GitHub). Streams its tool loop
                                             over SSE. Model: claude-sonnet-4-6 via raw urllib
web/        Vite + React                     Ledger.jsx renders the one-screen UI: capability
                                             register, live agent trace, two assignment cards
data/profiles.json                           Stated intent per login — maintained BY HAND;
                                             every key must be a real login present in graph.json
```

Secrets live in `.env` at the repo root (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`) — gitignored; `source .env` before running any stage. The Anthropic key is backend-only; `web/` must never reference it (the frontend only talks to `localhost:8000`).

## Commands

```bash
source .env                                                    # loads both tokens
python3 ingest.py triton-inference-server/client --prs 150 > data/repo.json
python3 extract.py data/repo.json > data/graph.json            # costs tokens — run ONCE
python3 agent.py                                               # server on :8000
cd web && npm run dev                                          # UI on :5173
```

Verification without the UI:

```bash
curl -s localhost:8000/api/graph | python3 -m json.tool | head -30
curl -s localhost:8000/api/issues | head -c 500
curl -N -X POST localhost:8000/api/assign -H 'Content-Type: application/json' \
  -d '{"issue":"#885 Remove upper bound on grpcio\n\n<body>"}'
```

A healthy `/api/assign` stream shows **many `type: step` events before `type: done`** — one step then done means the tool_use loop is broken (check `tool_use_id` pairing in tool_result blocks). The `done` event carries `recommendations` (kinds `ships_fast` and `develops`) and `risks`; if `recommendations` is empty and a `raw` field is present, the model returned prose around the JSON and the closing-instruction/parse needs tightening.

There are no tests, no linter, no build system beyond Vite. This is a hackathon codebase — do not add tests, config systems, error middleware, databases, or refactors for elegance.

## Data contract

`agent.py` endpoints are the contract; `web/src/Ledger.jsx` is the consumer. Key shapes:

- `GET /api/graph` → `{repo, people: [{id, name, monthsInactive, evidence: {area: {prs, reviews, confidence}}, wants, goal}], areas}`
- `GET /api/issues` → top open issues `[{number, title, body, labels, comments}]`
- `POST /api/assign` `{issue}` → SSE, each event `data: {json}\n\n`:
  - `{type: "step", tool, arg, result, kind: "evidence"|"intent"|"risk"}` — `kind` drives trace-line color
  - `{type: "done", recommendations: [...], risks: [...]}`

If you change a payload shape, update both sides in the same edit.

## Gotchas

- GitHub's GraphQL endpoint intermittently returns 502 on this heavy PR query — just retry `ingest.py`; it typically succeeds within 1–3 attempts.
- The agent server's process name is `Python agent.py` on macOS — `pkill -f agent.py` works, `pkill -f "python3 agent.py"` does not. A stale server holding :8000 makes a restarted one exit with "address already in use" while curls still get answered by the old code.
- `extract.py`'s per-area names come from the model and are fragmented (near-duplicate areas); `agent.py` tools compensate with substring/loose matching — keep matching loose when editing tools.
- `data/graph.json` is deliberately committed (crash backup for the demo); the rest of `data/` is gitignored.

## Design reference

`README.md` is the full frontend design brief (tokens, typography, layout, interactions); `Demle.dc.html` is the high-fidelity prototype it describes, including fixture data and the trace/register/assignment behavior. Fidelity is final: Lora / Inter / IBM Plex Mono, forest `#1F3A2E` on paper `#F4F6F2`, no border radius, no shadows. Evidence renders solid forest; intent renders dashed sage `#567F63`; risk renders rust `#A85438`.
