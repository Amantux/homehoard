// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  apiUrl: (path) => '/api/v1' + path,
  getToken: () => null,
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Report = (await import('./Report.vue')).default

// The GET /reports/inventory payload, in the shape the backend sends it: the
// summary's completeness block carries one {count, items} entry per key fact
// the report treats as the shape of a complete item.
const ITEMS = [
  { id: 'i1', name: 'NoValue', location: 'Garage', labels: ['Tools'], serialNumber: '', purchaseFrom: '',
    purchaseDate: '2026-01-05T00:00:00Z', purchasePrice: 0, quantity: 1, lineValue: 0, insured: false,
    warrantyStatus: 'active', imageId: 'd1',
    completeness: { value: false, photo: true, location: true, label: true, warrantyDate: true, purchaseDate: true } },
  { id: 'i2', name: 'NoPurchaseDate', location: 'Garage', labels: ['Tools'], serialNumber: '', purchaseFrom: '',
    purchaseDate: '', purchasePrice: 20, quantity: 1, lineValue: 20, insured: true,
    warrantyStatus: 'lifetime', imageId: 'd2',
    completeness: { value: true, photo: true, location: true, label: true, warrantyDate: true, purchaseDate: false } },
  { id: 'i3', name: 'Drill', location: 'Garage', labels: ['Tools'], serialNumber: '', purchaseFrom: '',
    purchaseDate: '2026-02-05T00:00:00Z', purchasePrice: 100, quantity: 1, lineValue: 100, insured: true,
    warrantyStatus: 'lifetime', imageId: 'd3',
    completeness: { value: true, photo: true, location: true, label: true, warrantyDate: true, purchaseDate: true } },
]

function makeReport() {
  const completeness = {
    value: { count: 0, items: [] }, photo: { count: 0, items: [] }, location: { count: 0, items: [] },
    label: { count: 0, items: [] }, warrantyDate: { count: 0, items: [] }, purchaseDate: { count: 0, items: [] },
  }
  for (const it of ITEMS) {
    for (const key of Object.keys(it.completeness)) {
      if (!it.completeness[key]) completeness[key].count += 1, completeness[key].items.push(it.id)
    }
  }
  return {
    generatedAt: '2026-11-22T10:00:00Z',
    currency: 'usd',
    summary: {
      totalItems: ITEMS.length,
      totalValue: 120,
      insuredValue: 120,
      uninsuredValue: 0,
      insuredCount: 2,
      warranty: { lifetime: 2, active: 0, expiring: 0, expired: 0, none: 0 },
      completeness,
    },
    byLocation: [],
    byLabel: [],
    items: ITEMS,
  }
}

describe('Report inventory report', () => {
  let wrapper

  async function mountReport() {
    const pinia = createPinia()
    setActivePinia(pinia)
    useUI()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/report', component: Report },
        { path: '/items', component: { render: () => null } },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push('/report')
    await router.isReady()
    const w = mount(Report, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    return w
  }

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.resetAllMocks()
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
    api.get.mockImplementation(async (url) =>
      url === '/reports/inventory' ? makeReport() : [])
  })
  afterEach(() => {
    wrapper?.unmount()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows the loading state while the report is in flight', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    wrapper = await mountReport()
    expect(wrapper.text()).toContain('Loading your inventory report')
  })

  it('shows the error state and can retry', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    wrapper = await mountReport()
    expect(wrapper.text()).toContain('Couldn’t load the report.')
    expect(wrapper.text()).toContain('boom')
    const retry = wrapper.findAll('button').find((b) => b.text().includes('Retry'))
    expect(retry).toBeTruthy()
    await retry.trigger('click')
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('shows the empty state when the group has no items', async () => {
    api.get.mockImplementation(async () => ({ summary: { totalItems: 0 } }))
    wrapper = await mountReport()
    expect(wrapper.text()).toContain('No items yet')
  })

  it('renders the missing-field counts from the report payload', async () => {
    wrapper = await mountReport()
    const text = wrapper.text()
    expect(text).toContain('Data completeness')
    expect(text).toContain('Missing value')
    expect(text).toContain('Missing purchase date')
    expect(text).toContain('1 missing')
  })

  it('links every missing gap to the item list filter', async () => {
    wrapper = await mountReport()
    const links = wrapper.findAllComponents({ name: 'RouterLink' })
    const gaps = []
    for (const l of links) {
      const to = l.props('to') || {}
      expect(to.path).toBe('/items')
      expect(to.query.missing).toBeTruthy()
      gaps.push(to.query.missing)
    }
    // The fixture has exactly two gaps with missing entries: an unvalued item and
    // one that never got a purchase date.
    expect(links.length).toBe(2)
    expect(gaps).toContain('value')
    expect(gaps).toContain('purchaseDate')
  })

  it('shows the all-complete state when nothing is missing', async () => {
    api.get.mockImplementation(async () => ({
      ...makeReport(),
      summary: { ...makeReport().summary, completeness: {
        value: { count: 0, items: [] }, photo: { count: 0, items: [] }, location: { count: 0, items: [] },
        label: { count: 0, items: [] }, warrantyDate: { count: 0, items: [] }, purchaseDate: { count: 0, items: [] },
      } },
    }))
    wrapper = await mountReport()
    expect(wrapper.text()).toContain('All key facts present')
  })
})
