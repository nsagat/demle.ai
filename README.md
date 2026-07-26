# Handoff: Demle — Capability Register

## Overview
Demle is a demo frontend for an agent that assigns GitHub issues by matching them to engineers' proven skills, stated growth goals, and current load — "match skills, don't just dump." One screen, three zones: an open issue with a live agent trace, a capability register (people × skill areas), and a post-run assignment decision (two candidate cards + a bus-factor risk banner).

## About the Design Files
The bundled `Demle.dc.html` is a **design reference created in HTML** — a prototype showing intended look and behavior, not production code to copy directly. The task is to **recreate this design in the target codebase's existing environment** (React, Vue, etc.) using its established patterns and libraries — or, if no environment exists yet, pick the most appropriate framework and implement it there. The file's template/logic split is prototype scaffolding; only the rendered UI, data shapes, and behavior described below are the spec.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and interactions are final. Recreate pixel-perfectly.

## Design Tokens
Colors:
- Canvas `#F4F6F2` (paper) · Panel `#FFFFFF`
- Primary/evidence accent `#1F3A2E` (forest) — also the trace terminal background
- Intent accent `#567F63` (sage) · Risk/flag `#A85438` (rust)
- Text `#2C3E33` · Muted `#6E7B6F` · Thin/disabled `#8A948B`
- Rule `#B7C2B4` · Hairline `#DCE3DA` · Skeleton bar `#E6EBE3`
- On dark trace panel: text `#F4F6F2`/`#E9E5DC`, intent `#7FA88F`, risk `#D9917A`, dims via rgba(244,246,242, .4–.75)
- Tint fills: lit column `rgba(31,58,46,0.05)`, banding `rgba(31,58,46,0.03)`, selected-card bg = accent + 8% alpha (`#1F3A2E14`/`#567F6314`), risk banner bg `rgba(168,84,56,0.07)`
Typography (Google Fonts):
- Lora 500–700: brand wordmark (22px/600), issue title (15px/600), candidate names (17px/600) — always `#1F3A2E`
- Inter 400–600: body UI, base 12.5px; issue summary 12px; card body 12.5px, line-height 1.55
- IBM Plex Mono 400–500: all labels/metadata/trace/buttons. Section labels 9.5px, letter-spacing 0.14em, uppercase; column headers 9–9.5px; trace 11–11.5px; stat numbers 13.5px; buttons 11px, letter-spacing 0.05em
Other:
- **No border radius anywhere. No shadows** (except focus/selection rings via box-shadow `0 0 0 2px rgba(accent,0.35–0.4)`)
- Spacing: page 28px top / 32px sides, max-width 1160px centered; sections stack at 26px; cards pad 16px; small gaps 4–14px
- Motion: entry `led-in` 260–400ms cubic-bezier(.2,.8,.2,1) (fade + 3px rise); `led-fade` 220–240ms; color/bg transitions 200–320ms; blinking cursor via steps(1) 1s. Respect `prefers-reduced-motion`
- Focus: 2px solid `#1F3A2E` outline, offset 2px. Links: `#1F3A2E` with `#B7C2B4` underline border

## Screens / Views — one screen, three zones

### 1. Header + Open Issue
- Header row: "Demle" wordmark + mono tagline "match skills, don't just dump" (10.5px `#8A948B`); right-aligned repo stats line (10.5px `#6E7B6F`). Below: 2px forest rule, 3px gap, 1px `#DCE3DA` hairline (double-rule ledger motif)
- Issue block: mono label "OPEN ISSUE"; issue number `#2841` (mono, forest) + Lora title; 12px summary paragraph, max-width 560px
- Right-aligned run button: solid forest, ink-on-forest text ("ISSUE OPENED →"); while running: transparent bg, `#8A948B` text, rule border, disabled ("RUNNING…"); after: "RUN AGAIN"
- **Agent trace terminal**: dark forest panel (`#1F3A2E`), 168px tall, scrollable, 12px/14px padding. Idle: "waiting for issue events…" at 55% paper. Lines appear one-by-one (led-in), auto-scroll to bottom: `▸ tool_name (arg) → result` — tool in `#E9E5DC` (intent tools `#7FA88F`), arg 60% `#E9E5DC`, result `#F4F6F2` (intent `#7FA88F`, risk `#D9917A`). While running, last line "▸ working_" with blinking underscore. Status text right of "AGENT TRACE" label: "ingesting repo history…" → "idle" → "running…" → "8 steps · 6.0s"

### 2. Capability Register (people × areas matrix)
- Labels: "CAPABILITY REGISTER" + right-aligned "columns discovered from repo history · rows are people"
- 9 columns: PYTHON CLIENT, C++ CLIENT, GRPC, JAVA BINDINGS, BUILD/CMAKE, PERF ANALYZER, CI, DOCS, WINDOWS BUILD. Headers vertical (writing-mode: vertical-rl, rotated 180°), 92px tall, bottom-aligned, mono 9.5px `#6E7B6F`; when an area is referenced by the trace it "lights": text → forest, column bg → 5% forest tint (240ms transition). Odd columns get 3% banding tint
- Left rail 176px: "CONTRIBUTOR / LOAD" headers; 7 rows, 31px tall, `#DCE3DA` bottom hairlines, `#B7C2B4` heavier rule under header; grid has right + left column borders `#DCE3DA`
- Rows load sequentially on page load (~140ms apart) from skeleton bars (110×7px `#E6EBE3`) to name + load fraction ("2/4", mono 9px `#8A948B`). Inactive contributor (Kwame, 14mo) shows "14mo" in rust and thin `#8A948B` name
- Cells: solid forest bars 32×13px = **evidence**, opacity encodes volume: `0.16 + (prs + 0.6·reviews)/24`, cap 0.95; inactive owner's bars at 0.22. Dashed 1px `#567F63` hollow bars = **intent** (stated want, no evidence)
- After run completes: chosen candidates' names bold forest; their relevant cells ring `0 0 0 2px` rgba-accent; risky area (java bindings × Kwame) rings rust
- Legend row below: solid swatch "evidence · derived from merged PRs + reviews", dashed swatch "intent · stated by the engineer, never inferred"; right: "windows build — no one has shipped this · hire, train, or scope it out"

### 3. Assignment (appears only after trace completes; led-in 400ms)
- Label row: "TWO WAYS TO ASSIGN THIS" + "the PM picks"; right side shows assignment receipt after choosing ("#2841 → Ana Duarte")
- Two equal cards (flex 1, min 320px, wrap; white bg, `#B7C2B4` border, 16px pad, flex column so ASSIGN buttons bottom-align):
  - **SHIPS FAST** (forest): eyebrow, name "Ana Duarte" + "evidence: strong", rationale paragraph, stat row (5 PRs · 3 reviews · 2/4 load — number 13.5px forest, unit 9.5px `#8A948B`), collapsible "▸ 3 artifacts" list (PR titles, mono 10.5px, left rule), full-width ASSIGN button (solid forest → on select: card border + 8% bg tint, button transparent "ASSIGNED" disabled; other card's button reads "CHOOSE OTHER")
  - **DEVELOPS** (sage): same structure; "Riya Shah" + "evidence: thin", STATED quote row ("Ship a real feature, not just tooling." · 1:1 · 2026-07-02), stats (0 python client PRs · 7 PRs elsewhere · 1/4 load), PAIR WITH box (`#B7C2B4` border + 2px sage left rule: Tomas Lindqvist, 12 PRs on C++ async semantics), "▸ 1 artifact", sage ASSIGN button
- **Risk banner**: rust border (3px left), 7% rust bg: "**Java bindings have no active owner.** Kwame Boateng last contributed 14 months ago…" + outlined rust button "↓ SKILL.md" that downloads a generated markdown skills file (content embedded in the prototype's SKILL_MD constant)

## Interactions & Behavior
1. Page load → register rows fill sequentially (skeleton → fade-in), status "ingesting repo history…" → "idle"
2. "ISSUE OPENED →" → trace resets & streams 8 tool calls (per-step delays 560–1150ms ÷ speed; total ~6s), auto-scrolling; referenced columns light up as steps land; button disabled while running
3. Trace completes → assignment section animates in; chosen candidates highlighted in register with rings
4. ASSIGN on either card → that card selected (border/tint/"ASSIGNED"), other button becomes "CHOOSE OTHER" (still clickable to switch); receipt line updates
5. Artifact toggles expand/collapse PR lists (▸/▾)
6. "↓ SKILL.md" → downloads `SKILL-java-bindings.md`
7. "RUN AGAIN" replays the trace (resets choice/toggles/assignment section)
8. Hover: cursor pointer on all enabled buttons; disabled use default cursor

## State Management
- `loaded` (0–7): register row reveal counter (timers on mount)
- `steps` (0–8): trace progress; drives lines, lit columns, risk rings
- `running`, `done`: run lifecycle → button label/style, status text, assignment visibility
- `chosen` (null | 'ship' | 'grow'): assignment selection
- `shipOpen`/`growOpen`: artifact accordions
- Derived per render: lit-area set from executed trace steps, risk-area set, cell opacity from evidence volume, selected-candidate highlighting
- All data (PEOPLE, TRACE, AREAS, SKILL_MD) is static demo fixture data embedded in the prototype — a real implementation would fetch register + stream trace events
- Config knobs in prototype: `banding` (bool), `traceSpeed` (0.5–2.5×), `autorun` (bool)

## Assets
None. No images or icons — glyphs are text characters (▸ ▾ → ↓ _). Fonts from Google Fonts (Lora, Inter, IBM Plex Mono).

## Files
- `Demle.dc.html` — the full prototype: template markup (inline styles) + `Component` logic class containing all fixture data, timings, and the SKILL.md content
