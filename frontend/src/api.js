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
