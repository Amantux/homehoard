// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock the API
vi.mock('../api', () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === '/qr-tags') {
        return [
          { id: 1, kind: 'item', source: 'generated', target: { name: 'Test Item' }, description: 'A test item', assetId: 'ITEM-001', shortCode: 'SC001', token: 'abc123' },
          { id: 2, kind: 'bin', source: 'generated', target: { name: 'Test Bin' }, description: null, token: 'def456' },
          { id: 3, kind: 'location', source: 'generated', target: { name: 'Test Location' }, description: null, token: 'ghi789' },
          { id: 4, kind: 'item', source: 'external', target: { name: 'External Code' }, description: null, token: 'xyz999' },
        ]
      }
      return []
    }),
  },
}))

const { api } = await import('../api')
const { useUI } = await import('../stores/ui')
const LabelSheet = (await import('./LabelSheet.vue')).default

describe('LabelSheet', () => {
  let wrapper
  let pinia
  let router

  beforeEach(() => {
    localStorage.clear()
    pinia = createPinia()
    setActivePinia(pinia)
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/labels', component: LabelSheet },
        { path: '/:rest(.*)*', component: { render: () => null } },
      ],
    })
  })

  it('renders default layout (address-3up) on mount', async () => {
    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Check that the default layout is selected
    const layoutRadios = wrapper.findAll('input[type="radio"]')
    expect(layoutRadios.length).toBeGreaterThan(0)
    const defaultRadio = layoutRadios.find((r) => r.element.value === 'address-3up')
    expect(defaultRadio.element.checked).toBe(true)

    // Check layout description text
    const descText = wrapper.find('p.muted').text()
    expect(descText).toContain('63.5')
    expect(descText).toContain('38.1')
    expect(descText).toContain('3')
  })

  it('switching layout updates applied CSS', async () => {
    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Switch to small-4up layout
    const smallRadio = wrapper.find('input[type="radio"][value="small-4up"]')
    await smallRadio.setValue()

    // Check that the layout description updated
    const descText = wrapper.find('p.muted').text()
    expect(descText).toContain('50.8')
    expect(descText).toContain('25.4')
    expect(descText).toContain('4')
  })

  it('shows extra text for layouts that support it', async () => {
    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Select large-2up layout (has showExtraText: true)
    const largeRadio = wrapper.find('input[type="radio"][value="large-2up"]')
    await largeRadio.setValue()

    // Check that extra text info is shown
    const extraTextInfo = wrapper.find('.stack:has(input[type="checkbox"])')
    expect(extraTextInfo.exists()).toBe(true)
    expect(extraTextInfo.text()).toContain('Extra text')
  })

  it('hides extra text toggle for layouts that do not support it', async () => {
    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Select address-3up layout (has showExtraText: false)
    const defaultRadio = wrapper.find('input[type="radio"][value="address-3up"]')
    await defaultRadio.setValue()

    // Check that extra text toggle is not shown
    const extraTextInfo = wrapper.find('.stack:has(input[type="checkbox"])')
    expect(extraTextInfo.exists()).toBe(false)
  })

  it('persists layout selection in localStorage', async () => {
    // Set a layout in localStorage
    localStorage.setItem('homehoard-label-layout', 'small-4up')

    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Check that the layout from localStorage is selected
    const smallRadio = wrapper.find('input[type="radio"][value="small-4up"]')
    expect(smallRadio.element.checked).toBe(true)
  })

  it('shows asset code as extra text for items', async () => {
    router.push('/labels')
    await router.isReady()
    wrapper = mount(LabelSheet, {
      global: { plugins: [pinia, router] },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 100))

    // Select large-2up layout (has showExtraText: true)
    const largeRadio = wrapper.find('input[type="radio"][value="large-2up"]')
    await largeRadio.setValue()

    // Select the item tag
    const itemCheckbox = wrapper.find('input[type="checkbox"][value="1"]')
    if (itemCheckbox) {
      await itemCheckbox.setValue(true)
    }

    // Check that asset code is shown
    const assetText = wrapper.find('.label-asset')
    expect(assetText.exists()).toBe(true)
    expect(assetText.text()).toContain('ITEM-001')
  })
})
