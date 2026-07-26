# demle — build plan

Product: **demle** — evidence-backed task delegation.
You have working files already. This is wiring and fixing, not building from zero.
Do not let Claude Code rewrite what already runs.

---

## Ground rules for the agent

**One phase per prompt.** Never say "build the whole app." Claude Code is good at scoped
tasks and bad at knowing when it's done with vague ones. Give it a phase, verify, then
give it the next.

**Verify yourself, every time.** Every phase below has a command that produces output you
can read. Run it. An agent that reports success is not evidence of success — the output is.

**Paste `CLAUDE.md` into the project root first.** Claude Code reads it automatically and
it carries the constraints that matter (no scores, no DMs, propose-don't-assign).

**When something breaks, paste the actual error.** Not "it doesn't work." The traceback.

**Reject scope creep on sight.** If it starts adding tests, a config system, error
middleware, or a database — stop it. You have hours, not days.

---

## Phase 0 · Setup — 10 min

```bash
mkdir demle && cd demle && mkdir data
# drop in: CLAUDE.md ingest.py extract.py skills.py agent.py DESIGN.md Ledger.jsx
npm create vite@latest web -- --template react
cd web && npm install && cd ..
pip install fastapi uvicorn
export GITHUB_TOKEN=ghp_xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
```

✅ **Check:** `echo $GITHUB_TOKEN | head -c 8` prints something.

---

## Phase 1 · Real data in — 20 min · HIGHEST RISK, DO FIRST

Everything downstream is dead if this fails, so find out now.

```bash
python3 ingest.py triton-inference-server/client --prs 150 > data/repo.json
```

✅ **Check:**
```bash
python3 -c "
import json; d=json.load(open('data/repo.json'))
print(d['pr_count'],'PRs |',len(d['people']),'people |',len(d['open_issues']),'issues')
print('reviews on PR0:', len(d['prs'][0]['reviews']))
print('review comments:', sum(len(p['review_comments']) for p in d['prs']))
"
```

**You need:** 100+ PRs, 10+ contributors, and — critically — **review comments in the
hundreds**. Review conversation is where capability signal lives. If that number is under
50, the repo has a thin review culture and demle will have nothing to read.

**If the repo is thin, switch now, not later.** Try `honojs/hono` or `astral-sh/ruff`.
Losing 10 minutes here beats discovering it at Phase 4.

---

## Phase 2 · Capability graph — 15 min · COSTS REAL TOKENS

```bash
python3 extract.py data/repo.json > data/graph.json
```

Run it **once**. Do not re-run while iterating on anything else.

✅ **Check:**
```bash
python3 -c "
import json; g=json.load(open('data/graph.json'))
for p in g['people'][:6]:
    print(p['login'], p.get('months_inactive'),'mo')
    for a in p['areas']: print('   ', a['area'], a['confidence'], a.get('artifacts',[])[:1])
print()
for a in g['areas'][:8]: print(a['area'], '| holders', a['holder_count'], '| active', a['active_count'], '|', a['risk'])
"
```

**🔴 Now stop and read the output properly. This is the most important ten minutes of the build.**

You are looking for three real facts that become your demo:

1. **An area with `risk: critical` or `high`** — one owner, inactive. That's your bus factor beat.
2. **A contributor with strong evidence in something unexpected** — the hidden expert.
3. **An open issue that maps onto one of these areas** — `python3 -c "import json;[print(i['number'],i['title']) for i in json.load(open('data/graph.json'))['open_issues'][:20]]"`

Write these three down. **The demo is these facts.** Everything else is presentation.

If the areas came back generic ("backend", "testing"), the extraction prompt didn't bite —
tell Claude Code to push it toward the repo's own vocabulary and re-run once.

---

## Phase 3 · profiles.json — 10 min · BY HAND

Stated intent has no automated source. That's the point, not a gap.

```json
{
  "<real-login-1>": { "wants": ["grpc"],
    "goal": "Understand the wire protocol properly.",
    "source": "eng sync 2026-06-14" },
  "<real-login-2>": { "wants": ["python client"],
    "goal": "Ship a feature, not just tooling.",
    "source": "1:1 2026-07-02" }
}
```

Use **real logins from your graph**, 6–8 people. At least one person should want an area
where they have thin evidence and someone else has strong evidence — that's the pairing.

✅ **Check:** every key in `profiles.json` also appears in `graph.json`. Typos here silently
break the develops recommendation.

---

## Phase 4 · Agent runs — 30 min · THE CORE

```bash
python3 agent.py
```

✅ **Check 1 — data endpoints:**
```bash
curl -s localhost:8000/api/graph | python3 -m json.tool | head -30
curl -s localhost:8000/api/issues | python3 -c "import json,sys;[print(i['number'],i['title'][:60]) for i in json.load(sys.stdin)[:5]]"
```

✅ **Check 2 — the agent loop, with a real issue:**
```bash
curl -N -X POST localhost:8000/api/assign \
  -H 'Content-Type: application/json' \
  -d '{"issue":"<paste a real issue title and body>"}'
```

**You must see multiple `type: step` events before `type: done`.** If you get one step and
then done, tool use isn't looping — that's the difference between an agent and a prompt, and
it's the thing a judge will probe.

**Failure modes, in the order you'll hit them:**
- One step then done → tool_result blocks malformed; check `tool_use_id` matches
- `KeyError` in a tool → area names in `graph.json` don't match what the model is passing; loosen the substring match
- Empty recommendations → model returned prose not JSON; tighten the closing instruction
- Hangs → `max_tokens` too low, response truncated mid-JSON

Ask Claude Code to add a `--test` flag that runs one issue end to end and prints the trace,
so you can re-verify in one command after every change.

---

## Phase 5 · Frontend wired — 40 min

Give Claude Design `DESIGN.md` + `Ledger.jsx`. Give Claude Code the wiring:

- `GET /api/graph` on mount → register
- `GET /api/issues` → real issue picker
- `POST /api/assign` → `EventSource`-style SSE read, each `step` appended live

✅ **Check:** open the browser, pick a real issue, watch trace lines appear **one at a time**.
If they all appear at once, SSE is buffering — that's the `X-Accel-Buffering` header and
making sure you're not awaiting the whole response before rendering.

✅ **Check:** the register shows real GitHub logins, and at least one contributor renders
faded (inactive) and one shows a dashed intent cell.

---

## Phase 6 · The two closers — 20 min

1. **Bus factor → SKILL.md.** Agent hits critical, calls `generate_skills_file`, download appears.
   ✅ Open the file. If it's generic best practices instead of things reviewers actually said,
   the review notes aren't reaching the prompt.
2. **Real-issue picker** so a judge can choose one themselves. This is worth more than any
   feature you'd build with the same 20 minutes.

---

## 🛑 Hard stop at T-45

Stop building. No exceptions, no "just one more thing."

- [ ] Full run-through, start to finish, out loud — **three times**
- [ ] Laptop on venue wifi, verify it still works (or run fully local)
- [ ] Screenshot the best screen in case live fails
- [ ] `graph.json` committed so a crash doesn't cost you the data
- [ ] Have `curl` fallback ready to show the agent working if the UI dies

---

## Cut order if behind

Cut from the bottom. Never upward into the trace panel.

1. SKILL.md generation
2. Learning trajectory tool
3. Real-issue picker → hardcode one issue
4. Live SSE → run the agent once, replay the saved trace with timing

Even at cut level 4 you have a real demo: real repo, real contributors, real reasoning.
The trace panel and the two recommendations survive everything.

---

## What you're protecting

If everything else burns, these three things are the product:

1. **Real data** — a judge can open the repo and check you
2. **The trace** — proof it's an agent, not a prompt
3. **Two recommendations** — ships fast vs. develops, PM picks

Nothing else is worth a minute past T-45.
