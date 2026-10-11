// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api', () => ({
  api: { get: vi.fn(async () => ({})), post: vi.fn(async () => ({})) },
  setToken: vi.fn(),
}))

const { useAuth } = await import('../stores/auth')
const Login = (await import('./Login.vue')).default

describe('Login', () => {
  let wrapper
  let auth
  beforeEach(() => {
    setActivePinia(createPinia())
    auth = useAuth()
    auth.login = vi.fn(async () => {})
  })
  afterEach(() => wrapper?.unmount())

  async function mountAt(url) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div/>' } },
        { path: '/login', component: Login },
        { path: '/items/:id', component: { template: '<div/>' } },
      ],
    })
    router.push(url)
    await router.isReady()
    wrapper = mount(Login, { global: { plugins: [router] } })
    return router
  }
  async function fillAndSubmit() {
    await wrapper.get('input[type="email"]').setValue('me@example.com')
    await wrapper.get('input[type="password"]').setValue('hunter22')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
  }

  it('submit calls auth.login(email, password)', async () => {
    await mountAt('/login')
    await fillAndSubmit()
    expect(auth.login).toHaveBeenCalledWith('me@example.com', 'hunter22')
  })

  it('follows an in-app ?redirect=', async () => {
    const router = await mountAt('/login?redirect=/items/5')
    await fillAndSubmit()
    expect(router.currentRoute.value.fullPath).toBe('/items/5')
  })

  it('ignores an off-site ?redirect= and lands on /', async () => {
    const router = await mountAt('/login?redirect=https://evil.example')
    await fillAndSubmit()
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('shows a login rejection in the alert and keeps the email', async () => {
    const router = await mountAt('/login?redirect=/items/5')
    auth.login = vi.fn(async () => { throw new Error('Wrong email or password') })
    await fillAndSubmit()
    expect(wrapper.get('[role="alert"]').text()).toBe('Wrong email or password')
    expect(wrapper.get('input[type="email"]').element.value).toBe('me@example.com')
    expect(router.currentRoute.value.path).toBe('/login')
  })
})
