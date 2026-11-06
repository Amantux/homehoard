// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Restock = (await import('./Restock.vue')).default

const BAGS = { id: 'b', name: 'Bags', onHand: 1, threshold: 6, target: 6, suggestedQuantity: 6 }
const BATTERIES = { id: 'a', name: 'AA batteries', onHand: 8, threshold: 10, target: 12, suggestedQuantity: 4 }
const CUPS = { id: 'c', name: 'Cups', onHand: 9, threshold: 10, target: 12, suggestedQuantity: 3 }
const BAGS_BOUGHT = { ...BAGS, onHand: 7, suggestedQuantity: 1, isLow: false, bought: 6, previousOnHand: 1 }
const BATTERIES_BOUGHT = { ...BATTERIES, onHand: 12, suggestedQuantity: 1, isLow: false, bought: 4, previousOnHand: 8 }

const apiError = (status, message) => Object.assign(new Error(message), { status })

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

describe('Restock one-tap Bought', () => {
  let wrapper, ui, router
  let list    // what GET /restock answers
  let item    // what GET /items/<id> answers (or throws, when it's an Error)

  // What the real api does on a successful write, and what App.vue wires to
  // dataChanged: every open view refreshes because of the write itself.
  const writes = (result) => async () => {
    const value = await result
    ui.dataChanged()
    return value
  }

  beforeEach(async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.resetAllMocks()
    const pinia = createPinia()
    setActivePinia(pinia)
    ui = useUI()
    list = [BAGS, BATTERIES, CUPS]
    item = null
    api.get.mockImplementation(async (url) => {
      if (url === '/restock') return { items: list.map((r) => ({ ...r })) }
      if (item instanceof Error) throw item
      return item
    })
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/restock', component: Restock },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push('/restock')
    await router.isReady()
    wrapper = mount(Restock, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
  })
  afterEach(() => {
    wrapper.unmount()
    ui.toasts.slice().forEach((t) => ui.dismiss(t.id))
    vi.useRealTimers()
  })

  const button = (name) => wrapper.find(`button[aria-label$=": ${name}"]`)
  const slots = () => wrapper.findAll('tbody tr').map((tr) => tr.find('strong').text())
  const onHand = (name) => wrapper.findAll('tbody tr')
    .find((tr) => tr.find('strong').text() === name).findAll('td')[1].text()
  const restockGets = () => api.get.mock.calls.filter(([u]) => u === '/restock').length
  const errors = () => ui.toasts.filter((t) => t.type === 'error').map((t) => t.message)
  const lastToast = () => ui.toasts[ui.toasts.length - 1]
  const later = (ms = 1000) => vi.setSystemTime(Date.now() + ms)
  async function tap(name) {
    await button(name).trigger('click')
    await flushPromises()
  }

  it('labels the button with what it does', () => {
    expect(button('AA batteries').text()).toBe('Bought 4')
    expect(button('Bags').text()).toBe('Bought 6')
  })

  it('names the action column for assistive tech', () => {
    expect(wrapper.findAll('thead th').at(-1).text()).toBe('Record purchase')
  })

  it('records the number on the button, says so, and holds the row in place with Undo', async () => {
    api.post.mockImplementation(writes(BATTERIES_BOUGHT))
    list = [BAGS, CUPS]
    const before = restockGets()
    expect(wrapper.find('.page-head .badge').text()).toBe('3 low')

    await tap('AA batteries')

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/restock/a/restocked', { quantity: 4 })
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    expect(onHand('AA batteries')).toBe('12')
    expect(button('AA batteries').text()).toBe('Undo')
    expect(wrapper.find('.page-head .badge').text()).toBe('2 low')
    expect(ui.toasts).toHaveLength(1)
    expect(ui.toasts[0].type).toBe('success')
    expect(ui.toasts[0].message).toContain('AA batteries')
    expect(ui.toasts[0].message).toContain('12 on hand')
    expect(ui.toasts[0].message).not.toContain('still')
    expect(restockGets()).toBeGreaterThan(before)
  })

  // ---- the row under the pointer is the row that was aimed at -----------------

  it('a double-click records once, and its second click touches nothing else', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]

    await tap('Bags')
    later(120)
    // The same spot on screen: the first button. It must still be Bags.
    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/restock/b/restocked', { quantity: 6 })
    expect(api.put).not.toHaveBeenCalled()
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    expect(button('Bags').text()).toBe('Undo')
  })

  it('a burst of clicks is one gesture however long it runs: a held Enter neither re-buys nor undoes', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]

    await tap('Bags')
    for (let i = 0; i < 10; i++) {
      later(300)
      await tap('Bags')
    }

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.get).not.toHaveBeenCalledWith('/items/b')
    expect(api.put).not.toHaveBeenCalled()
  })

  it('a click while the write is pending is ignored, on that row only', async () => {
    const post = deferred()
    api.post.mockImplementation(writes(post.promise))
    list = [BATTERIES, CUPS]

    await button('Bags').trigger('click')
    expect(button('Bags').text()).toBe('Adding…')
    expect(button('Bags').attributes('aria-disabled')).toBe('true')
    expect(button('AA batteries').text()).toBe('Bought 4')
    expect(button('AA batteries').attributes('aria-disabled')).toBe('false')

    later()
    await tap('Bags')
    expect(api.post).toHaveBeenCalledTimes(1)

    post.resolve(BAGS_BOUGHT)
    await flushPromises()
    expect(button('Bags').text()).toBe('Undo')
    expect(button('Bags').attributes('aria-disabled')).toBe('false')
  })

  it('working down the list writes the item aimed at, not the one that would have slid up', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]
    await tap('Bags')

    later(350)
    api.post.mockImplementation(writes(BATTERIES_BOUGHT))
    list = [CUPS]
    await wrapper.findAll('tbody button')[1].trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(2)
    expect(api.post).toHaveBeenLastCalledWith('/restock/a/restocked', { quantity: 4 })
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    expect(button('Cups').text()).toBe('Bought 3')
  })

  it('does not re-sort while the list is being worked through', async () => {
    api.post.mockImplementation(writes({ ...BATTERIES_BOUGHT, onHand: 9, isLow: true }))
    list = [{ ...CUPS, onHand: 0 }, BAGS, { ...BATTERIES, onHand: 9 }]

    await tap('AA batteries')

    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    expect(onHand('Cups')).toBe('0') // numbers still update in place
  })

  it('a refresh landing while the write is pending cannot drop the row', async () => {
    const post = deferred()
    api.post.mockImplementation(writes(post.promise))
    list = [BATTERIES, CUPS]    // the POST has committed; its response hasn't arrived

    await button('Bags').trigger('click')
    ui.dataChanged()
    await flushPromises()
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])

    post.resolve(BAGS_BOUGHT)
    await flushPromises()
    expect(button('Bags').text()).toBe('Undo')
  })

  it('a list fetched before the write landed cannot undo the hold with its old count', async () => {
    const stale = deferred()
    const fresh = [BATTERIES, CUPS]
    api.get.mockImplementationOnce(() => stale.promise) // e.g. the live-sync poll
    ui.dataChanged()
    await flushPromises()
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = fresh

    await tap('Bags')           // lands while that GET is still out
    expect(button('Bags').text()).toBe('Undo')

    stale.resolve({ items: [BAGS, BATTERIES, CUPS] })
    await flushPromises()

    expect(onHand('Bags')).toBe('7')
    expect(button('Bags').text()).toBe('Undo')
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    // ...and the write's own refresh, queued behind it, still got fetched and applied.
    list = [{ ...BATTERIES, onHand: 5 }, CUPS]
    ui.dataChanged()
    await flushPromises()
    expect(onHand('AA batteries')).toBe('5')
  })

  it('an item that newly runs low joins at the end, leaving every slot alone', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [{ id: 'z', name: 'Aardvark food', onHand: 0, threshold: 1, target: 1, suggestedQuantity: 2 }, BATTERIES, CUPS]

    await tap('Bags')
    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups', 'Aardvark food'])

    // Nothing moved, so the next row is tappable straight away.
    api.post.mockImplementation(writes(BATTERIES_BOUGHT))
    later(50)
    await tap('AA batteries')
    expect(api.post).toHaveBeenLastCalledWith('/restock/a/restocked', { quantity: 4 })
  })

  it('a click right after someone else moved the rows does not write the row that moved into place', async () => {
    list = [BATTERIES, CUPS]    // another client restocked Bags: the rows slide up
    ui.dataChanged()
    await flushPromises()
    expect(slots()).toEqual(['AA batteries', 'Cups'])
    api.post.mockImplementation(writes(BATTERIES_BOUGHT))

    later(200)
    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    expect(api.post).not.toHaveBeenCalled()

    // Once they have settled, a click there means what it says.
    later(1000)
    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/restock/a/restocked', { quantity: 4 })
  })

  it('a minute after the last tap, a refresh brings the list back to the server\'s order', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]
    await tap('Bags')

    later(61000)
    list = [CUPS, BATTERIES]
    ui.dataChanged()
    await flushPromises()

    expect(slots()).toEqual(['Cups', 'AA batteries'])
    // That moved rows too, so the same guard applies to it.
    api.post.mockImplementation(writes(BATTERIES_BOUGHT))
    later(100)
    await wrapper.findAll('tbody button')[0].trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledTimes(1)
  })

  it('once the list has moved on, an item that runs low again is an ordinary row, not an old Undo', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]
    await tap('Bags')

    later(61000)
    ui.dataChanged()
    await flushPromises()
    expect(slots()).toEqual(['AA batteries', 'Cups'])

    list = [BATTERIES, CUPS, BAGS_BOUGHT]   // the same count this page once wrote
    later(61000)
    ui.dataChanged()
    await flushPromises()
    expect(button('Bags').text()).toBe('Bought 1')
  })

  it('a bought row goes back to normal if the server lists it at a count this page did not write', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    list = [BATTERIES, CUPS]
    await tap('Bags')
    expect(button('Bags').text()).toBe('Undo')

    list = [{ ...BAGS, onHand: 2, suggestedQuantity: 5 }, BATTERIES, CUPS]
    ui.dataChanged()
    await flushPromises()

    expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    expect(onHand('Bags')).toBe('2')
    expect(button('Bags').text()).toBe('Bought 5')
  })

  // ---- the confirmation does not wait on the list -----------------------------

  it('confirms at once, with Undo ready, even if the refresh never comes back', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    api.get.mockReturnValue(new Promise(() => {}))

    await tap('Bags')

    expect(ui.toasts).toHaveLength(1)
    expect(ui.toasts[0].message).toContain('7 on hand')
    expect(onHand('Bags')).toBe('7')
    expect(button('Bags').text()).toBe('Undo')
    expect(button('Bags').attributes('aria-disabled')).toBe('false')
  })

  it('keeps the new state when the refresh fails', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    api.get.mockRejectedValue(new Error('offline'))

    await tap('Bags')

    expect(onHand('Bags')).toBe('7')
    expect(button('Bags').text()).toBe('Undo')
    expect(errors()).toEqual([])
  })

  it('says so when the purchase left the item low: the number on the button had gone stale', async () => {
    api.post.mockImplementation(writes({ ...BAGS_BOUGHT, onHand: 4, suggestedQuantity: 3, isLow: true }))
    list = [{ ...BAGS, onHand: 4, suggestedQuantity: 3 }, BATTERIES, CUPS]

    await tap('Bags')

    expect(lastToast().message).toContain('4 on hand')
    expect(lastToast().message).toContain('still at or below')
    expect(button('Bags').text()).toBe('Undo') // the refresh agrees on 4, so still held
  })

  // ---- navigation --------------------------------------------------------------

  it('a tap does not also open the item, though the row itself does', async () => {
    api.post.mockImplementation(writes(BAGS_BOUGHT))
    await tap('Bags')
    expect(router.currentRoute.value.path).toBe('/restock')

    await wrapper.findAll('tbody tr')[0].trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/items/b')
  })

  // ---- keyboard ---------------------------------------------------------------

  it('keeps keyboard focus on the button through Bought, Adding and Undo', async () => {
    const post = deferred()
    api.post.mockImplementation(writes(post.promise))
    list = [BATTERIES, CUPS]
    const el = button('Bags').element
    el.focus()
    expect(document.activeElement).toBe(el)

    await button('Bags').trigger('click')
    expect(button('Bags').text()).toBe('Adding…')
    expect(document.activeElement).toBe(el)

    post.resolve(BAGS_BOUGHT)
    await flushPromises()
    expect(button('Bags').text()).toBe('Undo')
    expect(button('Bags').element).toBe(el)
    expect(document.activeElement).toBe(el)
    expect(el.getAttribute('disabled')).toBeNull()
  })

  it('when a refused tap removes the focused row, focus moves to whatever took its slot', async () => {
    api.post.mockRejectedValue(apiError(422, 'This item is not on the restock list any more'))
    list = [BATTERIES, CUPS]
    button('Bags').element.focus()

    await tap('Bags')

    expect(slots()).toEqual(['AA batteries', 'Cups'])
    expect(document.activeElement).toBe(button('AA batteries').element)
  })

  it('when the last row in the list is removed, focus falls back to the row above it', async () => {
    api.post.mockRejectedValue(apiError(404, 'not found'))
    list = [BAGS, BATTERIES]
    button('Cups').element.focus()

    await tap('Cups')

    expect(document.activeElement).toBe(button('AA batteries').element)
  })

  it('when the only row is removed, focus falls back to the page heading', async () => {
    list = [BAGS]
    ui.dataChanged()
    await flushPromises()
    api.post.mockRejectedValue(apiError(404, 'not found'))
    list = []
    button('Bags').element.focus()

    later()
    await tap('Bags')

    expect(wrapper.find('tbody').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('h1').element)
  })

  it('leaves focus alone when it was somewhere else', async () => {
    api.post.mockRejectedValue(apiError(422, 'stale'))
    list = [BATTERIES, CUPS]
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    outside.focus()

    await tap('Bags')

    expect(document.activeElement).toBe(outside)
    outside.remove()
  })

  // ---- refusals ---------------------------------------------------------------

  it('on a 409 it swaps the button for a link to the item page', async () => {
    api.post.mockRejectedValue(apiError(409, 'edit placements'))
    list = [BATTERIES, CUPS]
    const before = restockGets()

    await tap('Bags')

    const link = wrapper.find('a#placements-b')
    expect(link.text()).toBe('Edit placements')
    expect(link.attributes('href')).toBe('/items/b')
    expect(document.activeElement).toBe(link.element)
    expect(button('Bags').exists()).toBe(false)
    expect(button('AA batteries').text()).toBe('Bought 4')
    // Nothing was bought, so no Undo and no claim that it was; the row is not stale.
    expect(errors()).toEqual([])
    expect(ui.toasts).toHaveLength(1)
    expect(ui.toasts[0].type).toBe('info')
    expect(ui.toasts[0].message).toContain('Bags')
    expect(restockGets()).toBe(before)

    await link.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/items/b')
  })

  it('a refused tap (422) shows why and drops the out-of-date row', async () => {
    const message = 'This item is not on the restock list any more: it is no longer low, or it was archived.'
    api.post.mockRejectedValue(apiError(422, message))
    list = [BATTERIES, CUPS]

    await tap('Bags')

    expect(errors()).toEqual([message])
    expect(slots()).toEqual(['AA batteries', 'Cups'])
    expect(wrapper.find('#placements-b').exists()).toBe(false)
  })

  it('a 404 names the item instead of a bare "not found"', async () => {
    api.post.mockRejectedValue(apiError(404, 'not found'))
    list = [BATTERIES, CUPS]

    await tap('Bags')

    expect(errors()).toEqual(['“Bags” is no longer available.'])
    expect(slots()).toEqual(['AA batteries', 'Cups'])
  })

  it('a failed tap leaves the button usable', async () => {
    api.post.mockRejectedValue(apiError(0, 'offline'))

    await tap('Bags')

    expect(errors()).toEqual(['offline'])
    expect(button('Bags').text()).toBe('Bought 6')
    expect(button('Bags').attributes('aria-disabled')).toBe('false')
  })

  it('a refused tap that hangs on its refresh still lets the row go back to normal', async () => {
    api.post.mockRejectedValue(apiError(0, 'offline'))
    api.get.mockReturnValue(new Promise(() => {}))

    await tap('Bags')

    expect(button('Bags').text()).toBe('Bought 6')
  })

  // ---- Undo -------------------------------------------------------------------

  describe('Undo', () => {
    beforeEach(async () => {
      api.post.mockImplementation(writes(BATTERIES_BOUGHT))
      list = [BAGS, CUPS]
      await tap('AA batteries')
      list = [BAGS, BATTERIES, CUPS]
      later()
    })

    it('is on the row, not a toast whose button shares the Bought column on a phone', () => {
      expect(button('AA batteries').text()).toBe('Undo')
      expect(ui.toasts[0].action).toBeNull()
    })

    it('puts the count back and the row back as it was, in its slot', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))

      await tap('AA batteries')

      expect(api.put).toHaveBeenCalledWith('/items/a', { quantity: 8 })
      expect(errors()).toEqual([])
      expect(lastToast().message).toContain('back to 8')
      expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
      expect(onHand('AA batteries')).toBe('8')
      expect(button('AA batteries').text()).toBe('Bought 4')
      expect(wrapper.find('.page-head .badge').text()).toBe('3 low')
    })

    it('the row shows the restored numbers even if the refresh fails', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))
      const realGet = api.get.getMockImplementation()
      api.get.mockImplementation(async (url) => {
        if (url === '/restock') throw new Error('offline')
        return realGet(url)
      })

      await tap('AA batteries')

      expect(onHand('AA batteries')).toBe('8')
      expect(button('AA batteries').text()).toBe('Bought 4')
    })

    it('a list fetched before the Undo landed cannot drop the row it just brought back', async () => {
      const stale = deferred()
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))
      list = [BAGS, CUPS]
      api.get.mockImplementationOnce(() => stale.promise)
      ui.dataChanged()
      await flushPromises()

      await tap('AA batteries')     // lands while that GET is still out
      expect(button('AA batteries').text()).toBe('Bought 4')

      list = [BAGS, BATTERIES, CUPS]
      stale.resolve({ items: [BAGS, CUPS] }) // from when it wasn't low
      await flushPromises()

      expect(slots()).toEqual(['Bags', 'AA batteries', 'Cups'])
    })

    it('a double-click on Undo does not buy it again', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))

      await tap('AA batteries')
      expect(button('AA batteries').text()).toBe('Bought 4')
      later(150)
      await tap('AA batteries')

      expect(api.post).toHaveBeenCalledTimes(1)
    })

    it('works again after a real pause: buy, undo, buy', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))
      await tap('AA batteries')
      later()
      list = [BAGS, CUPS]

      await tap('AA batteries')

      expect(api.post).toHaveBeenCalledTimes(2)
      expect(button('AA batteries').text()).toBe('Undo')
    })

    it('shows it is undoing and blocks a tap on the row meanwhile', async () => {
      item = { id: 'a', quantity: 12 }
      const put = deferred()
      api.put.mockImplementation(writes(put.promise))

      await tap('AA batteries')
      expect(button('AA batteries').text()).toBe('Undoing…')
      expect(button('AA batteries').attributes('aria-disabled')).toBe('true')
      later()
      await tap('AA batteries')
      expect(api.put).toHaveBeenCalledTimes(1)

      put.resolve({ id: 'a', quantity: 8 })
      await flushPromises()
      expect(button('AA batteries').text()).toBe('Bought 4')
      expect(button('AA batteries').attributes('aria-disabled')).toBe('false')
    })

    it('refuses when the count has moved since the tap, rather than overwrite it', async () => {
      item = { id: 'a', quantity: 11 }    // someone used one
      list = [BAGS, CUPS]
      const before = restockGets()

      await tap('AA batteries')

      expect(api.put).not.toHaveBeenCalled()
      expect(errors()).toHaveLength(1)
      expect(errors()[0]).toContain('AA batteries')
      expect(errors()[0]).toContain('now 11')
      // It wasn't undone and isn't low: nothing left for this page to offer.
      expect(restockGets()).toBeGreaterThan(before)
      expect(slots()).toEqual(['Bags', 'Cups'])
    })

    it('reports a failure when the PUT was ignored (several placements by now)', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockImplementation(writes({ id: 'a', quantity: 12 }))

      await tap('AA batteries')

      expect(api.put).toHaveBeenCalled()
      expect(errors()).toHaveLength(1)
      expect(errors()[0]).toContain('now 12')
      expect(ui.toasts.some((t) => t.message.includes('back to'))).toBe(false)
    })

    it('a 404 says it cannot be undone, not that the purchase is gone (it may just be vault-locked)', async () => {
      item = apiError(404, 'not found')
      list = [BAGS, CUPS]

      await tap('AA batteries')

      expect(api.put).not.toHaveBeenCalled()
      expect(errors()).toEqual([])
      expect(lastToast().type).toBe('info')
      expect(lastToast().message).toContain('can’t be undone')
      expect(slots()).toEqual(['Bags', 'Cups'])
    })

    it('treats a 404 from the PUT the same way', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockRejectedValue(apiError(404, 'not found'))
      list = [BAGS, CUPS]

      await tap('AA batteries')

      expect(errors()).toEqual([])
      expect(lastToast().message).toContain('can’t be undone')
      expect(slots()).toEqual(['Bags', 'Cups'])
    })

    it('any other failure keeps Undo on the row so it can be retried', async () => {
      item = { id: 'a', quantity: 12 }
      api.put.mockRejectedValue(apiError(500, 'HomeHoard hit an error. Try again.'))
      list = [BAGS, CUPS]         // it did not go through, so it's still not low
      const before = restockGets()

      await tap('AA batteries')

      expect(errors()).toEqual(['HomeHoard hit an error. Try again.'])
      expect(restockGets()).toBeGreaterThan(before)
      expect(button('AA batteries').text()).toBe('Undo')

      api.put.mockImplementation(writes({ id: 'a', quantity: 8 }))
      later()
      await tap('AA batteries')
      expect(lastToast().message).toContain('back to 8')
    })
  })
})
