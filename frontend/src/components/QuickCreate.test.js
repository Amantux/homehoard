// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => {
  class ApiError extends Error {
    constructor({ status, message, fields = {}, requestId = null }) {
      super(message)
      this.name = 'ApiError'
      this.status = status
      this.fields = fields
      this.requestId = requestId
    }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(async () => []),
      post: vi.fn(async () => ({ id: 'new1' })),
      upload: vi.fn(async () => ({})),
    },
  }
})

const { api, ApiError } = await import('../api')
const QuickCreate = (await import('./QuickCreate.vue')).default

describe('QuickCreate', () => {
  let wrapper
  beforeEach(() => {
    setActivePinia(createPinia())
    api.get.mockClear()
    api.post.mockClear()
    api.get.mockImplementation(async () => [])
    api.post.mockImplementation(async () => ({ id: 'new1' }))
  })
  afterEach(() => wrapper?.unmount())

  async function mountIt() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/items/:id', component: { template: '<div/>' } },
      ],
    })
    router.push('/')
    await router.isReady()
    wrapper = mount(QuickCreate, { global: { plugins: [router] }, attachTo: document.body })
    await flushPromises()
    return router
  }
  const nameInput = () => wrapper.get('input[aria-label="Name"]')
  const createBtn = () => wrapper.findAll('button').find((b) => /^Create item/.test(b.text()))

  it('an empty name cannot be submitted: button disabled, Enter posts nothing', async () => {
    await mountIt()
    expect(createBtn().attributes('disabled')).toBeDefined()
    await nameInput().trigger('keyup', { key: 'Enter' })
    await flushPromises()
    expect(api.post).not.toHaveBeenCalled()
    expect(wrapper.emitted('created')).toBeUndefined()
  })

  it('submits a valid item to /items with name + quantity and emits created', async () => {
    const router = await mountIt()
    await nameInput().setValue('Cordless drill')
    await wrapper.get('input[type="number"]').setValue('3')
    await createBtn().trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(1)
    const [url, body] = api.post.mock.calls[0]
    expect(url).toBe('/items')
    expect(body.name).toBe('Cordless drill')
    expect(body.quantity).toBe(3)
    expect(wrapper.emitted('created')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(router.currentRoute.value.path).toBe('/items/new1')
  })

  it('maps an ApiError with fields onto the field error beside the input', async () => {
    await mountIt()
    api.post.mockImplementationOnce(async () => {
      throw new ApiError({ status: 422, message: 'Invalid', fields: { name: 'Name is already taken' } })
    })
    await nameInput().setValue('Cordless drill')
    await createBtn().trigger('click')
    await flushPromises()

    const err = wrapper.get('.field-error')
    expect(err.text()).toBe('Name is already taken')
    expect(err.attributes('role')).toBe('alert')
    expect(nameInput().attributes('aria-invalid')).toBe('true')
    expect(wrapper.emitted('created')).toBeUndefined()
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
