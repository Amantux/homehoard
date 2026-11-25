// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// ?missing=<gap> arrives from a Report completeness-card link. The view has to
// read it off the route, hand it to the list API, and surface the active filter
// with a visible way out (clear).
const ITEMS = [
  { id: 'a', name: 'NoValue' },
  { id: 'b', name: 'Drill' },
]

vi.mock('../api', () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url.startsWith('/items?')) return { items: ITEMS, total: ITEMS.length }
      if (url === '/vault/status') return { configured: false, locked: true, hiddenCount: 0 }
      return []
    }),
    post: vi.fn(async () => ({})),
    patch: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
  },
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Items = (await import('./Items.vue')).default

describe('Items missing-field filter', () => {
  let wrapper
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {}, clear() {} })
  })
  afterEach(() => {
    wrapper?.unmount()
    vi.unstubAllGlobals()
  })

  async function mountItems(path) {
    const pinia = createPinia()
    setActivePinia(pinia)
    useUI()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/items', component: Items },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push(path)
    await router.isReady()
    wrapper = mount(Items, {
      global: { plugins: [pinia, router], stubs: { ItemCard: true } },
      attachTo: document.body,
    })
    await flushPromises()
    return wrapper
  }

  it('asks the list API for the gap named by ?missing=', async () => {
    await mountItems('/items?missing=value')
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('missing=value'))
  })

  it('shows the active gap filter and offers a visible clear control', async () => {
    await mountItems('/items?missing=value')
    expect(wrapper.text()).toContain('Missing value')
    const clear = wrapper.findAll('button').find((b) => b.text().includes('Clear filters'))
    expect(clear).toBeTruthy()
  })

  it('clears the gap filter', async () => {
    await mountItems('/items?missing=value')
    const clear = wrapper.findAll('button').find((b) => b.text().includes('Clear filters'))
    await clear.trigger('click')
    await flushPromises()
    expect(wrapper.find('.chip').exists()).toBe(false)
  })
})
