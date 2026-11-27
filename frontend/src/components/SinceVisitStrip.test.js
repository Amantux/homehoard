// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SinceVisitStrip from './SinceVisitStrip.vue'

const ROUTES = [
  { path: '/', component: { template: '<div />' } },
  { path: '/items', component: { template: '<div />' } },
  { path: '/checkouts', component: { template: '<div />' } },
  { path: '/report', component: { template: '<div />' } },
  { path: '/maintenance', component: { template: '<div />' } },
]

async function mountIt(digest) {
  const router = createRouter({ history: createMemoryHistory(), routes: ROUTES })
  router.push('/')
  await router.isReady()
  const w = mount(SinceVisitStrip, { props: { digest }, global: { plugins: [router] } })
  await flushPromises()
  return w
}

const zeroDigest = (over = {}) => ({
  since: '2026-11-20T00:00:00+00:00',
  newItems: 0,
  checkoutsReturned: 0,
  warrantiesExpiring7: 0,
  maintenanceCompleted: 0,
  ...over,
})

describe('SinceVisitStrip', () => {
  it('renders nothing on a first visit, when there is no digest', async () => {
    const w = await mountIt(null)
    expect(w.find('.card').exists()).toBe(false)
    expect(w.text()).toBe('')
  })

  it('renders nothing when the digest is undefined', async () => {
    const w = await mountIt(undefined)
    expect(w.find('.card').exists()).toBe(false)
    expect(w.text()).toBe('')
  })

  it('renders the neutral line when every count is zero', async () => {
    const w = await mountIt(zeroDigest())
    expect(w.find('.card').exists()).toBe(true)
    expect(w.text()).toContain('No changes since')
    expect(w.findAll('a').length).toBe(0)
  })

  it('renders one segment per non-zero category, each linking to its route', async () => {
    const w = await mountIt(zeroDigest({
      newItems: 3,
      checkoutsReturned: 1,
      warrantiesExpiring7: 2,
      maintenanceCompleted: 1,
    }))
    expect(w.find('.card').exists()).toBe(true)
    expect(w.text()).toContain('Since')
    expect(w.text()).toContain('3 new items')
    expect(w.text()).toContain('1 returned')
    expect(w.find('a[href*="/items"]').exists()).toBe(true)
    expect(w.find('a[href*="/checkouts"]').exists()).toBe(true)
    expect(w.find('a[href*="/report"]').exists()).toBe(true)
    expect(w.find('a[href*="/maintenance"]').exists()).toBe(true)
  })

  it('omits zero-count segments', async () => {
    const w = await mountIt(zeroDigest({ newItems: 2, checkoutsReturned: 0, warrantiesExpiring7: 0, maintenanceCompleted: 0 }))
    expect(w.text()).toContain('2 new items')
    expect(w.text()).not.toContain('returned')
    expect(w.text()).not.toContain('warrant')
    expect(w.findAll('a').length).toBe(1)
  })

  it('words the warranties segment with the 7-day window', async () => {
    const w = await mountIt(zeroDigest({ warrantiesExpiring7: 2 }))
    expect(w.text()).toContain('2 warranties expiring within 7 days')
  })
})
