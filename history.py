#!/usr/bin/env python3
"""
demle — history.

Append-only JSONL. No database: this is a log, and logs are files.

    data/history.jsonl

Each line is one delegation decision and, later, its outcome. The agent reads
this to see its own track record, avoid stacking stretch work on one person,
and check whether stated growth goals are actually being met.

Import into agent.py:
    from history import record_decision, record_outcome, get_assignment_history
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path("data/history.jsonl")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def _append(rec):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


# ── writes ───────────────────────────────────────────────────────

def record_decision(issue_number, issue_title, areas, recommendations,
                    chosen, chosen_kind, reasoning, trace):
    """Called when the PM approves. Snapshots the evidence AS IT STOOD —
    that snapshot is the audit trail, and it must not be recomputed later."""
    return _append({
        "type": "decision",
        "at": _now(),
        "issue": issue_number,
        "issue_title": issue_title,
        "areas": areas,
        "recommended": [{"kind": r["kind"], "person": r["person"],
                         "confidence": r["confidence"]} for r in recommendations],
        "chosen": chosen,
        "chosen_kind": chosen_kind,        # ships_fast | develops
        "reasoning": reasoning,
        "trace": trace,                    # the tool calls that led here
    })


def record_outcome(issue_number, merged, days_to_merge=None,
                   change_requests=None, reassigned_to=None):
    """Called when the issue closes. In production this comes off a webhook."""
    return _append({
        "type": "outcome",
        "at": _now(),
        "issue": issue_number,
        "merged": merged,
        "days_to_merge": days_to_merge,
        "change_requests": change_requests,
        "reassigned_to": reassigned_to,
    })


# ── the tool ─────────────────────────────────────────────────────

def get_assignment_history(login: str = "", area: str = ""):
    """What demle has decided before, and how those decisions turned out.

    Read this before recommending. Two things matter most:
      - active stretch work: do not stack a second growth assignment on
        someone still working through the first
      - track record: whether past recommendations in this area merged
    """
    rows = _read()
    decisions = [r for r in rows if r["type"] == "decision"]
    outcomes = {r["issue"]: r for r in rows if r["type"] == "outcome"}

    if login:
        decisions = [d for d in decisions if d["chosen"] == login]
    if area:
        decisions = [d for d in decisions
                     if any(area.lower() in a.lower() for a in d.get("areas", []))]

    def days_ago(iso):
        return round((datetime.now(timezone.utc)
                      - datetime.fromisoformat(iso)).days)

    items, open_stretch = [], []
    shipped = stalled = 0

    for d in sorted(decisions, key=lambda x: x["at"], reverse=True)[:12]:
        out = outcomes.get(d["issue"])
        age = days_ago(d["at"])
        entry = {
            "issue": d["issue"], "title": d["issue_title"][:70],
            "person": d["chosen"], "kind": d["chosen_kind"],
            "days_ago": age,
            "areas": d.get("areas", []),
            "status": "open" if not out else ("merged" if out["merged"] else "closed unmerged"),
        }
        if out:
            entry["days_to_merge"] = out.get("days_to_merge")
            entry["change_requests"] = out.get("change_requests")
            if out.get("reassigned_to"):
                entry["reassigned_to"] = out["reassigned_to"]
            if out["merged"]:
                shipped += 1
            else:
                stalled += 1
        elif d["chosen_kind"] == "develops" and age < 21:
            open_stretch.append({"person": d["chosen"], "issue": d["issue"],
                                 "days_ago": age})
        items.append(entry)

    # is a stated growth goal actually being served?
    growth = {}
    for d in decisions:
        if d["chosen_kind"] == "develops":
            g = growth.setdefault(d["chosen"], {"assignments": 0, "merged": 0, "areas": set()})
            g["assignments"] += 1
            g["areas"].update(d.get("areas", []))
            o = outcomes.get(d["issue"])
            if o and o["merged"]:
                g["merged"] += 1
    growth = {k: {**v, "areas": sorted(v["areas"])} for k, v in growth.items()}

    return {
        "query": {"login": login or "all", "area": area or "all"},
        "total_decisions": len(decisions),
        "shipped": shipped,
        "stalled": stalled,
        "recent": items,
        "open_stretch_assignments": open_stretch,   # ← check before recommending develops
        "growth_progress": growth,
    }


# ── schema + system prompt additions for agent.py ─────────────────

TOOL_SCHEMA = {
    "name": "get_assignment_history",
    "description": (
        "What demle has recommended before and how it turned out. "
        "ALWAYS call this before finalising recommendations. Two rules depend on it: "
        "(1) do not give someone a 'develops' assignment if they have an open stretch "
        "assignment from the last three weeks; "
        "(2) if past recommendations in this area stalled or were reassigned, weight "
        "evidence more heavily this time. "
        "Also shows whether stated growth goals are being served — cite that when relevant."
    ),
    "input_schema": {"type": "object", "properties": {
        "login": {"type": "string", "description": "filter to one contributor, optional"},
        "area": {"type": "string", "description": "filter to one capability, optional"},
    }},
}

SYSTEM_ADDITION = """
You have memory of your own past decisions via get_assignment_history. Call it
before you finalise. It changes your recommendation in three ways:

- Someone with an open 'develops' assignment from the last three weeks is not
  available for another one. Say so and pick someone else.
- If your past recommendations in this area stalled or got reassigned, lean on
  evidence rather than intent this time, and say that you are doing so.
- If a contributor's stated goal is being served — they have shipped work in the
  area they said they wanted — cite that. It is the strongest signal you have
  that a growth assignment will land.
"""
