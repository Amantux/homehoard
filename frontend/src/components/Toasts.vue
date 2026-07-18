<script setup>
import { useUI } from '../stores/ui'
const ui = useUI()
</script>

<template>
  <div class="toast-wrap">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.type"
         role="status" @click="ui.dismiss(t.id)">
      <span>{{ t.message }}</span>
      <button v-if="t.type === 'error'" class="ghost icon-btn toast-close"
              aria-label="Dismiss" @click.stop="ui.dismiss(t.id)">✕</button>
    </div>
  </div>
</template>
