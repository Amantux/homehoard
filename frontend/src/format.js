import { ref } from 'vue'
import { api } from './api'

export const currencySymbol = ref('$')

// `loaded` flips only after a successful fetch, so a failure (offline, expired
// session) retries on the next call; concurrent callers share one request.
let loaded = false
let inflight = null
export function loadCurrency() {
  if (loaded) return Promise.resolve()
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const group = await api.get('/groups')
      const currencies = await api.get('/currency')
      const c = currencies.find((x) => x.code === group.currency)
      if (c) currencySymbol.value = c.symbol
      loaded = true
    } catch (e) {
      /* ignore — keep the default symbol and retry next time */
    } finally {
      inflight = null
    }
  })()
  return inflight
}

export function money(v) {
  return (
    currencySymbol.value +
    Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  )
}

// Date-only fields (purchaseDate, warrantyExpires, due dates…) arrive as
// UTC midnight with an explicit +00:00. Formatting that instant in the
// viewer's zone shows the previous day west of UTC, so take the calendar
// date and format it as a LOCAL date instead.
export function shortDate(v) {
  if (!v) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v))
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(v)
  return d.toLocaleDateString()
}
