// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { shortDate } from '../format'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  apiUrl: (path) => '/api/v1' + path,
  getToken: () => null,
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Report = (await import('./Report.vue')).default

// The GET /reports/inventory attention rows, in the shape the backend sends:
// one deduplicated, severity-ordered row per item needing attention, carrying
// the single worst reason's gap and its due date (null when there is none).
const ATTENTION = [
  { id: 'i1', name: 'Old Drill', severity: 'expired', reasons: ['warranty_expired'], gap: 'warranty expired on 2026-02-19', due: '2026-02-19T13:00:00+00:00' },
  { id: 'i2', name: 'Soon Drill', severity: 'expiring', reasons: ['warranty_expiring'], gap: 'warranty expires on 2026-03-31', due: '2026-03-31T13:00:00+00:00' },
]

const ITEMS = [
  { id: 'i1', name: 'Old Drill', location: 'Garage', labels: ['Tools'], serialNumber: '', purchaseFrom: '', purchaseDate: '2026-01-01T00:00:00Z', purchasePrice: 100, quantity: 1, lineValue: 100, insured: true, warrantyStatus: 'expired', imageId: null },
  { id: 'i2', name: 'Soon Drill', location: 'Garage', labels: ['Tools'], serialNumber: '', purchaseFrom: '', purchaseDate: '2026-01-01T00:00:00Z', purchasePrice: 25, quantity: 1, lineValue: 25, insured: false, warrantyStatus: 'expiring', imageId: null },
]

function makeReport(attention = ATTENTION) {
  return {
    generatedAt: '2026-11-22T10:00:00Z',
    currency: 'usd',
    summary: {
      totalItems: ITEMS.length,
      totalValue: 125,
      insuredValue: 100,
      uninsuredValue: 25,
      insuredCount: 1,
      warranty: { lifetime: 0, active: 0, expiring: 1, expired: 1, none: 0 },
      attention,
    },
    byLocation: [],
    byLabel: [],
    items: ITEMS,
  }
}

describe('Report inventory report', () => {
  let wrapper
  let attention = ATTENTION

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
      url === '/reports/inventory' ? makeReport(attention) : [])
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
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

  it('renders the ranked attention rows with severity chip, gap, due date and item link', async () => {
    wrapper = await mountReport()
    const text = wrapper.text()

    // Section heading.
    expect(text).toContain('Attention')
    // Ranked rows: item names.
    expect(text).toContain('Old Drill')
    expect(text).toContain('Soon Drill')

    // Severity chips per row (expired / expiring), through the shared wlabel.
    const chips = wrapper.findAll('span.chip').map((c) => c.text())
    expect(chips).toContain('Expired')
    expect(chips).toContain('Expiring soon')

    // The specific gap per row.
    expect(text).toContain('warranty expired on 2026-02-19')
    expect(text).toContain('warranty expires on 2026-03-31')

    // Due date per row, formatted through the shared shortDate helper.
    expect(text).toContain(shortDate('2026-02-19T13:00:00+00:00'))
    expect(text).toContain(shortDate('2026-03-31T13:00:00+00:00'))

    // One-click link to the item for each ranked row.
    const links = wrapper.findAllComponents({ name: 'RouterLink' })
    const targets = links.map((l) => l.props('to'))
    expect(targets).toContain('/items/i1')
    expect(targets).toContain('/items/i2')
  })

  it('shows the empty state when nothing needs attention', async () => {
    attention = []
    wrapper = await mountReport()
    expect(wrapper.text()).toContain('Nothing needs attention')
  })
})
