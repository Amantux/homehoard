// A tiny in-memory ring buffer of the most recent client-side errors, so a bug
// report can carry the actual stack that led to it. Nothing is persisted or sent
// anywhere on its own — it's only read when the user opens the bug reporter.
const MAX = 5
const errors = []

function record(entry) {
  errors.push(entry)
  while (errors.length > MAX) errors.shift()
}

// Register global handlers once. Safe to call from main.js at startup.
export function installErrorLog() {
  if (window.__bugErrorLogInstalled) return
  window.__bugErrorLogInstalled = true
  window.addEventListener('error', (e) => {
    record({
      at: new Date().toISOString(),
      message: String(e.message || 'error'),
      source: e.filename ? `${e.filename}:${e.lineno || 0}:${e.colno || 0}` : '',
      stack: e.error && e.error.stack ? String(e.error.stack) : '',
    })
  })
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason
    record({
      at: new Date().toISOString(),
      message: r && r.message ? String(r.message) : String(r),
      source: 'unhandledrejection',
      stack: r && r.stack ? String(r.stack) : '',
    })
  })
}

export function recentErrors() {
  return errors.slice()
}
