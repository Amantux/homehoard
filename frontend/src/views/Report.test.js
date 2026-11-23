// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  apiUrl: (p) => '/api/v1' + p,
  getToken: () => null,
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Report = (await import('./Report.vue')).default

// GET /reports/inventory answers an item row carrying the ReportRow contract
// (item_ref/title/status_label/status_tone/reason/action_url) plus the
// valuation keys the report itself prints.
const ROW = {
  id: 'i1',
  item_ref: 'item:i1',
  title: 'Drill',
  status_label: 'Expired',
  status_tone: 'bad',
  reason: 'Warranty expired 2026-08-01.',
  action_url: '/#/items/i1',
  location: 'Garage',
  serialNumber: '',
  purchaseDate: '2026-01-01T00:00:00',
  purchasePrice: 100,
  quantity: 1,
  lineValue: 100,
  insured: true,
}

const REPORT = {
  generatedAt: '2026-11-23T08:00:00Z',
  currency: 'usd',
  summary: {
    totalItems: 1,
    totalValue: 100,
    insuredValue: 100,
    uninsuredValue: 0,
    insuredCount: 1,
    warranty: { lifetime: 0, active: 0, expiring: 0, expired: 1, none: 0 },
  },
  byLocation: [],
  byLabel: [],
  items: [ROW],
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/report', component: Report },
      { path: '/items', component: { render: () => null } },
      { path: '/:rest(.*)*', component: { render: () => null } },
    ],
  })
}

describe('Report view', () => {
  let wrapper, router

  beforeEach(async () => {
    vi.resetAllMocks()
    // happy-dom in this environment exposes no localStorage; the UI store reads
    // it while creating its state, so give it a minimal stand-in.
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} })
    const pinia = createPinia()
    setActivePinia(pinia)
    useUI()
    api.get.mockImplementation(async (url) => (url === '/reports/inventory' ? REPORT : {}))
    router = makeRouter()
    router.push('/report')
    await router.isReady()
    wrapper = mount(Report, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('renders each item row from the ReportRow fields', async () => {
    const row = wrapper.findAll('tbody tr').find((r) => r.text().includes('Drill'))
    expect(row).toBeTruthy()
    expect(row.text()).toContain('Expired')
    expect(row.text()).toContain('Warranty expired 2026-08-01.')
  })

  it('reads the status label and tone from the row, not a per-surface map', async () => {
    const badge = wrapper.find('tbody .badge')
    expect(badge.text()).toBe('Expired')
    expect(badge.classes()).toContain('badge')
    expect(badge.classes()).toContain('bad')
  })

  it('links the row through its action_url instead of building a path', async () => {
    const link = wrapper.find('tbody a')
    expect(link.attributes('href')).toBe('/#/items/i1')
  })
})
