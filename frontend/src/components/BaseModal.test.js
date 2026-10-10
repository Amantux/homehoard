// @vitest-environment happy-dom
import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import BaseModal from './BaseModal.vue'

// Mirrors the real stack: QuickCreate (outer BaseModal) opens PhotoCapture
// (inner BaseModal) from a button inside itself. Two BaseModals are used
// directly so the test exercises the shared stack, not either form's fields.
const Host = defineComponent({
  setup() {
    const outerOpen = ref(false)
    const innerOpen = ref(false)
    return () => h('div', [
      h('button', { id: 'opener', onClick: () => { outerOpen.value = true } }, 'New item'),
      outerOpen.value && h(BaseModal, { ariaLabel: 'Quick create', onClose: () => { outerOpen.value = false } }, {
        default: () => [
          h('button', { id: 'photo', onClick: () => { innerOpen.value = true } }, 'Add photo'),
          h('button', { id: 'save' }, 'Save'),
          innerOpen.value && h(BaseModal, { ariaLabel: 'Photo', onClose: () => { innerOpen.value = false } }, {
            default: () => [
              h('button', { id: 'shoot' }, 'Take photo'),
              h('button', { id: 'cancel' }, 'Cancel'),
            ],
          }),
        ],
      }),
    ])
  },
})

function key(k, opts = {}) {
  const e = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts })
  document.dispatchEvent(e)
  return e
}

async function settle() {
  // BaseModal focuses after an awaited nextTick inside onMounted.
  await nextTick()
  await nextTick()
}

describe('BaseModal stack', () => {
  let wrapper
  afterEach(() => wrapper?.unmount())

  it('Esc closes only the top modal, Tab wraps inside it, focus returns to the opener', async () => {
    wrapper = mount(Host, { attachTo: document.body })
    const opener = document.getElementById('opener')
    opener.focus()
    await wrapper.find('#opener').trigger('click')
    await settle()
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1)
    expect(document.activeElement.id).toBe('photo') // first focusable in the outer modal

    await wrapper.find('#photo').trigger('click')
    await settle()
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(2)
    expect(document.activeElement.id).toBe('shoot')

    // Tab from the last control in the top modal wraps to its first, not into the outer one.
    document.getElementById('cancel').focus()
    const tab = key('Tab')
    expect(tab.defaultPrevented).toBe(true)
    expect(document.activeElement.id).toBe('shoot')
    // Shift+Tab from the first wraps to the last.
    key('Tab', { shiftKey: true })
    expect(document.activeElement.id).toBe('cancel')

    // Esc closes the inner modal only; focus goes back to its opener in the outer one.
    key('Escape')
    await settle()
    const dialogs = document.querySelectorAll('[role="dialog"]')
    expect(dialogs.length).toBe(1)
    expect(dialogs[0].getAttribute('aria-label')).toBe('Quick create')
    expect(document.activeElement.id).toBe('photo')

    // Second Esc closes the outer modal and focus returns to the page opener.
    key('Escape')
    await settle()
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(0)
    expect(document.activeElement).toBe(opener)
  })
})
