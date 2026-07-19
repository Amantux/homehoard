// Parse a free-text item line like "3 AA batteries in the kitchen drawer" into
// { quantity, name, placeText }. Deliberately simple and predictable — the
// parsed values pre-fill editable fields, so a wrong guess is easily corrected.

const PLACE_RE = /\s+(?:in|into|inside|on|under|at)\s+(?:the\s+)?(.+)$/i

export function parseQuickAdd(text) {
  let rest = (text || '').trim()
  let quantity = 1
  let placeText = ''

  // Leading quantity: "3 AA batteries", "12x zip ties".
  const qty = rest.match(/^(\d{1,5})\s*(?:x|×)?\s+(.+)$/i)
  if (qty) {
    quantity = parseInt(qty[1], 10)
    rest = qty[2].trim()
  }

  // Trailing place: "... in the kitchen drawer", "... on shelf B".
  const place = rest.match(PLACE_RE)
  if (place) {
    placeText = place[1].trim()
    rest = rest.slice(0, place.index).trim()
  }

  return { quantity, name: rest, placeText }
}
