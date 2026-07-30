// The chat assistant ends a completed bug-report walkthrough with this marker; the UI
// hides it and offers a button that opens the Report-a-bug modal prefilled with the
// summary. Kept pure + separately tested because a leaked marker would be posted into
// a public GitHub issue.
export const BUG_MARKER = '[[REPORT_BUG]]'

// Streaming display: strip any COMPLETE marker AND trim a trailing PARTIAL prefix of it
// (e.g. "…text [[REPO" → "…text"), so the marker never flashes as it streams in.
export function hideMarker(text) {
  if (!text) return text
  let t = text.split(BUG_MARKER).join('')
  for (let i = BUG_MARKER.length - 1; i > 0; i--) {
    if (t.endsWith(BUG_MARKER.slice(0, i))) { t = t.slice(0, -i); break }
  }
  return t.replace(/\s+$/, '')
}

// Final reply (stream `done` / POST): complete-marker strip only — the text is done, so
// no trailing-partial trim. `summary` = the clean text when a marker was present, else null.
export function finalizeReply(text) {
  if (!text || !text.includes(BUG_MARKER)) return { content: text, summary: null }
  const content = text.split(BUG_MARKER).join('').replace(/\s+$/, '')
  return { content, summary: content }
}
