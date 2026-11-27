// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { getReports: vi.fn(), getReport: vi.fn() },
}))

const { api } = await import('../api')
const Reports = (await import('./Reports.vue')).default

// Mirrors GET /api/v1/reports: one {id, title} entry per registered report.
const LIST = [
  { id: 'inventory', title: 'Inventory valuation & insurance summary' },
  { id: 'attention', title: 'Attention digest' },
  { id: 'completeness', title: 'Item data-completeness' },
  { id: 'stale', title: 'Expiring & stale items' },
]

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/reports', component: Reports },
      { path: '/reports/:id', component: { template: '<div/>' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div/>' } },
    ],
  })
}

async function mountReports() {
  const router = makeRouter()
  router.push('/reports')
  await router.isReady()
  const wrapper = mount(Reports, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('Reports index', () => {
  let wrapper
  let router

  beforeEach(() => { vi.resetAllMocks() })
  afterEach(() => { wrapper?.unmount(); vi.clearAllMocks() })

  it('loads the registered reports from GET /reports', async () => {
    api.getReports.mockResolvedValue(LIST)
    ;({ wrapper, router } = await mountReports())
    expect(api.getReports).toHaveBeenCalledTimes(1)
  })

  it('lists the registered reports from the backend registry', async () => {
    api.getReports.mockResolvedValue(LIST)
    ;({ wrapper, router } = await mountReports())
    expect(wrapper.find('.page-head h1').text()).toBe('Reports')
    // One badge entry per registered report.
    expect(wrapper.find('.page-head .badge').text()).toBe('4')
    expect(wrapper.text()).toContain('Inventory valuation & insurance summary')
    expect(wrapper.text()).toContain('Attention digest')
    expect(wrapper.text()).toContain('Item data-completeness')
    expect(wrapper.text()).toContain('Expiring & stale items')
  })

  it('hands off to the single report route when a report is opened', async () => {
    api.getReports.mockResolvedValue(LIST)
    ;({ wrapper, router } = await mountReports())
    const open = wrapper.findAll('button').find((b) => b.text() === 'Open report')
    expect(open, 'an Open report button is rendered').toBeTruthy()
    await open.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/reports/inventory')
  })

  it('shows the empty state when the registry lists no reports', async () => {
    api.getReports.mockResolvedValue([])
    ;({ wrapper, router } = await mountReports())
    expect(wrapper.find('.empty-state').exists()).toBe(true)
    expect(wrapper.find('.empty-state h3').text()).toBe('No reports registered')
  })

  it('shows the error state and retries', async () => {
    api.getReports.mockRejectedValue(new Error('Could not load the reports.'))
    ;({ wrapper, router } = await mountReports())
    const alert = wrapper.find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('Could not load the reports.')
    const retry = wrapper.findAll('button').find((b) => b.text() === 'Try again')
    expect(retry, 'the error state offers a retry').toBeTruthy()
    await retry.trigger('click')
    await flushPromises()
    expect(api.getReports).toHaveBeenCalledTimes(2)
  })
})
