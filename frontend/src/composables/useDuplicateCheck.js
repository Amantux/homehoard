// Duplicate awareness, WITHOUT create-time friction.
//
// First cut was a confirm() before creating — rejected in review: confirming
// every new item punishes the common case to guard the rare one. Now creation
// is never interrupted; findDuplicates() just reports, callers show a passive
// toast pointing at the Duplicates page, and the resolution lives there.
import { api } from '../api'

export async function findDuplicates(name) {
  const q = (name || '').trim()
  if (!q) return []
  try {
    const res = await api.get(`/items?q=${encodeURIComponent(q)}&pageSize=6`)
    return (res.items || []).filter(
      (i) => i.name.trim().toLowerCase() === q.toLowerCase())
  } catch (e) {
    return [] // best-effort: awareness must never break creation
  }
}
