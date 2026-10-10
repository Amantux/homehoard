<script>
// Open modals, innermost last: only the top one answers Esc / Tab, so a
// PhotoCapture opened over QuickCreate closes alone.
const openStack = []
</script>

<script setup>
// Shared modal shell: dialog semantics, Esc / backdrop close, focus trap,
// initial focus and focus restore. Content modals keep their own .modal-head
// markup and put `:id="titleId"` (from the default slot) on their heading;
// or pass `title` and BaseModal renders the head itself.
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { focusableIn, trapTab } from '../utils/focusTrap.js'

const props = defineProps({
  title: String,
  width: String,
  ariaLabel: String,
  cardStyle: [String, Object],
  backdropStyle: [String, Object],
})
const emit = defineEmits(['close'])

const token = {}
const titleId = `modal-title-${Math.random().toString(36).slice(2, 10)}`
const dialog = ref(null)
let previouslyFocused = null

function onKeydown(e) {
  if (openStack[openStack.length - 1] !== token) return
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  } else if (e.key === 'Tab') {
    trapTab(e, dialog.value)
  }
}

onMounted(async () => {
  previouslyFocused = document.activeElement
  openStack.push(token)
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  const root = dialog.value
  if (!root || root.contains(document.activeElement)) return
  const target = root.querySelector('[autofocus]') || focusableIn(root)[0] || root
  target.focus()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  openStack.splice(openStack.indexOf(token), 1)
  if (previouslyFocused && typeof previouslyFocused.focus === 'function') previouslyFocused.focus()
})
</script>

<template>
  <div class="modal-backdrop" :style="backdropStyle" @click.self="emit('close')">
    <div ref="dialog" class="card modal" role="dialog" aria-modal="true" tabindex="-1"
         :aria-labelledby="ariaLabel ? undefined : titleId" :aria-label="ariaLabel"
         :style="[width ? { width, maxWidth: '96vw' } : null, cardStyle]">
      <div v-if="props.title || $slots.title" class="modal-head">
        <h2 :id="titleId"><slot name="title">{{ props.title }}</slot></h2>
      </div>
      <slot :title-id="titleId" />
      <slot name="footer" />
    </div>
  </div>
</template>
