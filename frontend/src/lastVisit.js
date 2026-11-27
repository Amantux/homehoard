import { LAST_VISIT } from './storageKeys'

// Last-visit watermark behind the Dashboard's "what changed since my last
// visit" strip. Storage can throw (private mode, disabled site data) — a failed
// read must never crash the dashboard, and a failed write just means the next
// visit asks for the full delta again.
export function getLastVisit() {
  try {
    return localStorage.getItem(LAST_VISIT)
  } catch {
    // ignore: storage unavailable
    return null
  }
}

export function setLastVisit(iso) {
  try {
    if (iso) localStorage.setItem(LAST_VISIT, iso)
    else localStorage.removeItem(LAST_VISIT)
  } catch {
    // ignore: storage unavailable
  }
}

// First visit: no watermark yet, so the first real delta reports everything that
// happened since the beginning instead of showing a blank strip.
export const FIRST_VISIT_WATERMARK = '1970-01-01T00:00:00Z'
