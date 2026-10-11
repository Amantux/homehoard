// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import Toasts from './Toasts.vue'
import { useUI } from '../stores/ui'

describe('Toasts', () => {
  let ui
  let w
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    ui = useUI()
    w = mount(Toasts)
  })
  afterEach(() => {
    // The pause flag is module-level in the store; leave it released.
    ui.resumeToasts()
    ui.toasts.slice().forEach((t) => ui.dismiss(t.id))
    w.unmount()
    vi.useRealTimers()
  })

  it('errors persist past 10s; success dismisses after 3.2s', async () => {
    ui.toast('Saved', 'success')
    ui.error('Broke')
    await nextTick()
    vi.advanceTimersByTime(3100)
    expect(ui.toasts.map((t) => t.message)).toEqual(['Saved', 'Broke'])
    vi.advanceTimersByTime(200)
    await nextTick()
    expect(ui.toasts.map((t) => t.message)).toEqual(['Broke'])
    vi.advanceTimersByTime(10000)
    await nextTick()
    expect(ui.toasts.map((t) => t.message)).toEqual(['Broke'])
  })

  it('hover pauses the auto-dismiss timer and mouseleave resumes it', async () => {
    ui.toast('Saved', 'success')
    await nextTick()
    await w.find('.toast-wrap').trigger('mouseenter')
    vi.advanceTimersByTime(20000)
    expect(ui.toasts).toHaveLength(1)
    await w.find('.toast-wrap').trigger('mouseleave')
    vi.advanceTimersByTime(3300)
    await nextTick()
    expect(ui.toasts).toHaveLength(0)
  })

  it('clearErrorToasts removes only errors', async () => {
    ui.toast('Saved', 'success')
    ui.error('Broke')
    ui.clearErrorToasts()
    await nextTick()
    expect(ui.toasts.map((t) => t.message)).toEqual(['Saved'])
  })

  it('the dismiss button removes its own toast', async () => {
    ui.error('One')
    ui.error('Two')
    await nextTick()
    await w.findAll('.toast-close')[0].trigger('click')
    expect(ui.toasts.map((t) => t.message)).toEqual(['Two'])
  })

  it('renders errors in role=alert and notices in role=status', async () => {
    ui.error('Broke')
    ui.toast('Saved', 'success')
    await nextTick()
    expect(w.find('[role="alert"]').text()).toContain('Broke')
    expect(w.find('[role="alert"]').text()).not.toContain('Saved')
    expect(w.find('[role="status"]').text()).toContain('Saved')
    expect(w.find('[role="status"]').text()).not.toContain('Broke')
  })
})
