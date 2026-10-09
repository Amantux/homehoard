// HTML escaping for the few places that build markup as a string (e.g. writing a
// print document into a popup) instead of going through Vue's template escaping.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c])
}

// The single-tag print document. Every interpolated value is escaped — the
// heading and caption are user-supplied, and the popup is same-origin.
export function buildPrintHtml({ title, imgSrc, heading, caption }) {
  return `<html><head><title>${escapeHtml(title)}</title></head>
    <body style="text-align:center;font-family:sans-serif;padding:40px">
    <img src="${escapeHtml(imgSrc)}" style="width:260px;height:260px" />
    <h2>${escapeHtml(heading)}</h2><p style="color:#888">${escapeHtml(caption)}</p>
    <script>window.onload=()=>window.print()</scr${''}ipt></body></html>`
}
