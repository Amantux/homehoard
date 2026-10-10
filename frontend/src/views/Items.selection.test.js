// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// A live-sync refresh (ui.dataChanged) refetches the same page. It must not
// wipe a bulk selection the user is in the middle of building (P47).
const ITEMS = [
  { id: 'a', name: 'Drill' },
  { id: 'b', name: 'Saw' },
  { id: 'c', name: 'Level' },
]

vi.mock('../api', () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url.startsWith('/items?')) return { items: ITEMS.map((i) => ({ ...i })), total: ITEMS.length }
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

describe('Items bulk selection', () => {
  let wrapper
  beforeEach(() => localStorage.clear())
  afterEach(() => wrapper?.unmount())

  it('keeps the selection across a live-data refresh', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/items', component: Items },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push('/items')
    await router.isReady()

    wrapper = mount(Items, {
      global: { plugins: [pinia, router], stubs: { ItemCard: true } },
      attachTo: document.body,
    })
    await flushPromises()
    expect(wrapper.findAll('input[aria-label^="Select "]').length).toBe(3)

    await wrapper.find('input[aria-label="Select Drill"]').setValue(true)
    await wrapper.find('input[aria-label="Select Level"]').setValue(true)
    expect(wrapper.find('.bulk-bar').text()).toContain('2 selected')

    const fetchesBefore = api.get.mock.calls.filter(([u]) => u.startsWith('/items?')).length
    useUI().dataChanged()
    await flushPromises()
    // The refresh really happened (so the test can't pass by doing nothing)...
    expect(api.get.mock.calls.filter(([u]) => u.startsWith('/items?')).length).toBe(fetchesBefore + 1)
    // ...and the selection survived it.
    expect(wrapper.find('.bulk-bar').exists()).toBe(true)
    expect(wrapper.find('.bulk-bar').text()).toContain('2 selected')
    expect(wrapper.find('input[aria-label="Select Drill"]').element.checked).toBe(true)
    expect(wrapper.find('input[aria-label="Select Saw"]').element.checked).toBe(false)
    expect(wrapper.find('input[aria-label="Select Level"]').element.checked).toBe(true)
  })
})
