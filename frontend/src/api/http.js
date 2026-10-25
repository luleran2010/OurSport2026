// HTTP for the OurSport API v1 (backend/docs/05-api.md), the same against the real backend
// and the mock: cookies + X-CSRF-Token on unsafe requests, one refresh on 401, problem+json
// errors, and `Authorization: Pass <token>` for scorers who opened a pitch QR code.

// Base URL of the API. Empty = same origin (the Vite dev server proxies /api and /health).
export const API_BASE = import.meta.env.VITE_API_URL ?? ''
export const V1 = `${API_BASE}/api/v1`

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const PASS_KEY = 'oursport:scorer-pass'

function cookie(name) {
  const hit = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null
}

/** A session exists on this device (the CSRF cookie is readable; the session cookies are not). */
export const hasSession = () => Boolean(cookie('oursport_csrf'))

// ---- scorer pass (QR code: /score?pass=<token>) --------------------------------------------

export function scorerPass() {
  try {
    return localStorage.getItem(PASS_KEY)
  } catch {
    return null
  }
}

export function setScorerPass(token) {
  try {
    if (token) localStorage.setItem(PASS_KEY, token)
    else localStorage.removeItem(PASS_KEY)
  } catch {
    /* storage blocked: the pass works until the page is closed */
  }
}

// ---- errors -----------------------------------------------------------------------------

/** RFC 9457 problem details -> Error with `status`, `code` and `errors` (branch on `code`). */
async function problem(res) {
  const body = await res.json().catch(() => ({}))
  if (body && body.code) {
    const err = new Error(body.detail || body.title || `${res.status} ${res.statusText}`)
    Object.assign(err, { status: res.status, code: body.code, errors: body.errors ?? [], data: body })
    return err
  }
  // older mock-only routes (publisher): FastAPI's { detail }
  const d = body.detail
  const detail = Array.isArray(d) ? d[0]?.msg : typeof d === 'object' && d ? d.message : d
  const err = new Error(detail || `${res.status} ${res.statusText}`)
  err.status = res.status
  err.code = typeof d === 'object' && d && !Array.isArray(d) ? d.code : undefined
  err.data = typeof d === 'object' && d && !Array.isArray(d) ? d : undefined
  return err
}

// ---- requests -----------------------------------------------------------------------------

let refreshing = null

/**
 * Rotate the refresh cookie once for every request that got 401 at the same time. `seen` is the
 * CSRF cookie the failed request was sent with: every refresh sets a new one, so a change means
 * the session was renewed meanwhile (here or in another tab) and the request only needs a retry.
 * Tabs share the cookies but each refresh token works once (the backend ends a session whose old
 * token comes back), so the tabs take turns under a Web Lock instead of racing.
 */
function refresh(seen) {
  const renew = async () => {
    if (cookie('oursport_csrf') !== seen) return true
    try {
      const r = await fetch(`${V1}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': cookie('oursport_csrf') ?? '' },
      })
      return r.ok
    } catch {
      return false
    }
  }
  refreshing ??= (navigator.locks ? navigator.locks.request('oursport-session-refresh', renew) : renew())
    .finally(() => setTimeout(() => (refreshing = null), 0))
  return refreshing
}

async function send(url, { method = 'GET', body, headers = {}, signal, scorer = false } = {}) {
  const h = { ...headers }
  if (body !== undefined && !(body instanceof FormData) && !(body instanceof Blob) && !h['Content-Type']) {
    h['Content-Type'] = 'application/json'
  }
  if (UNSAFE.has(method)) h['X-CSRF-Token'] = cookie('oursport_csrf') ?? ''
  const pass = scorer && scorerPass()
  if (pass) h.Authorization = `Pass ${pass}`
  const payload = body === undefined || body instanceof FormData || body instanceof Blob || typeof body === 'string'
    ? body : JSON.stringify(body)
  return fetch(url, { method, body: payload, headers: h, signal, credentials: 'include' })
}

/** A v1 call (`path` without /api/v1). Objects in `body` are sent as JSON. 204 -> null. */
export async function v1(path, options = {}) {
  const seen = cookie('oursport_csrf')
  let res = await send(`${V1}${path}`, options)
  if (res.status === 401 && !path.startsWith('/auth/') && hasSession() && (await refresh(seen))) {
    res = await send(`${V1}${path}`, options)
  }
  if (res.status === 204) return null
  if (!res.ok) throw await problem(res)
  return res.json()
}

/** Every page of a cursor-paged v1 list (`{items, next_cursor}`), limit 100. */
export async function v1All(path) {
  const items = []
  let cursor = null
  const sep = path.includes('?') ? '&' : '?'
  do {
    const page = await v1(`${path}${sep}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
    items.push(...page.items)
    cursor = page.next_cursor
  } while (cursor)
  return items
}

/** Mock-only publisher routes not yet on v1. */
export async function legacy(path, options = {}) {
  const res = await send(`${API_BASE}${path}`, options)
  if (res.status === 204) return null
  if (!res.ok) throw await problem(res)
  return res.json()
}

/** Build a query string, dropping empty values and the "all" placeholder. */
export function qs(params) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '' && v !== 'all') p.set(k, v)
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}
