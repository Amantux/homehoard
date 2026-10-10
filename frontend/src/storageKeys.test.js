import { describe, it, expect, afterEach, vi } from 'vitest'
import { migrateLegacyKeys, TOKEN, ITEM_VIEW, THEME } from './storageKeys'

function fakeStorage(initial = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] },
  }
}

describe('migrateLegacyKeys', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('moves legacy-only values to the new keys and deletes the old ones', () => {
    const s = fakeStorage({ easyinv_token: 't1', easyinv_itemview: 'list', easyinv_theme: 'dark' })
    vi.stubGlobal('localStorage', s)
    migrateLegacyKeys()
    expect(s.data).toEqual({ [TOKEN]: 't1', [ITEM_VIEW]: 'list', [THEME]: 'dark' })
  })

  it('keeps the new value when both exist, and still deletes the old key', () => {
    const s = fakeStorage({ easyinv_token: 'old', [TOKEN]: 'new' })
    vi.stubGlobal('localStorage', s)
    migrateLegacyKeys()
    expect(s.data).toEqual({ [TOKEN]: 'new' })
  })

  it('is a no-op when nothing is stored', () => {
    const s = fakeStorage({ unrelated: 'x' })
    vi.stubGlobal('localStorage', s)
    migrateLegacyKeys()
    expect(s.data).toEqual({ unrelated: 'x' })
  })

  it('does not throw when storage access throws', () => {
    const boom = () => { throw new Error('SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(() => migrateLegacyKeys()).not.toThrow()
  })
})
