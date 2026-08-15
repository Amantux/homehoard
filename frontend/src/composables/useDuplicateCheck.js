// A soft "you already have one of these" before creating an item.
//
// Persona finding: creating "AA batteries" twice draws no reaction, and the
// second row silently splits the inventory (quantities, thresholds and history
// divide between twins — the restock list then lies about both). A HARD block
// would be wrong — two "Umbrella"s in different places is legitimate — so this
// asks, names the existing item and where it lives, and lets the user choose.
import { api } from '../api'

export async function confirmNotDuplicate(name) {
  const q = (name || '').trim()
  if (!q) return true
  let existing
  try {
    const res = await api.get(`/items?q=${encodeURIComponent(q)}&pageSize=5`)
    existing = (res.items || []).filter(
      (i) => i.name.trim().toLowerCase() === q.toLowerCase())
  } catch (e) {
    return true // the nudge is best-effort; never let it block creation
  }
  if (!existing.length) return true
  const it = existing[0]
  const where = it.bin?.name || it.location?.name || 'no location'
  return confirm(
    `You already have “${it.name}” (${it.quantity} in ${where}). ` +
    `Creating another makes a separate item whose quantity and restock ` +
    `tracking are counted apart. Create it anyway?`)
}
