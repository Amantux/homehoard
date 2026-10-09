// Focus-trap helpers for BaseModal. Pure (they only touch the root passed in
// and the element given as `active`) so they unit-test without mounting.
const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

export function focusableIn(root) {
  if (!root) return []
  return Array.from(root.querySelectorAll(FOCUSABLE))
    .filter((el) => !el.hidden && el.getAttribute('aria-hidden') !== 'true')
}

// Keep Tab / Shift+Tab inside `root`. Returns true when it moved focus itself.
export function trapTab(event, root, active = document.activeElement) {
  if (event.key !== 'Tab' || !root) return false
  const els = focusableIn(root)
  if (!els.length) {
    event.preventDefault()
    root.focus()
    return true
  }
  const first = els[0]
  const last = els[els.length - 1]
  const inside = els.includes(active)
  if (event.shiftKey && (active === first || !inside)) {
    event.preventDefault()
    last.focus()
    return true
  }
  if (!event.shiftKey && (active === last || !inside)) {
    event.preventDefault()
    first.focus()
    return true
  }
  return false
}
