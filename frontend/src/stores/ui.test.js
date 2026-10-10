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

describe('ui toasts', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
    setActivePinia(createPinia())
  })
  afterEach(() => { useUI().resumeToasts(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it('clearErrorToasts removes only error toasts', () => {
    const ui = useUI()
    ui.toast('Saved')
    ui.error('Could not load bins')
    ui.toast('Heads up', 'info')
    ui.error('Second failure')
    ui.clearErrorToasts()
    expect(ui.toasts.map((t) => t.message)).toEqual(['Saved', 'Heads up'])
  })

  it('pauseToasts holds auto-dismiss until resumeToasts', async () => {
    const ui = useUI()
    ui.toast('Saved')
    await vi.advanceTimersByTimeAsync(2000)
    ui.pauseToasts()
    await vi.advanceTimersByTimeAsync(10000)
    expect(ui.toasts).toHaveLength(1)
    ui.resumeToasts()
    await vi.advanceTimersByTimeAsync(1100)
    expect(ui.toasts).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(200)
    expect(ui.toasts).toHaveLength(0)
  })

  it('a pause left over from an emptied stack does not freeze the next toast', async () => {
    const ui = useUI()
    ui.toast('Saved')
    ui.pauseToasts()
    ui.dismiss(ui.toasts[0].id) // stack empties under the pointer: no mouseleave
    ui.toast('Saved again')
    await vi.advanceTimersByTimeAsync(3300)
    expect(ui.toasts).toHaveLength(0)
  })
})
