<script setup>
import { computed } from 'vue'
import { useUI } from '../stores/ui'
const ui = useUI()

// Two always-mounted live regions: a screen reader only announces content
// added to a region that already exists, so a region created together with
// its first toast is often read late or not at all. Errors go to the
// assertive (role="alert") one; everything else to the polite one.
const errors = computed(() => ui.toasts.filter((t) => t.type === 'error'))
const notices = computed(() => ui.toasts.filter((t) => t.type !== 'error'))

// Dismiss first so the action's own toasts (success or error) don't stack
// under a stale one; run() owns its error handling.
function runAction(t) {
  ui.dismiss(t.id)
  t.action.run()
}

// Hold auto-dismiss while the pointer or keyboard focus is in the toasts, so
// one can't vanish mid-read or out from under a focused Undo button.
function onFocusOut(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) ui.resumeToasts()
}
</script>

<template>
  <div class="toast-wrap" @mouseenter="ui.pauseToasts()" @mouseleave="ui.resumeToasts()"
       @focusin="ui.pauseToasts()" @focusout="onFocusOut">
    <div class="toast-region" role="alert">
      <div v-for="t in errors" :key="t.id" class="toast" :class="t.type">
        <span>{{ t.message }}</span>
        <button v-if="t.action" class="secondary sm" @click="runAction(t)">
          {{ t.action.label }}
        </button>
        <button class="ghost icon-btn toast-close" aria-label="Dismiss" @click="ui.dismiss(t.id)">✕</button>
      </div>
    </div>
    <div class="toast-region" role="status" aria-live="polite">
      <div v-for="t in notices" :key="t.id" class="toast" :class="t.type">
        <span>{{ t.message }}</span>
        <button v-if="t.action" class="secondary sm" @click="runAction(t)">
          {{ t.action.label }}
        </button>
        <button class="ghost icon-btn toast-close" aria-label="Dismiss" @click="ui.dismiss(t.id)">✕</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* The regions stay in the a11y tree even when empty (never display:none),
   so spacing lives between non-empty regions instead of on the wrapper. */
.toast-wrap { gap: 0; }
.toast-region { display: flex; flex-direction: column; gap: 10px; }
.toast-region:not(:empty) + .toast-region:not(:empty) { margin-top: 10px; }
/* Dismiss is the ✕ button now, not a click anywhere on the toast. */
.toast { cursor: default; }
</style>
