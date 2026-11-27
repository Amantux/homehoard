// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { getLastVisit, setLastVisit, FIRST_VISIT_WATERMARK } from './lastVisit'

function fakeStorage(initial = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] },
  }
}

describe('lastVisit', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns null when no watermark is stored', () => {
    vi.stubGlobal('localStorage', fakeStorage())
    expect(getLastVisit()).toBeNull()
  })

  it('round-trips the stored ISO watermark', () => {
    const s = fakeStorage()
    vi.stubGlobal('localStorage', s)
    setLastVisit('2026-11-20T00:00:00+00:00')
    expect(getLastVisit()).toBe('2026-11-20T00:00:00+00:00')
    setLastVisit(null)
    expect(getLastVisit()).toBeNull()
  })

  it('does not throw when storage access is unavailable', () => {
    const boom = () => { throw new Error('SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(() => { getLastVisit(); setLastVisit('2026-11-20T00:00:00Z') }).not.toThrow()
  })

  it('seeds the first visit at the epoch', () => {
    expect(FIRST_VISIT_WATERMARK).toBeTruthy()
  })
})
