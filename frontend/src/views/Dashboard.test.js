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
  // Minimal stand-in: the dashboard never touches toasts/confirm/session state,
  // and stubbing the store keeps the happy-dom env free of localStorage.
  useUI: () => ({ toasts: [], error: () => {}, dismiss: () => {}, toast: () => {} }),
}))

const { api } = await import('../api')
const Dashboard = (await import('./Dashboard.vue')).default

// Mirrors GET /api/v1/ha/summary for the pieces the briefing reads: overdue
// checkouts, warranties expiring within 30 days, overdue maintenance,
// low consumables.
function haSummary({ overdueLends = [], days30 = 0, maintOverdue = 0, restock = 0 } = {}) {
  return {
    checkedOutItems: overdueLends.map((name, i) => ({ id: 'c' + i, name, to: 'Garage', overdue: true })),
    warrantiesExpiring: { days30, days90: 0, items: [] },
    maintenance: { overdue: maintOverdue, upcoming30: 0, entries: [] },
    restock: { count: restock, items: [] },
  }
}

describe('Dashboard', () => {
  let wrapper, router

  beforeEach(async () => {
    vi.resetAllMocks()
    api.get.mockImplementation(async (url) => {
      if (url === '/groups/statistics') return { totalItems: 3, totalLocations: 2, totalLabels: 1, totalWithWarranty: 2, totalItemPrice: 100 }
      if (url === '/items?orderBy=createdAt&pageSize=6') return { items: [] }
      if (url === '/locations') return []
      if (url === '/ha/summary') return haSummary({ overdueLends: ['Drill'], days30: 2, maintOverdue: 1 })
      if (url === '/groups') return { currency: 'usd' }
      if (url === '/currency') return [{ code: 'usd', symbol: '$' }]
      throw new Error('Unexpected api.get: ' + url)
    })
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: Dashboard },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
    router.push('/')
    await router.isReady()
    wrapper = mount(Dashboard, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
  })

  afterEach(() => {
    wrapper.unmount()
    vi.clearAllMocks()
  })

  it('announces the attention digest via a polite live region', () => {
    const live = wrapper.find('[aria-live="polite"]')
    expect(live.exists()).toBe(true)
    expect(live.attributes('aria-live')).toBe('polite')
    // Visually hidden, but announced: the digest summary itself.
    expect(live.classes()).toContain('visually-hidden')
    // 1 overdue lend + 2 warranties expiring + 1 maintenance overdue.
    expect(live.text()).toBe('Attention digest: 4 items need attention')
  })

  it('renders a plain-language severity label next to every colored attention badge', () => {
    const badges = wrapper.findAll('.badge')
    const texts = badges.map((b) => b.text())
    // Overdue checkout lend: badge reads "1 Overdue"; warranty expiring: "Expiring soon".
    expect(texts).toContain('1 Overdue')
    expect(texts).toContain('Expiring soon')
    // Colored chips never render bare — each carries a visible plain-language label.
    for (const t of texts) {
      expect(t.trim().length).toBeGreaterThan(0)
      expect(t).not.toMatch(/^\d+$/)
    }
  })
})
