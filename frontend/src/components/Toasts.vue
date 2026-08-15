<script setup>
import { useUI } from '../stores/ui'
const ui = useUI()

// Dismiss first so the action's own toasts (success or error) don't stack
// under a stale one; run() owns its error handling.
function runAction(t) {
  ui.dismiss(t.id)
  t.action.run()
}
</script>

<template>
  <div class="toast-wrap">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.type"
         role="status" @click="ui.dismiss(t.id)">
      <span>{{ t.message }}</span>
      <button v-if="t.action" class="secondary sm" @click.stop="runAction(t)">
        {{ t.action.label }}
      </button>
      <button v-if="t.type === 'error'" class="ghost icon-btn toast-close"
              aria-label="Dismiss" @click.stop="ui.dismiss(t.id)">✕</button>
    </div>
  </div>
</template>
