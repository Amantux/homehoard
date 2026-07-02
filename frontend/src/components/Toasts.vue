<script setup>
import { useUI } from '../stores/ui'
const ui = useUI()
</script>

<template>
  <div class="toast-wrap">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.type"
         @click="ui.dismiss(t.id)">
      {{ t.message }}
    </div>
  </div>
</template>
