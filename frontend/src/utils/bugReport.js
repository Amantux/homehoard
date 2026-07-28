// Pure helpers for the "Report a bug" deep-link flow. No network, no secrets:
// we only assemble a GitHub "new issue" URL from facts the user can see and edit.
// Everything user- or env-supplied is percent-encoded, so a description can never
// break out of the URL.

// Keep the issue body well under GitHub's ~8 KB URL ceiling. The final URL length
// is re-checked by the caller (encoding expands it), which falls back to clipboard.
export const MAX_BODY = 4000

export function truncate(text, max) {
  if (!text) return ''
  const s = String(text)
  return s.length <= max ? s : s.slice(0, max) + '\n…clipped…'
}

export function isIngress() {
  return /hassio_ingress/.test(window.location.pathname)
}

// A scrubbed diagnostics block: only coarse, publishable facts (no keys, no base
// URLs, no DB URL, no inventory contents). `diagnostics` is the /diagnostics body.
export function buildDiagnostics({ app, version, diagnostics, errors, route }) {
  const d = diagnostics || {}
  const lines = [
    `- App: ${app} ${version || 'unknown'}`,
    `- Route: ${route || ''}`,
    `- DB backend: ${d.dbBackend || 'unknown'}`,
    `- AI provider: ${d.aiProvider || 'none'}`,
    `- MCP enabled: ${d.mcpEnabled === undefined ? 'unknown' : d.mcpEnabled}`,
    `- Ingress: ${isIngress()}`,
    `- Browser: ${truncate(navigator.userAgent, 300)}`,
    `- Viewport: ${window.innerWidth}×${window.innerHeight}`,
    `- When: ${new Date().toISOString()}`,
  ]
  const errs = (errors || []).filter(Boolean)
  if (errs.length) {
    lines.push('', 'Recent client errors (most recent last):')
    for (const e of errs) {
      const block = truncate(`${e.at} ${e.message}\n${e.source}\n${e.stack}`.trim(), 1200)
      lines.push('```', block, '```')
    }
  }
  return lines.join('\n')
}

function qs(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
}

// type: 'bug' | 'feature'
export function issueUrl({ repo, type, title, body }) {
  const label = type === 'feature' ? 'enhancement' : 'bug'
  const prefix = type === 'feature' ? '[Feature] ' : '[Bug] '
  const query = qs({
    title: prefix + String(title || '').trim(),
    body: body || '',
    labels: label,
  })
  return `https://github.com/${repo}/issues/new?${query}`
}

export function searchUrl({ repo, query }) {
  const q = `is:issue ${String(query || '').trim()}`.trim()
  return `https://github.com/${repo}/issues?${qs({ q })}`
}
