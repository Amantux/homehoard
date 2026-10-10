// Thin fetch wrapper around the HomeHoard API.
import { TOKEN as TOKEN_KEY } from './storageKeys'

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

// Every failed request throws this. `status` is 0 when the server was
// unreachable; `fields` maps form field -> message for 422 validation errors.
export class ApiError extends Error {
  constructor({ status, message, fields = {}, requestId = null }) {
    super(message)
    this.name = 'ApiError'
    this.status = status // lets views tell a 404 ("deleted or never existed") from other failures
    this.fields = fields
    this.requestId = requestId
  }
}

export const NETWORK_ERROR_MESSAGE = "Can't reach HomeHoard. Check the add-on is running."

// Message for a failure whose body isn't our JSON (proxy HTML page, plain text).
function curatedMessage(status, requestId) {
  if (status === 401) return 'Sign in again.'
  if (status === 403) return "You don't have permission to do that."
  if (status === 404) return 'Not found.'
  if (status === 413) return 'That upload is too large.'
  if (status === 429) return 'Too many requests — try again in a moment.'
  if (status >= 500) return `HomeHoard hit an error${requestId ? ` (request ${requestId})` : ''}. Try again.`
  return `Request failed (${status}).`
}

export function errorFromResponse(status, data) {
  if (data && typeof data === 'object' && data.error) {
    return new ApiError({ status, message: data.error, fields: data.fields || {}, requestId: data.requestId || null })
  }
  const requestId = (data && typeof data === 'object' && data.requestId) || null
  return new ApiError({ status, message: curatedMessage(status, requestId), requestId })
}

// Called after every successful local write (non-GET request, or a chat stream
// that ended normally) so views refresh at once instead of waiting for the
// live-sync poll. App.vue wires it to ui.dataChanged(); kept as a hook so this
// module stays free of pinia.
let writeHook = null
export function setWriteHook(fn) {
  writeHook = fn
}

// Called on any 401 (the token is already cleared). App.vue wires it to end the
// session in place — clear auth.user, stop the poller, show a sign-in banner —
// instead of navigating, so the open view and its unsaved inputs survive.
let unauthorizedHook = null
export function setUnauthorizedHook(fn) {
  unauthorizedHook = fn
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
  let res
  try {
    res = await fetch(apiUrl(path), { method, headers, body: payload })
  } catch (e) {
    throw new ApiError({ status: 0, message: NETWORK_ERROR_MESSAGE })
  }
  if (res.status === 401) {
    setToken(null)
    if (unauthorizedHook) unauthorizedHook()
  }
  const ct = res.headers.get('content-type') || ''
  const data = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) throw errorFromResponse(res.status, data)
  if (method !== 'GET' && writeHook) writeHook()
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
  let res
  try {
    res = await fetch(apiUrl(path), {
      method: 'POST', headers, body: JSON.stringify(body),
    })
  } catch (e) {
    throw new ApiError({ status: 0, message: NETWORK_ERROR_MESSAGE })
  }
  if (res.status === 401) {
    setToken(null)
    if (unauthorizedHook) unauthorizedHook()
  }
  if (!res.ok || !res.body) {
    let data = null
    try { data = await res.json() } catch (e) { /* non-JSON: curated message */ }
    throw errorFromResponse(res.status, data)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  // A malformed line is skipped (warned once per stream) so one bad line can't
  // end the reply; only the parse is guarded — onEvent's own errors propagate.
  let warned = false
  const emit = (line) => {
    let evt
    try {
      evt = JSON.parse(line)
    } catch (e) {
      if (!warned) { console.warn('Skipped malformed stream line'); warned = true }
      return
    }
    onEvent(evt)
  }
  const flush = (chunk, last) => {
    buf += chunk
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) emit(line)
    }
    if (last && buf.trim()) emit(buf.trim())
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    flush(decoder.decode(value, { stream: true }), false)
  }
  flush(decoder.decode(), true)
  if (writeHook) writeHook()
}
