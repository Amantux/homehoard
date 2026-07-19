<script setup>
import { ref, computed, getCurrentInstance } from 'vue'

const uid = 'combo-' + getCurrentInstance().uid
const listId = uid + '-list'
const optId = (i) => `${uid}-opt-${i}`

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] }, // [{ id, label, sublabel? }]
  placeholder: { type: String, default: 'Type to search…' },
  allowCreate: { type: Boolean, default: false },
  createNoun: { type: String, default: 'item' },
  ariaLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'create'])

const typed = ref('')
const open = ref(false)
const highlight = ref(-1)

const selected = computed(() => props.options.find((o) => o.id === props.modelValue) || null)
const display = computed(() => (selected.value ? selected.value.label : ''))

const filtered = computed(() => {
  const term = typed.value.trim().toLowerCase()
  if (!term) return props.options
  return props.options.filter((o) => o.label.toLowerCase().includes(term))
})
const canCreate = computed(() => {
  const term = typed.value.trim()
  return (
    props.allowCreate &&
    term.length > 0 &&
    !props.options.some((o) => o.label.toLowerCase() === term.toLowerCase())
  )
})
// Rows = filtered options, then (optionally) the create row.
const rowCount = computed(() => filtered.value.length + (canCreate.value ? 1 : 0))

function onFocus() {
  open.value = true
  typed.value = ''
  highlight.value = -1
}
function onInput(e) {
  typed.value = e.target.value
  open.value = true
  highlight.value = 0
}
function close() {
  open.value = false
  typed.value = ''
  highlight.value = -1
}
// Delay on focus-out so a mousedown on an option still registers first.
function onFocusOut() {
  setTimeout(close, 120)
}
function pick(option) {
  emit('update:modelValue', option.id)
  close()
}
function doCreate() {
  emit('create', typed.value.trim())
  close()
}
function clear() {
  emit('update:modelValue', '')
  typed.value = ''
}
function onEnter() {
  if (highlight.value < 0) return
  if (highlight.value < filtered.value.length) pick(filtered.value[highlight.value])
  else if (canCreate.value) doCreate()
}
function move(delta) {
  if (!open.value) { open.value = true; return }
  const n = rowCount.value
  if (n === 0) return
  if (highlight.value < 0) { highlight.value = delta > 0 ? 0 : n - 1; return }
  highlight.value = (highlight.value + delta + n) % n
}
</script>

<template>
  <div class="combobox" @focusout="onFocusOut">
    <div class="combo-input">
      <input
        :value="open ? typed : display"
        :placeholder="placeholder"
        :aria-label="ariaLabel || placeholder"
        role="combobox"
        :aria-expanded="open"
        :aria-controls="listId"
        :aria-activedescendant="highlight >= 0 ? optId(highlight) : undefined"
        autocomplete="off"
        @focus="onFocus"
        @input="onInput"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="onEnter"
        @keydown.esc.prevent="close"
      />
      <button v-if="modelValue && !open" type="button" class="combo-clear"
              aria-label="Clear" @click="clear">✕</button>
    </div>

    <ul v-if="open && (filtered.length || canCreate)" :id="listId" class="combo-list" role="listbox">
      <li
        v-for="(o, i) in filtered"
        :key="o.id"
        :id="optId(i)"
        role="option"
        :aria-selected="o.id === modelValue"
        class="combo-opt"
        :class="{ hi: i === highlight, sel: o.id === modelValue }"
        @mousedown.prevent="pick(o)"
        @mouseenter="highlight = i"
      >
        <span class="opt-label">{{ o.label }}</span>
        <span v-if="o.sublabel" class="opt-sub">{{ o.sublabel }}</span>
      </li>
      <li
        v-if="canCreate"
        :id="optId(filtered.length)"
        role="option"
        class="combo-opt combo-create"
        :class="{ hi: highlight === filtered.length }"
        @mousedown.prevent="doCreate"
        @mouseenter="highlight = filtered.length"
      >
        ＋ Create {{ createNoun }} “{{ typed.trim() }}”
      </li>
    </ul>
  </div>
</template>

<style scoped>
.combobox { position: relative; }
.combo-input { position: relative; }
.combo-input input { width: 100%; padding-right: 30px; }
.combo-clear {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  width: 22px; height: 22px; padding: 0; font-size: 0.72rem;
  background: none; border: none; color: var(--muted); cursor: pointer; border-radius: 5px;
}
.combo-clear:hover { background: var(--surface-2); color: var(--text); }
.combo-list {
  position: absolute; z-index: 60; left: 0; right: 0; top: calc(100% + 4px);
  margin: 0; padding: 4px; list-style: none; max-height: 240px; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); box-shadow: var(--shadow-lg);
}
.combo-opt {
  display: flex; align-items: baseline; gap: 8px;
  padding: 8px 10px; border-radius: 7px; cursor: pointer; font-size: 0.9rem;
}
.combo-opt.hi { background: var(--accent-soft); }
.combo-opt.sel .opt-label { font-weight: 650; color: var(--accent); }
.opt-label { flex-shrink: 0; }
.opt-sub { color: var(--muted); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.combo-create { color: var(--accent); font-weight: 600; }
</style>
