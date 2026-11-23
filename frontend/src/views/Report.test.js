// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  apiUrl: vi.fn(),
  getToken: vi.fn(),
}))

vi.mock('../stores/ui', () => ({
  // Minimal stand-in: the report never touches toasts/confirm/session state,
  // and stubbing the store keeps the happy-dom env free of localStorage.
  useUI: () => ({ toasts: [], error: () => {}, dismiss: () => {}, toast: () => {} }),
}))

const { api } = await import('../api')
const Report = (await import('./Report.vue')).default

// Mirrors GET /api/v1/reports/inventory for the pieces the report view renders:
// the warranty summary counts plus the per-item warranty statuses.
function inventoryReport({ warranty = {}, items = [] } = {}) {
  const rows = items.length
    ? items
    : [
        { id: '1', name: 'Drill', location: '', labels: [], serialNumber: '', purchaseFrom: '', purchaseDate: null, purchasePrice: 100, quantity: 1, lineValue: 100, insured: true, warrantyStatus: 'active', imageId: null },
        { id: '2', name: 'Ladder', location: '', labels: [], serialNumber: '', purchaseFrom: '', purchaseDate: null, purchasePrice: 50, quantity: 2, lineValue: 100, insured: false, warrantyStatus: 'expiring', imageId: null },
      ]
  const counts = { lifetime: 0, active: 0, expiring: 0, expired: 0, none: 0 }
  for (const it of rows) counts[it.warrantyStatus] = (counts[it.warrantyStatus] || 0) + 1
  const totalValue = rows.reduce((a, i) => a + (Number(i.lineValue) || 0), 0)
  const insuredValue = rows.reduce((a, i) => a + (i.insured ? Number(i.lineValue) || 0 : 0), 0)
  return {
    generatedAt: new Date().toISOString(),
    currency: 'usd',
    summary: {
      totalItems: rows.length,
      totalValue,
      insuredValue,
      uninsuredValue: totalValue - insuredValue,
      insuredCount: rows.filter((i) => i.insured).length,
      warranty: { ...counts, ...warranty },
    },
    byLocation: [],
    byLabel: [],
    items: rows,
  }
}

describe('Report', () => {
  let wrapper, router

  beforeEach(async () => {
    vi.resetAllMocks()
    api.get.mockImplementation(async (url) => {
      if (url === '/reports/inventory') return inventoryReport({ warranty: { lifetime: 0, active: 1, expiring: 1, expired: 0, none: 0 } })
      throw new Error('Unexpected api.get: ' + url)
    })
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: Report },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push('/')
    await router.isReady()
    wrapper = mount(Report, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
  })

  afterEach(() => {
    wrapper.unmount()
    vi.clearAllMocks()
  })

  it('announces the report’s overall completeness / severity via a polite live region', () => {
    const live = wrapper.find('[aria-live="polite"]')
    expect(live.exists()).toBe(true)
    expect(live.attributes('aria-live')).toBe('polite')
    // Visually hidden, but announced: the report’s overall severity summary.
    expect(live.classes()).toContain('visually-hidden')
    // 1 warranty expiring soon out of 2 total warranties.
    expect(live.text()).toBe('Inventory report: 1 warranty needs attention')
  })

  it('renders a visible plain-language severity label on every colored status chip', () => {
    const chips = wrapper.findAll('.chip')
    const texts = chips.map((c) => c.text().trim())
    // The covered aggregate keeps its plain-language word; the status chips
    // read the shared util’s plain-language label, e.g. "1 Expiring soon".
    expect(texts.join(' ')).toContain('covered')
    expect(texts).toContain('1 Expiring soon')
    expect(texts).toContain('0 Expired')
    expect(texts).toContain('0 None')
  })

  it('renders each item’s warranty status as a visible plain-language label', () => {
    const statuses = wrapper.findAll('tbody tr td span').map((s) => s.text().trim())
    expect(statuses).toContain('Active')
    expect(statuses).toContain('Expiring soon')
  })
})
