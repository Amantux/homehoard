import { describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ api: { get: vi.fn() } }))

const { shortDate } = await import('./format')

describe('shortDate', () => {
  it('formats a UTC-midnight timestamp as that calendar day, whatever the zone', () => {
    // Compare against a local-constructed date: the two must agree in every TZ.
    expect(shortDate('2026-07-10T00:00:00+00:00')).toBe(new Date(2026, 6, 10).toLocaleDateString())
  })
  it('formats a bare date the same way', () => {
    expect(shortDate('2026-07-10')).toBe(new Date(2026, 6, 10).toLocaleDateString())
  })
  it('returns a dash for empty values', () => {
    expect(shortDate(null)).toBe('—')
  })
})
