import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// The ui store reads localStorage at state init; node has none by default.
globalThis.localStorage ??= { getItem: () => null, setItem() {}, removeItem() {} }

const { useUI } = await import('../stores/ui')
const { useConfirm } = await import('./useConfirm')

describe('useConfirm', () => {
  let ui, confirm
  beforeEach(() => {
    setActivePinia(createPinia())
    ui = useUI()
    confirm = useConfirm()
  })

  it('resolves true on accept and clears the request', async () => {
    const p = confirm({ title: 'Delete "Drill"?', danger: true })
    expect(ui.confirmRequest).toMatchObject({ title: 'Delete "Drill"?', danger: true, confirmLabel: 'Confirm' })
    ui.resolveConfirm(true)
    await expect(p).resolves.toBe(true)
    expect(ui.confirmRequest).toBeNull()
  })

  it('resolves false on cancel', async () => {
    const p = confirm({ title: 'x' })
    ui.resolveConfirm(false)
    await expect(p).resolves.toBe(false)
  })

  it('rejects a second request while one is pending, leaving the first intact', async () => {
    const first = confirm({ title: 'first' })
    await expect(confirm({ title: 'second' })).rejects.toThrow(/already open/)
    expect(ui.confirmRequest.title).toBe('first')
    ui.resolveConfirm(true)
    await expect(first).resolves.toBe(true)
  })
})
