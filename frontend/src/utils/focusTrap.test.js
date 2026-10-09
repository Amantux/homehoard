import { describe, it, expect, vi } from 'vitest'
import { focusableIn, trapTab } from './focusTrap.js'

// Minimal duck-typed DOM: the helpers only use querySelectorAll / focus /
// hidden / getAttribute, so no jsdom is needed.
const el = (name) => ({ name, hidden: false, getAttribute: () => null, focus: vi.fn() })
const rootWith = (els) => ({ querySelectorAll: () => els, focus: vi.fn() })
const tab = (shiftKey = false) => ({ key: 'Tab', shiftKey, preventDefault: vi.fn() })

describe('focusTrap', () => {
  it('Tab from the last focusable wraps to the first', () => {
    const [a, b, c] = [el('a'), el('b'), el('c')]
    const ev = tab()
    expect(trapTab(ev, rootWith([a, b, c]), c)).toBe(true)
    expect(a.focus).toHaveBeenCalled()
    expect(ev.preventDefault).toHaveBeenCalled()
  })

  it('Shift+Tab from the first focusable wraps to the last', () => {
    const [a, b, c] = [el('a'), el('b'), el('c')]
    expect(trapTab(tab(true), rootWith([a, b, c]), a)).toBe(true)
    expect(c.focus).toHaveBeenCalled()
  })

  it('Tab in the middle is left to the browser', () => {
    const [a, b, c] = [el('a'), el('b'), el('c')]
    const ev = tab()
    expect(trapTab(ev, rootWith([a, b, c]), b)).toBe(false)
    expect(ev.preventDefault).not.toHaveBeenCalled()
  })

  it('no focusables keeps focus on the root', () => {
    const root = rootWith([])
    const ev = tab()
    expect(trapTab(ev, root, null)).toBe(true)
    expect(root.focus).toHaveBeenCalled()
    expect(ev.preventDefault).toHaveBeenCalled()
  })

  it('ignores non-Tab keys and hidden elements', () => {
    const a = el('a'); const h = { ...el('h'), hidden: true }
    expect(focusableIn(rootWith([a, h]))).toEqual([a])
    expect(trapTab({ key: 'Enter' }, rootWith([a]), a)).toBe(false)
  })
})
