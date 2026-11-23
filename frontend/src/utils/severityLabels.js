// Plain-language severity labels.
//
// Single source of truth for turning the severity tokens the attention digest,
// inventory/completeness report and dashboard tiles already use (overdue, low,
// expiring soon, warranty statuses, …) into short human labels for chips, badges
// and briefings. Pure + unit tested (severityLabels.test.js) so views adopt it
// instead of keeping their own label maps.

export const SEVERITY_LABELS = {
  // Attention digest / dashboard briefing, stat tiles and HA-card badges.
  overdue: 'Overdue',
  maintenanceOverdue: 'Overdue',
  warrantyExpiringSoon: 'Expiring soon',
  low: 'Low',
  runningLow: 'Running low',
  needsAttention: 'Needs attention',
  // Warranty status tokens from the inventory report / HA sensors.
  lifetime: 'Lifetime',
  active: 'Active',
  expiring: 'Expiring soon',
  // The same expiring window, named after the digest's phrase rather than the
  // bare status token — both resolve to the same plain-language label.
  expiringSoon: 'Expiring soon',
  expired: 'Expired',
  none: 'None',
  // Completeness: what an item is still missing.
  missingPrice: 'Missing price',
  missingFields: 'Missing fields',
  // Lifecycle states rendered as badges / dots.
  out: 'Out',
  checkedOut: 'Checked out',
  scheduled: 'Scheduled',
  completed: 'Completed',
}

// Lookup key for a token: trim, split camelCase / separators into words,
// collapse spaces, lowercase. So 'Maintenance Overdue', 'maintenance_overdue'
// and 'maintenanceOverdue' all resolve to the same key.
function normalizeKey(token) {
  return String(token ?? '')
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[\s_-]+/g, ' ')
    .trim()
    .toLowerCase()
}

const LABELS = new Map(
  Object.entries(SEVERITY_LABELS).map(([token, label]) => [normalizeKey(token), label])
)

// Fallback: a sensible capitalized form of the token ('banana' -> 'Banana',
// 'needsAttention' -> 'Needs Attention').
function titleCase(token) {
  const pretty = String(token ?? '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[\s_-]+/g, ' ')
    .trim()
  const titled = pretty
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
  return titled
}

// Short plain-language label for a severity token; unknown tokens fall back to
// a capitalized form of the token itself.
export function severityLabel(token) {
  const key = normalizeKey(token)
  const mapped = key ? LABELS.get(key) : undefined
  if (mapped) return mapped
  const raw = String(token ?? '').trim()
  return raw ? titleCase(raw) : ''
}
