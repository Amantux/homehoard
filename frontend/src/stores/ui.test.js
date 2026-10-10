import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUI } from './ui.js'

describe('ui live sync', () => {
  let doc, win, api
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
    doc = { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
    win = { addEventListener: vi.fn(), removeEventListener: vi.fn() }
    vi.stubGlobal('document', doc)
    vi.stubGlobal('window', win)
    api = { get: vi.fn().mockResolvedValue({ cursor: 1 }) }
    setActivePinia(createPinia())
  })
  // The live-sync handles are module-level, so stop between tests.
  afterEach(() => { useUI().stopLiveSync(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it('stopLiveSync clears the interval and removes both listeners', async () => {
    const ui = useUI()
    ui.startLiveSync(api)
    await vi.advanceTimersByTimeAsync(0)
    ui.stopLiveSync()
    const n = api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(24000)
    expect(api.get.mock.calls.length).toBe(n)
    const vis = doc.addEventListener.mock.calls.find((c) => c[0] === 'visibilitychange')[1]
    const foc = win.addEventListener.mock.calls.find((c) => c[0] === 'focus')[1]
    expect(doc.removeEventListener).toHaveBeenCalledWith('visibilitychange', vis)
    expect(win.removeEventListener).toHaveBeenCalledWith('focus', foc)
  })

  it('start -> stop -> start rebuilds the timer', async () => {
    const ui = useUI()
    ui.startLiveSync(api)
    ui.stopLiveSync()
    ui.startLiveSync(api)
    await vi.advanceTimersByTimeAsync(0)
    const n = api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(12000)
    expect(api.get.mock.calls.length).toBe(n + 1)
  })

  it('skips a tick while a /changes request is outstanding', async () => {
    const ui = useUI()
    api.get = vi.fn(() => new Promise(() => {}))
    ui.startLiveSync(api)
    await vi.advanceTimersByTimeAsync(36000)
    expect(api.get).toHaveBeenCalledTimes(1)
    ui.stopLiveSync()
  })
})
