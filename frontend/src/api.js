// Thin fetch wrapper around the HomeHoard API.
const TOKEN_KEY = 'easyinv_token'

// Resolve the API root relative to the page so the app works both standalone
// (served at "/") and behind a Home Assistant ingress path (e.g.
// "/api/hassio_ingress/<token>/"). We take the directory of the current page.
function apiBase() {
  let p = window.location.pathname
  if (!p.endsWith('/')) p = p.slice(0, p.lastIndexOf('/') + 1)
  return p + 'api/v1'
}

export function apiUrl(path) {
  return apiBase() + path
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(method, path, body, isForm = false) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = token
  let payload
  if (isForm) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(apiUrl(path), { method, headers, body: payload })
  if (res.status === 401) {
    setToken(null)
    if (!location.hash.includes('/login')) location.hash = '#/login'
  }
  const ct = res.headers.get('content-type') || ''
  const data = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) throw new Error((data && data.error) || res.statusText)
  return data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
  upload: (p, form) => request('POST', p, form, true),
}

// POST that consumes a newline-delimited-JSON (NDJSON) streaming response,
// invoking onEvent(obj) for each parsed line as it arrives. Used by the chat
// assistant's streaming mode. Uses fetch + a ReadableStream reader (not
// EventSource) so the Authorization header still goes out.
export async function streamPost(path, body, onEvent) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = token
  const res = await fetch(apiUrl(path), {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (res.status === 401) {
    setToken(null)
    if (!location.hash.includes('/login')) location.hash = '#/login'
  }
  if (!res.ok || !res.body) {
    let msg = res.statusText
    try { const j = await res.json(); msg = (j && j.error) || msg } catch (e) { /* non-JSON */ }
    throw new Error(msg)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const flush = (chunk, last) => {
    buf += chunk
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) onEvent(JSON.parse(line))
    }
    if (last && buf.trim()) onEvent(JSON.parse(buf.trim()))
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    flush(decoder.decode(value, { stream: true }), false)
  }
  flush(decoder.decode(), true)
}
