# demle — frontend live-wiring + local run (design)

Date: 2026-07-25
Scope: BUILD_PLAN Phase 5 (frontend wired) + Phase 6 (two closers) + local run setup.
Phases 1–4 are already done: `data/repo.json`, `data/graph.json`, `data/profiles.json` exist and `agent.py` serves `/api/graph`, `/api/issues`, `/api/assign` (SSE).

## Problem

`web/src/App.jsx` imports `./Ledger.jsx`, which does not exist — the React app is broken.
`Demle.dc.html` is a complete, approved design comp, but it uses a bespoke `DCLogic`/`{{ }}`
template framework and **fake data** (Marcus Chen, 9 areas × 7 people). We need a real React
`Ledger.jsx` that reproduces the design and binds to the live backend against **real** data
(44 people × ~104 areas, real GitHub logins, real SSE agent trace).

## Backend contract (fixed — do not rewrite the agent loop)

- `GET /api/graph` → `{repo, stats:{prs,reviews,contributors}, people:[{id,name,monthsInactive,load,evidence:{area:{prs,reviews,confidence}},wants,goal,goalSource}], areas:[{area,risk,holders,active}]}`
- `GET /api/issues` → `[{number,title,body,labels,comments,created_at}]`
- `POST /api/assign` `{issue}` → SSE:
  - `step`: `{type:"step", tool, arg, result, kind}` where `kind ∈ evidence|intent|risk`
  - `done`: `{type:"done", recommendations:[{kind:"ships_fast|develops", person, confidence:"strong|moderate|thin", reasoning, stats:[["5","PRs"]…], artifacts:[…], mentor:{name,why}}], risks:[{area,holders,activeHolders,level:"ok|high|critical",detail}]}`

## Components (in `web/src/`)

- `Ledger.jsx` — the whole screen; owns fetch/SSE state. Split into small presentational pieces:
  - `<IssuePicker>` — real issues from `/api/issues`; selecting one sets the active issue; "run" button.
  - `<AgentTrace>` — dark panel; appends one line per `step`; auto-scrolls; blinking cursor while running.
  - `<Register>` — the capability matrix (curated window, see below).
  - `<Recommendations>` — the two cards (`ships_fast` → SHIPS FAST, `develops` → DEVELOPS) from `done.recommendations`, plus the red bus-factor banner from `done.risks`.
- `api.js` — `getGraph()`, `getIssues()`, `streamAssign(issueText, onEvent)` (fetch + ReadableStream SSE parser).
- Styling: inline styles ported from the comp (same palette `C`), or a co-located CSS module. Palette:
  ink `#F4F6F2`, entry/strong `#1F3A2E`, intent `#567F63`, flag `#A85438`, thin `#8A948B`, text `#2C3E33`, muted `#6E7B6F`, rule `#B7C2B4`, hair `#DCE3DA`.

## Register curation (approved)

104 areas × 44 people cannot render as the clean grid. Curate a readable window, honestly labeled:
- **Rows:** ~13 people ranked by total evidence volume (`Σ prs + reviews·0.6`), **bots filtered**
  (`copilot-pull-request-reviewer`, `greptile-apps`). Inactive (>6mo) render faded; the `monthsInactive`
  badge replaces the load badge for them (e.g. `20mo` in flag color).
- **Columns:** ~11 areas = union of the shown people's evidence areas, ranked by holder_count + volume,
  **seeded to include ≥1 critical/high-risk area** so the bus-factor story is visible in the grid.
- **Intent cells (dashed):** `profiles.json` `wants` are free-text ("rust grpc client") and won't match
  area labels exactly. Token-match `wants` → columns (same fuzzy spirit as backend `search_evidence`):
  lowercase, split on non-alphanumerics, a want matches a column if a shared token of length >2 exists.
  A dashed cell renders where a person wants an area they have no evidence in.
- Caption: "showing top N of 104 areas · M of 44 people" — honest about the subset.
- Trace-driven highlight: when a `step` names an area/person present in the window, tint that
  column/row; columns stay fixed (no mid-run reflow).

## SKILL.md closer (approved: add endpoint)

`generate_skills_file`'s real output (review notes from `review_comments`) never reaches the client today.
Add an **additive** `GET /api/skill?area=<area>` to `agent.py` that calls the existing `generate_skills_file`
and renders Markdown from the real notes/top-files. When `done.risks` contains a `critical`/`high` entry,
show the red banner with a `↓ SKILL.md` button that fetches this endpoint and triggers a download.
Does not touch the agent loop.

## Local run (deploy = local for now)

- `vite.config.js`: dev proxy `/api` → `http://localhost:8000` (no hardcoded host, CORS moot).
- Run: terminal 1 `python3 agent.py`; terminal 2 `cd web && npm run dev`.
- Document in `web/README.md` / root README.

## Verification (from BUILD_PLAN)

- Pick a real issue → trace lines appear **one at a time** (SSE not buffered).
- Register shows real logins; ≥1 faded inactive; ≥1 dashed intent cell.
- A critical-risk run surfaces the banner; `↓ SKILL.md` downloads a file whose body quotes real
  review comments (not generic best practices).

## Out of scope (YAGNI)

No auth, no DB, no tests harness, no public hosting, no rewrite of ingest/extract/agent loop.
