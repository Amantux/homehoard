// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import Combobox from './Combobox.vue'

const OPTIONS = [
  { id: 'a', label: 'Garage' },
  { id: 'b', label: 'Garden shed' },
  { id: 'c', label: 'Attic' },
]

describe('Combobox', () => {
  let wrapper
  afterEach(() => {
    wrapper?.unmount()
    vi.useRealTimers()
  })

  const input = () => wrapper.get('[role="combobox"]')

  it('remote mode emits one trimmed search per typed change and does not filter locally', async () => {
    wrapper = mount(Combobox, { props: { options: OPTIONS, remote: true } })
    await input().trigger('focus')
    // Options are already present, so focus must not emit a seed search.
    expect(wrapper.emitted('search')).toBeUndefined()

    await input().setValue('  gar ')
    expect(wrapper.emitted('search')).toEqual([['gar']])
    // The parent owns matching in remote mode: non-matching options stay listed.
    expect(wrapper.findAll('[role="option"]')).toHaveLength(3)
  })

  it('ArrowDown + Enter selects the second option and emits update:modelValue', async () => {
    wrapper = mount(Combobox, { props: { options: OPTIONS } })
    await input().trigger('focus')
    await input().trigger('keydown', { key: 'ArrowDown' })
    await input().trigger('keydown', { key: 'ArrowDown' })
    await input().trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['b']])
    expect(input().attributes('aria-expanded')).toBe('false')
  })

  it('blur with no selection leaves the model alone and closes the listbox', async () => {
    vi.useFakeTimers()
    wrapper = mount(Combobox, {
      props: { options: OPTIONS, modelValue: 'c' },
      attachTo: document.body,
    })
    await input().trigger('focus')
    expect(input().attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)

    await input().trigger('focusout')
    await vi.advanceTimersByTimeAsync(200)

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(input().attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(input().element.value).toBe('Attic')
  })

  it('allowCreate offers a create row for unmatched text and Enter emits create', async () => {
    wrapper = mount(Combobox, { props: { options: OPTIONS, allowCreate: true, createNoun: 'location' } })
    await input().trigger('focus')
    await input().setValue('Cellar')
    const row = wrapper.get('.combo-create')
    expect(row.text()).toContain('Create location')
    expect(row.text()).toContain('Cellar')

    // setValue highlights row 0 (no match -> only the create row exists).
    await input().trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('create')).toEqual([['Cellar']])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('does not offer create when the text exactly matches an option', async () => {
    wrapper = mount(Combobox, { props: { options: OPTIONS, allowCreate: true } })
    await input().trigger('focus')
    await input().setValue('garage')
    expect(wrapper.find('.combo-create').exists()).toBe(false)
  })
})
