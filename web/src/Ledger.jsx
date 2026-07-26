import { useEffect, useRef, useState } from 'react'
import { getRepos, getGraph, getIssues, streamAssign, downloadSkill } from './api.js'

const C = {
  ink: '#F4F6F2', panel: '#FFFFFF', rule: '#B7C2B4', hair: '#DCE3DA', entry: '#1F3A2E',
  intent: '#567F63', flag: '#A85438', thin: '#8A948B', text: '#2C3E33', muted: '#6E7B6F',
}
const MONO = "'IBM Plex Mono',monospace"
const NCOLS = 9
const NROWS = 12

// bots that show up in contributor lists but aren't people
const BOTS = new Set([
  'copilot-pull-request-reviewer', 'greptile-apps', 'github-advanced-security',
  'github-actions', 'dependabot',
])

const tokens = (s) =>
  (s || '').toLowerCase().split(/[^a-z0-9+]+/).filter((t) => t.length > 2)
const overlaps = (a, b) => {
  const bt = new Set(tokens(b))
  return tokens(a).some((t) => bt.has(t))
}
// the single area a free-text "want" most likely refers to (argmax shared tokens)
const bestAreaForWant = (want, areaNames) => {
  let best = null, score = 0
  for (const a of areaNames) {
    const s = new Set(tokens(a))
    const n = tokens(want).filter((t) => s.has(t)).length
    if (n > score || (n === score && n > 0 && best && a.length < best.length)) { best = a; score = n }
  }
  return score > 0 ? best : null
}

export default function Ledger() {
  const [graph, setGraph] = useState(null)
  const [repos, setRepos] = useState([])
  const [repoSlug, setRepoSlug] = useState(null)
  const [issues, setIssues] = useState([])
  const [issueNum, setIssueNum] = useState(null)
  const [loaded, setLoaded] = useState(0)
  const [trace, setTrace] = useState([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [chosen, setChosen] = useState(null)
  const [shipOpen, setShipOpen] = useState(false)
  const [growOpen, setGrowOpen] = useState(false)
  const traceEl = useRef(null)
  const startRef = useRef(0)

  // 1) discover ingested repos; fall back to the backend default if none listed
  useEffect(() => {
    let dead = false
    getRepos()
      .then((rs) => { if (dead) return; setRepos(rs); setRepoSlug(rs[0]?.slug ?? '') })
      .catch(() => !dead && setRepoSlug(''))
    return () => { dead = true }
  }, [])

  // 2) load the selected repo's capability graph + open issues
  useEffect(() => {
    if (repoSlug === null) return
    let dead = false
    setGraph(null); setLoaded(0); setTrace([]); setResult(null); setChosen(null)
    getGraph(repoSlug || undefined).then((g) => !dead && setGraph(g)).catch(() => {})
    getIssues(repoSlug || undefined).then((is) => {
      if (dead) return
      setIssues(is)
      setIssueNum(is.length ? is[0].number : null)
    }).catch(() => {})
    return () => { dead = true }
  }, [repoSlug])

  const areaNames = graph ? graph.areas.map((a) => a.area) : []
  const areaMap = graph ? Object.fromEntries(graph.areas.map((a) => [a.area, a])) : {}

  // rows: real people (bots filtered), strongest evidence first, capped
  const rows = graph
    ? [...graph.people]
        .filter((p) => !BOTS.has(p.id))
        .map((p) => {
          const intent = {}
          ;(p.wants || []).forEach((w) => {
            const a = bestAreaForWant(w, areaNames)
            if (a && !p.evidence[a]) intent[a] = w // stated interest, no evidence yet
          })
          return {
            ...p, intent,
            vol: Object.values(p.evidence).reduce((a, e) => a + e.prs + e.reviews, 0),
          }
        })
        .sort((a, b) => b.vol - a.vol)
        .slice(0, NROWS)
    : []

  const intentAreas = new Set(rows.flatMap((p) => Object.keys(p.intent)))

  // columns: areas the shown rows hold, boosted for risk + stated-intent, then
  // guaranteed to include ≥1 intent column and ≥1 critical/high column so the
  // demo beats are always visible in the grid.
  const cols = (() => {
    if (!graph) return []
    const held = {}
    rows.forEach((p) => Object.entries(p.evidence).forEach(([a, e]) => {
      held[a] = (held[a] || 0) + e.prs + e.reviews * 0.6
    }))
    const riskBoost = (r) => (r === 'critical' ? 8 : r === 'high' ? 5 : 0)
    const score = (a) => (held[a] || 0) + riskBoost(areaMap[a]?.risk) + (intentAreas.has(a) ? 6 : 0)
    const cand = new Set([...Object.keys(held), ...intentAreas])
    const picked = [...cand].sort((a, b) => score(b) - score(a)).slice(0, NCOLS)
    if (intentAreas.size && !picked.some((a) => intentAreas.has(a)))
      picked[picked.length - 1] = [...intentAreas].sort((a, b) => score(b) - score(a))[0]
    const risky = (a) => ['critical', 'high'].includes(areaMap[a]?.risk)
    if (!picked.some(risky)) {
      const r = [...cand].filter(risky).sort((a, b) => score(b) - score(a))[0]
      if (r) picked[picked.length - 1] = r
    }
    return picked.map((area) => ({ ...areaMap[area], area }))
  })()

  useEffect(() => {
    if (!graph) return
    const timers = []
    for (let i = 1; i <= Math.min(rows.length, NROWS); i++)
      timers.push(setTimeout(() => setLoaded(i), 320 + i * 140))
    return () => timers.forEach(clearTimeout)
  }, [graph])

  useEffect(() => {
    if (traceEl.current) traceEl.current.scrollTop = traceEl.current.scrollHeight
  }, [trace.length])

  const issue = issues.find((i) => i.number === issueNum)

  const run = async () => {
    if (running || !issue) return
    setTrace([]); setResult(null); setChosen(null); setShipOpen(false); setGrowOpen(false)
    setRunning(true)
    startRef.current = Date.now()
    try {
      await streamAssign(
        `#${issue.number} ${issue.title}\n\n${(issue.body || '').slice(0, 800)}`,
        repoSlug || undefined,
        (ev) => {
          if (ev.type === 'step') setTrace((t) => [...t, ev])
          else if (ev.type === 'done') {
            setElapsed(((Date.now() - startRef.current) / 1000).toFixed(1))
            setResult(ev)
          } else if (ev.type === 'error') {
            setTrace((t) => [...t, { tool: 'error', arg: '', result: ev.message, kind: 'risk' }])
          }
        },
      )
    } catch (e) {
      setTrace((t) => [...t, { tool: 'error', arg: '', result: String(e.message || e), kind: 'risk' }])
    }
    setRunning(false)
  }

  const lit = new Set()
  const riskAreas = new Set()
  for (const s of trace) {
    if (!['search_evidence', 'check_bus_factor', 'generate_skills_file', 'analyze_issue'].includes(s.tool)) continue
    for (const c of cols) {
      if (overlaps(s.arg, c.area) || overlaps(s.result, c.area)) {
        lit.add(c.area)
        if (s.kind === 'risk') riskAreas.add(c.area)
      }
    }
  }

  const recs = result?.recommendations || []
  const ship = recs.find((r) => r.kind === 'ships_fast')
  const grow = recs.find((r) => r.kind === 'develops')
  const picked = new Set(result ? recs.map((r) => r.person) : [])
  const risks = (result?.risks || []).filter((r) => r.level !== 'ok')
  const risk = risks[0]

  const growPerson = grow && graph?.people.find((p) => p.id === grow.person)

  const colViews = cols.map((c, i) => ({
    ...c,
    label: (c.area.length > 24 ? c.area.slice(0, 23) + '…' : c.area).toUpperCase(),
    color: lit.has(c.area) ? C.entry : C.muted,
    bg: lit.has(c.area) ? 'rgba(31,58,46,0.05)' : i % 2 === 1 ? 'rgba(31,58,46,0.03)' : 'transparent',
  }))

  const rowViews = rows.map((p, pi) => {
    const isLoaded = pi < loaded
    const gone = (p.monthsInactive ?? 99) > 6
    const sel = picked.has(p.id)
    return {
      id: p.id, loaded: isLoaded, name: p.name,
      nameColor: sel ? C.entry : gone ? C.thin : C.text,
      nameWeight: sel ? 600 : 400,
      cap: gone ? Math.round(p.monthsInactive) + 'mo' : p.load + ' open',
      capColor: gone ? C.flag : C.thin,
      cells: cols.map((c, ci) => {
        const e = p.evidence[c.area]
        const vol = e ? e.prs + e.reviews * 0.6 : 0
        const solid = isLoaded && !!e
        const hollow = isLoaded && !e && !!p.intent[c.area]
        let ring = 'none'
        if (solid && riskAreas.has(c.area) && gone) ring = '0 0 0 2px rgba(168,84,56,0.4)'
        else if (solid && sel && lit.has(c.area)) ring = '0 0 0 2px rgba(31,58,46,0.35)'
        return {
          bg: colViews[ci].bg, solid, hollow,
          op: gone ? 0.22 : Math.min(0.16 + vol / 24, 0.95),
          ring,
          ringG: hollow && sel && lit.has(c.area) ? '0 0 0 2px rgba(86,127,99,0.35)' : 'none',
        }
      }),
    }
  })

  const gap = cols.find((c) => c.risk === 'critical' || c.risk === 'high')

  const statusText = running ? 'running…'
    : result ? `${trace.length} steps · ${elapsed}s`
    : !graph ? 'ingesting repo history…'
    : loaded < rows.length ? 'ingesting repo history…' : 'idle'

  const label = (t) => ({ fontFamily: MONO, fontSize: '9.5px', letterSpacing: '0.14em', color: C.muted, ...(t || {}) })
  const mono = (s, extra) => ({ fontFamily: MONO, fontSize: s, ...(extra || {}) })

  const cardStyle = (col, key) => {
    const mine = chosen === key
    return {
      border: mine ? col : C.rule,
      bg: mine ? col + '14' : C.panel,
      btnLabel: mine ? 'ASSIGNED' : chosen ? 'CHOOSE OTHER' : 'ASSIGN',
      btnBg: mine || chosen ? 'transparent' : col,
      btnColor: mine || chosen ? col : C.ink,
      btnCursor: mine ? 'default' : 'pointer',
      btnDisabled: mine,
    }
  }
  const shipCard = cardStyle(C.entry, 'ship')
  const growCard = cardStyle(C.intent, 'grow')

  // real SKILL.md: fetches /api/skill?area= which renders the actual review
  // conversation on this area — not a canned string.
  const onDownloadSkill = () => { if (risk) downloadSkill(risk.area, repoSlug || undefined) }

  const traceColor = (kind) => ({
    tool: kind === 'intent' ? '#7FA88F' : '#E9E5DC',
    res: kind === 'risk' ? '#D9917A' : kind === 'intent' ? '#7FA88F' : '#F4F6F2',
  })

  const stat = (n, unit) => (
    <div key={unit + n} style={{ display: 'flex', gap: 4, alignItems: 'baseline' }}>
      <span style={mono('13.5px', { color: C.entry })}>{n}</span>
      <span style={mono('9.5px', { color: C.thin })}>{unit}</span>
    </div>
  )

  const assignedNote = chosen === 'ship' && ship ? `#${issueNum} → ${ship.person}`
    : chosen === 'grow' && grow ? `#${issueNum} → ${grow.person}${grow.mentor?.name ? ` · pair: ${grow.mentor.name}` : ''}`
    : ''

  return (
    <div style={{ minHeight: '100vh', background: '#F4F6F2', color: C.text, fontFamily: "'Inter',system-ui,sans-serif", fontSize: '12.5px' }}>
      <div style={{ maxWidth: 1160, margin: '0 auto', padding: '28px 32px 64px 32px' }}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
            <span style={{ fontFamily: "'Lora',serif", fontWeight: 600, fontSize: 22, color: C.entry }}>Demle</span>
            <span style={mono('10.5px', { color: C.thin })}>match skills, don't just dump</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            {repos.length > 1 && (
              <select
                value={repoSlug ?? ''}
                disabled={running}
                onChange={(e) => setRepoSlug(e.target.value)}
                style={mono('10px', { color: C.entry, background: C.panel, border: `1px solid ${C.hair}`, padding: '3px 5px', cursor: running ? 'default' : 'pointer' })}
              >
                {repos.map((r) => (
                  <option key={r.slug} value={r.slug}>{r.repo}</option>
                ))}
              </select>
            )}
            <span style={mono('10.5px', { color: C.muted })}>
              {graph ? `${graph.repo} · ${graph.stats.prs} merged PRs · ${graph.stats.reviews} reviews · ${graph.stats.contributors} contributors` : 'loading…'}
            </span>
          </div>
        </div>
        <div style={{ height: 2, background: C.entry }} />
        <div style={{ height: 1, background: C.hair, marginTop: 3 }} />

        <div style={{ marginTop: 22 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
            <span style={label()}>OPEN ISSUE</span>
            <select
              value={issueNum ?? ''}
              disabled={running}
              onChange={(e) => { setIssueNum(Number(e.target.value)); setTrace([]); setResult(null); setChosen(null) }}
              style={mono('10.5px', { color: C.text, background: C.panel, border: `1px solid ${C.hair}`, padding: '4px 6px', maxWidth: 420, cursor: running ? 'default' : 'pointer' })}
            >
              {issues.map((i) => (
                <option key={i.number} value={i.number}>#{i.number} {i.title.slice(0, 56)}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 18, marginBottom: 14 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={mono('11px', { color: C.entry })}>#{issue?.number}</span>
                <span style={{ fontFamily: "'Lora',serif", fontSize: 15, fontWeight: 600, color: C.entry }}>{issue?.title}</span>
              </div>
              <p style={{ fontSize: 12, color: C.muted, margin: '5px 0 0 0', maxWidth: 560, lineHeight: 1.55, textWrap: 'pretty' }}>
                {(issue?.body || '').slice(0, 200)}{(issue?.body || '').length > 200 ? '…' : ''}
              </p>
            </div>
            <button
              onClick={run}
              disabled={running}
              style={mono('11px', {
                letterSpacing: '0.05em', padding: '9px 18px', whiteSpace: 'nowrap', flexShrink: 0,
                cursor: running ? 'default' : 'pointer',
                background: running ? 'transparent' : C.entry,
                color: running ? C.thin : C.ink,
                border: `1px solid ${running ? C.rule : C.entry}`, transition: 'all 200ms',
              })}
            >
              {running ? 'RUNNING…' : result ? 'RUN AGAIN' : 'ISSUE OPENED →'}
            </button>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <span style={label()}>AGENT TRACE</span>
            <span style={mono('9.5px', { color: running ? C.entry : C.thin })}>{statusText}</span>
          </div>
          <div data-trace="1" ref={traceEl} style={{ background: C.entry, border: `1px solid ${C.entry}`, padding: '12px 14px', height: 168, overflowY: 'auto' }}>
            {trace.length === 0 && !running && (
              <span style={mono('11.5px', { color: 'rgba(244,246,242,0.55)' })}>waiting for issue events…</span>
            )}
            {trace.map((ln, i) => {
              const col = traceColor(ln.kind)
              return (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 5, animation: 'led-in 260ms cubic-bezier(.2,.8,.2,1) both' }}>
                  <span style={mono('11px', { color: 'rgba(244,246,242,0.4)' })}>▸</span>
                  <span style={mono('11.5px', { color: col.tool })}>{ln.tool}</span>
                  <span style={mono('11.5px', { color: 'rgba(233,229,220,0.6)' })}>({ln.arg})</span>
                  <span style={mono('11.5px', { color: 'rgba(244,246,242,0.4)' })}>→</span>
                  <span style={mono('11.5px', { color: col.res })}>{ln.result}</span>
                </div>
              )
            })}
            {running && (
              <span style={mono('11.5px', { color: 'rgba(244,246,242,0.75)' })}>
                ▸ working<span style={{ animation: 'led-blink 1s steps(1) infinite' }}>_</span>
              </span>
            )}
          </div>
        </div>

        <div style={{ marginTop: 26 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 2 }}>
            <span style={label()}>CAPABILITY REGISTER</span>
            <span style={mono('9.5px', { color: C.thin })}>
              {graph ? `showing ${cols.length} of ${graph.areas.length} areas · ${rows.length} of ${graph.people.length} people` : 'columns discovered from repo history'}
            </span>
          </div>
          <div style={{ borderRight: `1px solid ${C.hair}` }}>
            <div style={{ display: 'flex', alignItems: 'stretch' }}>
              <div style={{ width: 176, flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', padding: '0 10px 7px 0' }}>
                <span style={mono('9px', { letterSpacing: '0.1em', color: C.thin })}>CONTRIBUTOR</span>
                <span style={mono('9px', { letterSpacing: '0.1em', color: C.thin })}>LOAD</span>
              </div>
              {colViews.map((c) => (
                <div key={c.area} title={c.area} style={{ flex: '1 1 0', minWidth: 54, height: 92, display: 'flex', justifyContent: 'center', alignItems: 'flex-end', paddingBottom: 7, borderLeft: `1px solid ${C.hair}`, background: c.bg, transition: 'background 240ms' }}>
                  <span style={mono('9.5px', { letterSpacing: '0.06em', color: c.color, writingMode: 'vertical-rl', transform: 'rotate(180deg)', whiteSpace: 'nowrap', transition: 'color 240ms' })}>{c.label}</span>
                </div>
              ))}
            </div>
            <div style={{ height: 1, background: C.rule }} />
            {rowViews.map((row) => (
              <div key={row.id} style={{ display: 'flex', alignItems: 'stretch', height: 31, borderBottom: `1px solid ${C.hair}` }}>
                <div style={{ width: 176, flexShrink: 0, paddingRight: 10 }}>
                  {row.loaded ? (
                    <div style={{ height: 30, display: 'flex', justifyContent: 'space-between', alignItems: 'center', animation: 'led-fade 220ms both' }}>
                      <span style={{ fontSize: '12.5px', color: row.nameColor, fontWeight: row.nameWeight, transition: 'color 240ms', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</span>
                      <span style={mono('9px', { color: row.capColor })}>{row.cap}</span>
                    </div>
                  ) : (
                    <div style={{ height: 30, display: 'flex', alignItems: 'center' }}>
                      <span style={{ display: 'block', width: 110, height: 7, background: '#E6EBE3' }} />
                    </div>
                  )}
                </div>
                {row.cells.map((cell, ci) => (
                  <div key={ci} style={{ flex: '1 1 0', minWidth: 54, borderLeft: `1px solid ${C.hair}`, display: 'flex', alignItems: 'center', justifyContent: 'center', background: cell.bg, transition: 'background 240ms' }}>
                    {cell.solid && (
                      <span style={{ display: 'block', width: 32, height: 13, background: C.entry, opacity: cell.op, boxShadow: cell.ring, transition: 'box-shadow 320ms cubic-bezier(.2,.8,.2,1)', animation: 'led-fade 240ms both' }} />
                    )}
                    {cell.hollow && (
                      <span style={{ display: 'block', width: 32, height: 13, border: `1px dashed ${C.intent}`, boxShadow: cell.ringG, transition: 'box-shadow 320ms cubic-bezier(.2,.8,.2,1)', animation: 'led-fade 240ms both' }} />
                    )}
                  </div>
                ))}
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingTop: 11 }}>
              <div style={{ display: 'flex', gap: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ display: 'block', width: 20, height: 10, background: C.entry }} />
                  <span style={mono('9.5px', { color: C.thin })}>evidence · derived from merged PRs + reviews</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ display: 'block', width: 20, height: 10, border: `1px dashed ${C.intent}` }} />
                  <span style={mono('9.5px', { color: C.thin })}>intent · stated by the engineer, never inferred</span>
                </div>
              </div>
              {gap && (
                <span style={mono('9.5px', { color: C.thin })}>
                  {gap.area.toLowerCase()} — {gap.risk} risk · hire, train, or scope it out
                </span>
              )}
            </div>
          </div>
        </div>

        {result && (ship || grow) && (
          <div style={{ marginTop: 26, animation: 'led-in 400ms cubic-bezier(.2,.8,.2,1) both' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                <span style={label()}>TWO WAYS TO ASSIGN THIS</span>
                <span style={mono('9.5px', { color: C.thin })}>the PM picks</span>
              </div>
              <span style={mono('9.5px', { color: C.entry })}>{assignedNote}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>

              {ship && (
                <div style={{ flex: '1 1 0', minWidth: 320, display: 'flex', flexDirection: 'column', border: `1px solid ${shipCard.border}`, background: shipCard.bg, padding: 16, transition: 'all 300ms cubic-bezier(.2,.8,.2,1)' }}>
                  <span style={mono('9px', { letterSpacing: '0.14em', color: C.entry })}>SHIPS FAST</span>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 6 }}>
                    <span style={{ fontFamily: "'Lora',serif", fontSize: 17, fontWeight: 600, color: C.entry }}>{ship.person}</span>
                    <span style={mono('9.5px', { color: C.muted })}>evidence: {ship.confidence}</span>
                  </div>
                  <p style={{ fontSize: '12.5px', color: C.text, margin: '9px 0 0 0', lineHeight: 1.55, textWrap: 'pretty' }}>{ship.reasoning}</p>
                  <div style={{ display: 'flex', gap: 16, marginTop: 11 }}>
                    {(ship.stats || []).slice(0, 3).map(([n, u]) => stat(n, u))}
                  </div>
                  {(ship.artifacts || []).length > 0 && (
                    <>
                      <button onClick={() => setShipOpen((s) => !s)} style={{ background: 'none', border: 'none', padding: '10px 0 0 0', cursor: 'pointer', ...mono('10.5px', { color: C.muted }) }}>
                        {(shipOpen ? '▾ ' : '▸ ') + (ship.artifacts || []).length + ((ship.artifacts || []).length === 1 ? ' artifact' : ' artifacts')}
                      </button>
                      {shipOpen && (
                        <div style={{ marginTop: 6, borderLeft: `1px solid ${C.rule}`, paddingLeft: 11 }}>
                          {(ship.artifacts || []).map((a) => (
                            <span key={a} style={{ display: 'block', ...mono('10.5px', { color: C.muted, padding: '3px 0', lineHeight: 1.4 }) }}>{a}</span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                  <div style={{ height: 13, marginTop: 'auto' }} />
                  <button
                    onClick={() => setChosen('ship')}
                    disabled={shipCard.btnDisabled}
                    style={mono('11px', { letterSpacing: '0.05em', padding: '9px 0', width: '100%', cursor: shipCard.btnCursor, background: shipCard.btnBg, color: shipCard.btnColor, border: `1px solid ${C.entry}`, transition: 'all 300ms' })}
                  >
                    {shipCard.btnLabel}
                  </button>
                </div>
              )}

              {grow && (
                <div style={{ flex: '1 1 0', minWidth: 320, display: 'flex', flexDirection: 'column', border: `1px solid ${growCard.border}`, background: growCard.bg, padding: 16, transition: 'all 300ms cubic-bezier(.2,.8,.2,1)' }}>
                  <span style={mono('9px', { letterSpacing: '0.14em', color: C.intent })}>DEVELOPS</span>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 6 }}>
                    <span style={{ fontFamily: "'Lora',serif", fontSize: 17, fontWeight: 600, color: C.entry }}>{grow.person}</span>
                    <span style={mono('9.5px', { color: C.muted })}>evidence: {grow.confidence}</span>
                  </div>
                  <p style={{ fontSize: '12.5px', color: C.text, margin: '9px 0 0 0', lineHeight: 1.55, textWrap: 'pretty' }}>{grow.reasoning}</p>
                  {growPerson?.goal && (
                    <div style={{ marginTop: 9, display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                      <span style={mono('9px', { letterSpacing: '0.1em', color: C.intent })}>STATED</span>
                      <span style={{ fontSize: '11.5px', color: C.text }}>"{growPerson.goal}"</span>
                      <span style={mono('9.5px', { color: C.muted })}>{growPerson.goalSource}</span>
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 16, marginTop: 11 }}>
                    {(grow.stats || []).slice(0, 3).map(([n, u]) => stat(n, u))}
                  </div>
                  {grow.mentor?.name && (
                    <div style={{ marginTop: 11, padding: '10px 12px', border: `1px solid ${C.rule}`, borderLeft: `2px solid ${C.intent}` }}>
                      <span style={mono('9px', { letterSpacing: '0.1em', color: C.intent })}>PAIR WITH</span>
                      <div style={{ fontSize: '12.5px', marginTop: 4 }}>{grow.mentor.name}</div>
                      <span style={{ display: 'block', ...mono('10.5px', { color: C.muted, marginTop: 3, lineHeight: 1.45 }) }}>{grow.mentor.why}</span>
                    </div>
                  )}
                  {(grow.artifacts || []).length > 0 && (
                    <>
                      <button onClick={() => setGrowOpen((s) => !s)} style={{ background: 'none', border: 'none', padding: '10px 0 0 0', cursor: 'pointer', ...mono('10.5px', { color: C.muted }) }}>
                        {(growOpen ? '▾ ' : '▸ ') + (grow.artifacts || []).length + ((grow.artifacts || []).length === 1 ? ' artifact' : ' artifacts')}
                      </button>
                      {growOpen && (
                        <div style={{ marginTop: 6, borderLeft: `1px solid ${C.rule}`, paddingLeft: 11 }}>
                          {(grow.artifacts || []).map((a) => (
                            <span key={a} style={{ display: 'block', ...mono('10.5px', { color: C.muted, padding: '3px 0', lineHeight: 1.4 }) }}>{a}</span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                  <div style={{ height: 13, marginTop: 'auto' }} />
                  <button
                    onClick={() => setChosen('grow')}
                    disabled={growCard.btnDisabled}
                    style={mono('11px', { letterSpacing: '0.05em', padding: '9px 0', width: '100%', cursor: growCard.btnCursor, background: growCard.btnBg, color: growCard.btnColor, border: `1px solid ${C.intent}`, transition: 'all 300ms' })}
                  >
                    {growCard.btnLabel}
                  </button>
                </div>
              )}
            </div>

            {risk && (
              <div style={{ marginTop: 12, border: `1px solid ${C.flag}`, borderLeftWidth: 3, background: 'rgba(168,84,56,0.07)', padding: '12px 14px' }}>
                <div style={{ fontSize: '12.5px', lineHeight: 1.55, textWrap: 'pretty' }}>
                  <strong style={{ color: C.flag, fontWeight: 600 }}>{risk.area} — {risk.level} risk. </strong>
                  {risk.detail}
                </div>
                <button onClick={onDownloadSkill} style={mono('10.5px', { letterSpacing: '0.05em', padding: '7px 13px', marginTop: 10, cursor: 'pointer', background: 'transparent', color: C.flag, border: `1px solid ${C.flag}` })}>
                  ↓ SKILL.md
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
