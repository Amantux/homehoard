// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}))

const { api } = await import('../api')
const Dashboard = (await import('./Dashboard.vue')).default

// The /ha/summary attention payload: one overdue lend, one expiring warranty,
// one overdue maintenance entry and one running-low consumable — the same
// alerts the notifier digest carries per-entry deep links for.
let payload = {
  checkedOutItems: [{ id: 12, name: 'Ladder', to: 'Bob', overdue: true }],
  warrantiesExpiring: { days30: 1, days90: 1, items: [{ id: 7, name: 'Router', expires: '2026-12-01' }] },
  maintenance: { overdue: 1, upcoming30: 0, entries: [{ id: 9, itemId: 5, name: 'Oil change', overdue: true }] },
  restock: { count: 1, items: [{ id: 21, name: 'Bags', onHand: 1, suggestedQuantity: 6, oneTap: true }] },
}

const stats = { totalItems: 1, totalLocations: 0, totalLabels: 0, totalWithWarranty: 0, totalItemPrice: 0 }

function mockSummary() {
  api.get.mockImplementation(async (url) => {
    if (url === '/groups/statistics') return stats
    if (url === '/items?orderBy=createdAt&pageSize=6') return { items: [] }
    if (url === '/locations') return []
    if (url === '/ha/summary') return payload
    if (url === '/groups') return { currency: 'USD' }
    if (url === '/currency') return [{ code: 'USD', symbol: '$' }]
    throw new Error('Unexpected GET ' + url)
  })
}

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Dashboard },
      { path: '/items/:id', component: { render: () => null } },
      { path: '/checkouts', component: { render: () => null } },
      { path: '/maintenance', component: { render: () => null } },
      { path: '/restock', component: { render: () => null } },
      { path: '/report', component: { render: () => null } },
      { path: '/:pathMatch(.*)*', component: { render: () => null } },
    ],
  })
  router.push('/')
  await router.isReady()
  const wrapper = mount(Dashboard, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Dashboard attention strip', () => {
  let wrapper, router

  beforeEach(async () => {
    vi.resetAllMocks()
    // Node >= 22 keeps `localStorage` behind a flag; the happy-dom window has
    // one, so stub the global the pinia store reads before mounting.
    vi.stubGlobal('localStorage', {
      getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
    })
    mockSummary()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    wrapper?.unmount()
  })

  it('renders each attention row as a link to the per-entry record', async () => {
    ;({ wrapper, router } = await mountView())

    // Overdue lend -> the item that is still out.
    expect(wrapper.find('a[href="/items/12"]').exists()).toBe(true)
    // Expiring warranty -> the item whose warranty is running out.
    expect(wrapper.find('a[href="/items/7"]').exists()).toBe(true)
    // Overdue maintenance -> the item the job is for.
    expect(wrapper.find('a[href="/items/5"]').exists()).toBe(true)
    // Running-low consumable -> the item to buy.
    expect(wrapper.find('a[href="/items/21"]').exists()).toBe(true)
  })

  it('deep-links the overdue-checkout row at the lent item and routes there', async () => {
    ;({ wrapper, router } = await mountView())

    const link = wrapper.find('a[href="/items/12"]')
    expect(link.text()).toContain('Ladder')
    await link.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/items/12')
  })

  it('falls back to the section-level route when there is no entry to deep-link', async () => {
    payload.checkedOutItems = [{ name: 'Mystery', overdue: true }]
    ;({ wrapper, router } = await mountView())

    expect(wrapper.find('a[href="/checkouts"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/items/12"]').exists()).toBe(false)
  })

  it('renders no attention card when nothing needs attention', async () => {
    payload.checkedOutItems = []
    payload.warrantiesExpiring = { days30: 0, days90: 0, items: [] }
    payload.maintenance = { overdue: 0, upcoming30: 0, entries: [] }
    payload.restock = { count: 0, items: [] }
    ;({ wrapper, router } = await mountView())

    expect(wrapper.text()).not.toContain('Needs attention')
  })
})
