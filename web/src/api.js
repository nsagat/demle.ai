// demle — thin client over the FastAPI agent.
// Dev: vite proxies /api -> localhost:8000 (see vite.config.js), so BASE is ''.
// Prod (e.g. Vercel): the static frontend and the Python agent are hosted
// separately, so point the frontend at the backend. Resolution order:
//   1. ?api=<url> query param (persisted to localStorage) — best for demos +
//      ephemeral tunnel URLs: open demle-ai.vercel.app/?api=https://xyz.trycloudflare.com once
//   2. localStorage (remembered from a previous ?api=)
//   3. VITE_API_BASE build-time env var
//   4. '' (same-origin — works in dev via the vite proxy)
function resolveBase() {
  try {
    const p = new URLSearchParams(window.location.search).get('api')
    if (p) { window.localStorage.setItem('demle_api', p); return p.replace(/\/+$/, '') }
    const saved = window.localStorage.getItem('demle_api')
    if (saved) return saved.replace(/\/+$/, '')
  } catch { /* no DOM (SSR/tests) */ }
  return (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')
}
const BASE = resolveBase()

const qs = (repo) => (repo ? `?repo=${encodeURIComponent(repo)}` : '')

export async function getRepos() {
  const r = await fetch(`${BASE}/api/repos`)
  if (!r.ok) throw new Error(`repos ${r.status}`)
  return r.json()
}

export async function getGraph(repo) {
  const r = await fetch(`${BASE}/api/graph${qs(repo)}`)
  if (!r.ok) throw new Error(`graph ${r.status}`)
  return r.json()
}

export async function getIssues(repo) {
  const r = await fetch(`${BASE}/api/issues${qs(repo)}`)
  if (!r.ok) throw new Error(`issues ${r.status}`)
  return r.json()
}

// POST /api/assign returns Server-Sent Events. EventSource is GET-only, so we
// read the body stream ourselves and parse `data: {...}` frames as they arrive.
// onEvent is called once per parsed event; resolves when the stream closes.
export async function streamAssign(issueText, repo, onEvent, signal) {
  const res = await fetch(`${BASE}/api/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ issue: issueText, repo }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`assign ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    let sep
    while ((sep = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload))
      } catch {
        // partial/garbled frame — skip, keep reading
      }
    }
  }
}

// Trigger a SKILL.md download for an area (GET /api/skill?area=&repo=).
export async function downloadSkill(area, repo) {
  const url = `${BASE}/api/skill?area=${encodeURIComponent(area)}${repo ? `&repo=${encodeURIComponent(repo)}` : ''}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`skill ${res.status}`)
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : 'SKILL.md'
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}
