// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../api', () => ({
  api: { getReports: vi.fn(), getReport: vi.fn() },
  apiUrl: (p) => '/api/v1' + p,
  getToken: () => 'tok',
}))

const { api } = await import('../api')
const Report = (await import('./Report.vue')).default

// Mirrors the backend registry's inventory payload (GET /api/v1/reports/inventory):
// the shared envelope (generatedAt + currency) plus the valuation shape.
const INVENTORY = {
  generatedAt: '2026-01-01T00:00:00Z',
  currency: 'usd',
  summary: {
    totalItems: 1, totalValue: 100, insuredValue: 100, uninsuredValue: 0, insuredCount: 1,
    warranty: { lifetime: 0, active: 1, expiring: 0, expired: 0, none: 0 },
  },
  byLocation: [],
  byLabel: [],
  items: [
    {
      id: 'i1', name: 'Drill', location: 'Garage', labels: [], serialNumber: '',
      purchaseFrom: '', purchaseDate: '2025-01-01', purchasePrice: 100, quantity: 1,
      lineValue: 100, insured: true, warrantyStatus: 'active', imageId: null,
    },
  ],
}

// A narrower registry payload (attention digest): no valuation shape, so it takes
// the "no printable layout yet" branch instead of the inventory template.
const DIGEST = { generatedAt: '2026-01-01T00:00:00Z', currency: 'usd', isEmpty: false, counts: {} }

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/reports/:id', component: Report },
      { path: '/report', component: Report },
      { path: '/reports', component: { template: '<div/>' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div/>' } },
    ],
  })
}

async function mountReport(path = '/reports/inventory') {
  const router = makeRouter()
  router.push(path)
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Report, { global: { plugins: [router, pinia] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Report (registry-driven)', () => {
  let wrapper

  beforeEach(() => {
    vi.resetAllMocks()
    setActivePinia(createPinia())
    api.getReport.mockResolvedValue(INVENTORY)
    wrapper = undefined
  })
  afterEach(() => { wrapper?.unmount(); vi.clearAllMocks(); vi.unstubAllGlobals() })

  it('loads the chosen registered report through the shared loader', async () => {
    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    expect(api.getReport).toHaveBeenCalledTimes(1)
    expect(api.getReport).toHaveBeenCalledWith('inventory')
    expect(wrapper.text()).toContain('Drill')
    expect(wrapper.text()).toContain('Total value')
  })

  it('defaults to the household inventory when no id is in the route', async () => {
    const { wrapper: w } = await mountReport('/report')
    wrapper = w
    expect(api.getReport).toHaveBeenCalledWith('inventory')
  })

  it('renders the valuation layout for an inventory-shaped payload', async () => {
    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    expect(wrapper.text()).toContain('Inventory report')
    expect(wrapper.text()).toContain('Insured (1 items)')
    expect(wrapper.text()).toContain('Warranty:')
  })

  it('shows the empty state when the report has no items', async () => {
    api.getReport.mockResolvedValue({
      ...INVENTORY,
      summary: { ...INVENTORY.summary, totalItems: 0, totalValue: 0, insuredValue: 0, uninsuredValue: 0, insuredCount: 0 },
    })
    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    expect(wrapper.text()).toContain('No items yet')
  })

  it('renders the fallback for a registered report without a printable layout', async () => {
    api.getReport.mockResolvedValue(DIGEST)
    const { wrapper: w } = await mountReport('/reports/attention')
    wrapper = w
    expect(api.getReport).toHaveBeenCalledWith('attention')
    expect(wrapper.text()).toContain('This report has no printable layout yet.')
  })

  it('renders the item data-completeness report through the shared loader', async () => {
    const COMPLETENESS = {
      generatedAt: '2026-01-01T00:00:00Z', currency: 'usd',
      summary: { totalItems: 1, missing: { hasValue: 1, hasPhoto: 0, hasLocation: 0, hasLabel: 0, hasWarranty: 1, hasPurchaseDate: 0 } },
      fields: [],
      items: [],
    }
    api.getReport.mockResolvedValue(COMPLETENESS)
    const { wrapper: w } = await mountReport('/reports/completeness')
    wrapper = w
    expect(api.getReport).toHaveBeenCalledWith('completeness')
    expect(wrapper.text()).toContain('This report has no printable layout yet.')
  })

  it('renders the stale items report through the shared loader', async () => {
    const STALE = {
      generatedAt: '2026-01-01T00:00:00Z', currency: 'usd',
      summary: { totalItems: 1, staleCount: 1, warranty: { lifetime: 0, active: 0, expiring: 0, expired: 1, none: 0 } },
      items: [],
    }
    api.getReport.mockResolvedValue(STALE)
    const { wrapper: w } = await mountReport('/reports/stale')
    wrapper = w
    expect(api.getReport).toHaveBeenCalledWith('stale')
    expect(wrapper.text()).toContain('This report has no printable layout yet.')
  })

  it('shows the error state and retries through the shared loader', async () => {
    api.getReport.mockRejectedValue(new Error('Could not load the report.'))
    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    expect(wrapper.text()).toContain('Could not load the report.')
    const retry = wrapper.findAll('button').find((b) => b.text() === 'Retry')
    expect(retry, 'the error state offers a retry').toBeTruthy()
    await retry.trigger('click')
    await flushPromises()
    expect(api.getReport).toHaveBeenCalledTimes(2)
  })

  it('exports the CSV through the shared helper for the loaded report', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      blob: async () => new Blob(['name,value']),
      headers: { get: () => 'attachment; filename="homehoard-inventory-report.csv"' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const clickSpy = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(clickSpy)

    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    const csv = wrapper.findAll('button').find((b) => b.text().includes('CSV'))
    expect(csv, 'the report offers a CSV export').toBeTruthy()
    await csv.trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/reports/inventory.csv', { headers: { Authorization: 'tok' } })
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })

  it('surfaces the CSV error through the ui error toast', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 500, blob: async () => new Blob([]), headers: { get: () => '' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { wrapper: w } = await mountReport('/reports/inventory')
    wrapper = w
    const { useUI } = await import('../stores/ui')
    const ui = useUI()
    const errorSpy = vi.spyOn(ui, 'error').mockImplementation(() => {})
    const csv = wrapper.findAll('button').find((b) => b.text().includes('CSV'))
    await csv.trigger('click')
    await flushPromises()
    expect(errorSpy).toHaveBeenCalledWith('Could not download the CSV.')
  })
})
