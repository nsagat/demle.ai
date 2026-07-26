# demle

**Evidence-backed task delegation.** demle reads a repository's merged PRs and
review conversation, builds a capability graph of who has demonstrably built
what, and — when a new issue lands — recommends who should take it. Not by a
match score, but by evidence you can click through to.

**Live demo → https://demle-ai.vercel.app**

> The deployed link serves the UI. The live agent runs against a small Python
> backend (below); point the frontend at a running backend with
> `https://demle-ai.vercel.app/?api=<backend-url>`, or run the whole thing
> locally for the full experience.

---

## What it does

For each open issue, demle produces **exactly two recommendations**, and never
confuses the two kinds of signal behind them:

- **Evidence** — what someone has demonstrably shipped, derived from PRs and reviews.
- **Intent** — where someone has *said* they want to grow. Self-reported, never inferred.

That yields:

- **Ships fast** — strongest evidence, currently active, has capacity.
- **Develops** — stated interest in the area, thinner evidence, paired with a mentor who has it.

It also flags **bus-factor risk**: when an area's only owners have gone inactive,
demle reconstructs what they knew from the actual review threads into a
downloadable `SKILL.md` — quotes from real reviewers, not generic best practice.

Everything is shown as counts and artifact titles you can verify. No scores, no
rankings, no assignments made on your behalf — the human picks.

## Architecture

```
ingest.py   GitHub GraphQL → merged PRs, reviews, open issues   → data/<repo>/repo.json
extract.py  repo.json → capability graph (via Claude)           → data/<repo>/graph.json
agent.py    FastAPI: tools over the cached graphs, streamed      → the live agent (SSE)
web/        React + Vite frontend                                → the register + trace + cards
```

- The agent is a real tool-use loop over the cached graph (search evidence,
  check workload, check bus factor, reconstruct skills…), streamed to the UI as
  Server-Sent Events so each step appears live.
- Multi-repo aware: a contributor thin in one repo can surface on the strength
  of their work in another.

## Run it locally

Requires Python 3, Node 18+, an `ANTHROPIC_API_KEY`, and (to ingest new repos) a `GITHUB_TOKEN`.

```bash
# 1. backend — serves the cached graphs under data/ on :8000
export ANTHROPIC_API_KEY=sk-ant-...
python3 agent.py

# 2. frontend — Vite dev server on :5173, proxies /api -> :8000
cd web && npm install && npm run dev
```

Open http://localhost:5173, pick a real issue, and watch the agent work.

### Ingesting a fresh repo

```bash
export GITHUB_TOKEN=ghp_...
python3 ingest.py  triton-inference-server/client --prs 150 > data/triton-inference-server__client/repo.json
python3 extract.py data/triton-inference-server__client/repo.json     > data/triton-inference-server__client/graph.json
```

## Deployment

The frontend deploys as a static site (this repo → Vercel, building `web/` per
`vercel.json`). The Python backend is hosted separately; the frontend finds it via:

1. `?api=<url>` query param (persisted) — handy for ephemeral tunnel URLs
2. `VITE_API_BASE` build-time env var
3. same-origin (dev, via the Vite proxy)

## Stack

Claude (Anthropic API) · FastAPI · React + Vite · GitHub GraphQL

## Repo layout

| Path | What |
|------|------|
| `ingest.py` / `extract.py` | build the capability graph from a repo's history |
| `agent.py` | the live agent + API (`/api/repos`, `/api/graph`, `/api/issues`, `/api/assign`, `/api/skill`) |
| `web/src/Ledger.jsx` | the single-screen UI: register, live trace, recommendation cards |
| `web/src/api.js` | SSE client + API-base resolution |
| `Demle.dc.html` | the original design reference (static prototype) |
| `docs/superpowers/specs/` | design notes |
