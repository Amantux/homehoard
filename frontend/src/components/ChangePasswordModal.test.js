// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

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
    setToken: vi.fn(),
    api: { put: vi.fn(async () => ({ token: 'Bearer fresh' })) },
  }
})

const { api, setToken, ApiError } = await import('../api')
const ChangePasswordModal = (await import('./ChangePasswordModal.vue')).default

describe('ChangePasswordModal', () => {
  let wrapper
  beforeEach(() => {
    setActivePinia(createPinia())
    api.put.mockReset()
    api.put.mockImplementation(async () => ({ token: 'Bearer fresh' }))
    setToken.mockClear()
  })
  afterEach(() => wrapper?.unmount())

  async function fill(cur, next, confirm) {
    wrapper = mount(ChangePasswordModal, { attachTo: document.body })
    const inputs = wrapper.findAll('input[type="password"]')
    await inputs[0].setValue(cur)
    await inputs[1].setValue(next)
    await inputs[2].setValue(confirm)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }

  it('flags a mismatched confirmation without calling the API', async () => {
    await fill('old-password', 'new-password-1', 'new-password-2')
    expect(api.put).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("Passwords don't match.")
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('stores the re-issued token and closes on success', async () => {
    await fill('old-password', 'new-password-1', 'new-password-1')
    expect(api.put).toHaveBeenCalledWith('/users/change-password', { current: 'old-password', new: 'new-password-1' })
    expect(setToken).toHaveBeenCalledWith('Bearer fresh')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('maps a 400 to the Current password field and stays open', async () => {
    api.put.mockImplementation(async () => {
      throw new ApiError({ status: 400, message: 'current password incorrect' })
    })
    await fill('wrong', 'new-password-1', 'new-password-1')
    const fields = wrapper.findAll('label.field')
    expect(fields[0].text()).toContain('Current password is incorrect.')
    expect(setToken).not.toHaveBeenCalled()
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('maps a 422 to the New password field', async () => {
    api.put.mockImplementation(async () => {
      throw new ApiError({ status: 422, message: 'password must be at least 8 characters' })
    })
    await fill('old-password', 'short', 'short')
    const fields = wrapper.findAll('label.field')
    expect(fields[1].text()).toContain('password must be at least 8 characters')
  })
})
