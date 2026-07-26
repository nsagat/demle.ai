# demle

**Match skills, don't just dump.** demle is an agent that reads a repository's
entire history of work — every merged PR, every review thread — and figures out
who should take the next issue, backed by evidence you can click through to.

### ▸ Live demo: **https://demle-ai.vercel.app**

---

## The problem

Task assignment on engineering teams runs on gut feel and availability: *who's
free? who's loud in standup?* The signal that actually matters — who has
demonstrably built this before, who's quietly trying to grow into it — is
invisible, buried across years of pull requests and review conversation nobody
has time to read.

So work gets dumped on whoever's visible. Experts get missed. People never get
the stretch assignment they asked for. And when the one person who understood a
subsystem leaves, their knowledge leaves with them.

## What demle does

It reads the repo's merged PRs and reviews, builds a **capability graph** of who
has proven what, and when a new issue lands it recommends who should take it —
producing **two options**, drawn from two kinds of signal it never confuses:

- **Evidence** — what someone has *demonstrably shipped*. Derived from PRs and reviews.
- **Intent** — where someone has *said* they want to grow. Self-reported, never inferred.

Which gives the manager a real choice:

- **Ships fast** — strongest evidence, active, has capacity.
- **Develops** — stated interest, thinner evidence, paired with a mentor who has it.

And it catches the thing everyone finds out too late — **bus-factor risk**. When
an area's only owners have gone inactive, demle reconstructs what they knew from
the actual review threads into a downloadable `SKILL.md`: the things reviewers
really said, not generic best practice.

No match scores. No rankings. No assignments made for you. Just counts and
artifact titles you can verify — **the human still decides.**

## Why it's different

- **It's a real agent, not a prompt.** A live tool-use loop — search evidence,
  check workload, check bus factor, reconstruct knowledge — reasoning over the
  graph and streaming each step to the screen as it goes.
- **Evidence and intent never mix.** Intent is only ever what a person stated
  themselves. demle will never guess your ambitions from your commit history.
- **Cross-repo recall.** Someone thin in this repo can surface on the strength
  of their work in another.
- **Knowledge doesn't leave when people do.** Bus-factor gaps become a skills
  file rebuilt from real reviewer conversation.

## How it works

```
GitHub history  →  capability graph (built by Claude)  →  live agent  →  the UI
   ingest.py            extract.py                         agent.py       web/
```

The agent (FastAPI) runs a genuine tool-use loop over the cached graph and
streams its reasoning over Server-Sent Events; the frontend (React + Vite)
renders the capability register, the live trace, and the two recommendation
cards in real time.

**Built with** Claude (Anthropic API) · FastAPI · React + Vite · GitHub GraphQL

## Run it locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 agent.py                  # backend on :8000
cd web && npm install && npm run dev   # frontend on :5173
```
