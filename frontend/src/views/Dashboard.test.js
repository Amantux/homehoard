// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn() },
}))

const { api } = await import('../api')
const { LAST_VISIT } = await import('../storageKeys')
const { FIRST_VISIT_WATERMARK } = await import('../lastVisit')
const Dashboard = (await import('./Dashboard.vue')).default
const SinceVisitStrip = (await import('../components/SinceVisitStrip.vue')).default

const STATS = {
  totalItems: 3,
  totalLocations: 2,
  totalLabels: 1,
  totalWithWarranty: 1,
  totalItemPrice: 250,
}
const HA = {
  checkedOutItems: [],
  warrantiesExpiring: { days30: 0 },
  maintenance: { overdue: 0 },
  restock: { count: 0 },
}

const digest = (over = {}) => ({
  since: '2026-11-21T00:00:00+00:00',
  newItems: 2,
  checkoutsReturned: 0,
  warrantiesExpiring7: 0,
  maintenanceCompleted: 0,
  ...over,
})

function fakeStorage(initial = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] },
  }
}

describe('Dashboard since-visit digest', () => {
  let wrapper

  beforeEach(() => {
    vi.stubGlobal('localStorage', fakeStorage())
    api.get.mockImplementation(async (url) => {
      if (url === '/groups/statistics') return { ...STATS }
      if (url.startsWith('/items?')) return { items: [] }
      if (url === '/locations') return []
      if (url === '/ha/summary') return { ...HA }
      if (url === '/groups') return { currency: 'usd' }
      if (url === '/currency') return [{ code: 'usd', name: 'US Dollar', symbol: '$', local: 'en-US' }]
      if (url.startsWith('/changes?')) return digest()
      throw new Error('unexpected GET ' + url)
    })
    setActivePinia(createPinia())
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  async function mountDashboard() {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: Dashboard },
        { path: '/items', component: { template: '<div />' } },
        { path: '/checkouts', component: { template: '<div />' } },
        { path: '/report', component: { template: '<div />' } },
        { path: '/maintenance', component: { template: '<div />' } },
        { path: '/restock', component: { template: '<div />' } },
        { path: '/locations', component: { template: '<div />' } },
        { path: '/labels', component: { template: '<div />' } },
        { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
      ],
    })
    router.push('/')
    await router.isReady()
    wrapper = mount(Dashboard, { global: { plugins: [pinia, router] } })
    await flushPromises()
    return router
  }

  it('first visit hides the strip, seeds the watermark, and never calls /changes', async () => {
    await mountDashboard()
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/changes'))
    expect(wrapper.findComponent(SinceVisitStrip).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Since')
    expect(localStorage.getItem(LAST_VISIT)).toBe(FIRST_VISIT_WATERMARK)
  })

  it('returning visit renders the strip and advances the watermark', async () => {
    localStorage.setItem(LAST_VISIT, '2026-11-20T00:00:00Z')
    await mountDashboard()
    expect(api.get).toHaveBeenCalledWith(`/changes?since=${encodeURIComponent('2026-11-20T00:00:00Z')}`)
    expect(wrapper.findComponent(SinceVisitStrip).exists()).toBe(true)
    expect(wrapper.text()).toContain('Since')
    expect(localStorage.getItem(LAST_VISIT)).not.toBe('2026-11-20T00:00:00Z')
  })

  it('/changes failure leaves the watermark stale and renders no strip', async () => {
    localStorage.setItem(LAST_VISIT, '2026-11-20T00:00:00Z')
    api.get.mockImplementation(async (url) => {
      if (url.startsWith('/changes?')) throw new Error('network down')
      if (url === '/groups/statistics') return { ...STATS }
      if (url.startsWith('/items?')) return { items: [] }
      if (url === '/locations') return []
      if (url === '/ha/summary') return { ...HA }
      if (url === '/groups') return { currency: 'usd' }
      if (url === '/currency') return [{ code: 'usd', name: 'US Dollar', symbol: '$', local: 'en-US' }]
      throw new Error('unexpected GET ' + url)
    })
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    await mountDashboard()
    expect(wrapper.findComponent(SinceVisitStrip).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Since')
    expect(localStorage.getItem(LAST_VISIT)).toBe('2026-11-20T00:00:00Z')
    expect(errSpy).toHaveBeenCalled()
  })
})
