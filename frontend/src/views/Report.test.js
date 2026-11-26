// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  apiUrl: (p) => `/api/v1${p}`,
  getToken: () => null,
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const Report = (await import('./Report.vue')).default

// happy-dom in this runtime ships no localStorage unless pointed at a file; the
// ui store reads it while the pinia state is created, so give the tests a working
// in-memory one.
function memoryStorage() {
  const store = new Map()
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => void store.set(k, String(v)),
    removeItem: (k) => void store.delete(k),
    clear: () => void store.clear(),
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size
    },
  }
}

const ITEM_BASE = {
  id: '7',
  name: 'Drill',
  location: 'Garage',
  labels: [],
  serialNumber: '',
  purchaseFrom: '',
  purchaseDate: null,
  purchasePrice: 100,
  quantity: 1,
  lineValue: 100,
  insured: true,
  warrantyStatus: 'active',
  imageId: null,
  // The shared core row fields ride along on the report's adapter row too.
  title: 'Drill',
  group_id: 'g1',
  timestamp: '2026-11-20',
  summary: 'Covered until 2026-12-20.',
  status: 'active',
  action_url: '/#/items/7',
}

function item(over = {}) {
  return { ...ITEM_BASE, ...over }
}

function report(items) {
  return {
    generatedAt: '2026-11-26T10:00:00+00:00',
    currency: 'usd',
    summary: {
      totalItems: items.length,
      totalValue: 100,
      insuredValue: 100,
      uninsuredValue: 0,
      insuredCount: 1,
      warranty: { lifetime: 0, active: 1, expiring: 0, expired: 0, none: 0 },
    },
    byLocation: [],
    byLabel: [],
    items,
  }
}

function mountReport(payload) {
  api.get.mockImplementation(async (url) => {
    if (url === '/reports/inventory') return payload
    throw new Error(`unexpected GET ${url}`)
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  const ui = useUI()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/report', component: Report },
      { path: '/:rest(.*)*', component: { render: () => null } },
    ],
  })
  router.push('/report')
  const wrapper = mount(Report, { global: { plugins: [pinia, router] }, attachTo: document.body })
  return { wrapper, ui, router }
}

describe('Report view (the report renderer)', () => {
  let wrapper
  let ui

  beforeEach(async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.resetAllMocks()
    vi.stubGlobal('localStorage', memoryStorage())
    const mounted = mountReport(report([item()]))
    wrapper = mounted.wrapper
    ui = mounted.ui
    await flushPromises()
  })

  afterEach(() => {
    wrapper.unmount()
    ui.toasts.slice().forEach((t) => ui.dismiss(t.id))
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders the report rows from the adapter payload', async () => {
    await flushPromises()
    expect(wrapper.text()).toContain('Drill')
    expect(wrapper.text()).toContain('Garage')
    expect(wrapper.text()).toContain('Inventory report')
  })

  it('hands each row the quirks bag through to the renderer, verbatim, and defaults it to null', async () => {
    const payload = report([
      item({ id: '7', quirks: { to: 'Mom', note: { private: true } } }),
      item({ id: '8', name: 'Ladder', quirks: null }),
    ])
    const mounted = mountReport(payload)
    wrapper = mounted.wrapper
    await flushPromises()

    const rows = wrapper.vm.items
    expect(rows).toHaveLength(2)
    expect(rows[0].quirks).toEqual({ to: 'Mom', note: { private: true } })
    expect(rows[1].quirks).toBeNull()
  })
})
