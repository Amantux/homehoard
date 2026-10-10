import { describe, it, expect } from 'vitest'
import { safeRedirect } from './safeRedirect.js'

describe('safeRedirect', () => {
  it('keeps an in-app path, including its query', () => {
    expect(safeRedirect('/items/42')).toBe('/items/42')
    expect(safeRedirect('/items?q=drill&page=2')).toBe('/items?q=drill&page=2')
    expect(safeRedirect('/')).toBe('/')
  })

  it.each([
    ['protocol-relative', '//evil.com'],
    ['protocol-relative with path', '//evil.com/items'],
    ['absolute URL', 'https://evil.com'],
    ['javascript scheme', 'javascript:alert(1)'],
    ['backslash as slash', '/\\evil.com'],
    ['backslash later', '/items\\..\\x'],
    ['tab collapses to //', '/\t/evil.com'],
    ['newline collapses to //', '/\n/evil.com'],
    ['relative path', 'items/42'],
    ['empty', ''],
  ])('rejects %s', (_label, input) => {
    expect(safeRedirect(input)).toBe('/')
  })

  it.each([undefined, null, 42, ['/items'], { path: '/items' }])('rejects non-string %j', (input) => {
    expect(safeRedirect(input)).toBe('/')
  })
})
