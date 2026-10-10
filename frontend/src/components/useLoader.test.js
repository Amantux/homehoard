import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLoader } from './useLoader.js'

// A loadFn whose calls each return a promise the test resolves by hand, and
// which tracks how many calls are in flight at once.
function fakeLoad(target) {
  const calls = []
  let inFlight = 0
  let maxInFlight = 0
  const fn = vi.fn(() => {
    inFlight += 1
    maxInFlight = Math.max(maxInFlight, inFlight)
    let resolve
    const p = new Promise((r) => { resolve = r }).then((v) => { target.value = v; inFlight -= 1 })
    calls.push(resolve)
    return p
  })
  return { fn, calls, max: () => maxInFlight }
}
const tick = () => new Promise((r) => setTimeout(r, 0))

describe('useLoader serialization', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
    // onUnmounted() outside a component warns; irrelevant here.
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    setActivePinia(createPinia())
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('a refresh arriving mid-reload re-runs after it (not dropped)', async () => {
    const target = { value: null }
    const f = fakeLoad(target)
    const { reload, refresh } = useLoader(f.fn, { immediate: false })
    const r1 = reload()
    refresh()
    expect(f.fn).toHaveBeenCalledTimes(1)
    f.calls[0]('first')
    await tick()
    expect(f.fn).toHaveBeenCalledTimes(2)
    f.calls[1]('second')
    await r1
    expect(target.value).toBe('second')
  })

  it('overlapping reloads never run loadFn concurrently; latest response wins', async () => {
    const target = { value: null }
    const f = fakeLoad(target)
    const { reload, loading } = useLoader(f.fn, { immediate: false })
    const r1 = reload()
    const r2 = reload()
    await tick()
    expect(f.max()).toBe(1)
    f.calls[0]('stale')
    await tick()
    expect(f.fn).toHaveBeenCalledTimes(2)
    f.calls[1]('fresh')
    await Promise.all([r1, r2])
    expect(f.max()).toBe(1)
    expect(target.value).toBe('fresh')
    expect(loading.value).toBe(false)
  })
})
