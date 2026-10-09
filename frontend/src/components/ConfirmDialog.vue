<script setup>
// The app's one confirmation dialog, driven by ui.confirmRequest (useConfirm).
import { onBeforeUnmount } from 'vue'
import { useUI } from '../stores/ui'
import BaseModal from './BaseModal.vue'

const ui = useUI()
// If the dialog unmounts while a request is open (template swap on a 401
// redirect, a route change) the awaiting caller must still settle, or every
// later confirm() rejects as "already open".
onBeforeUnmount(() => ui.resolveConfirm(false))
</script>

<template>
  <BaseModal v-if="ui.confirmRequest" :title="ui.confirmRequest.title" width="420px"
             @close="ui.resolveConfirm(false)">
    <p v-if="ui.confirmRequest.body" style="margin:0 0 16px">{{ ui.confirmRequest.body }}</p>
    <template #footer>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="secondary" :autofocus="ui.confirmRequest.danger || undefined"
                @click="ui.resolveConfirm(false)">{{ ui.confirmRequest.cancelLabel }}</button>
        <button :class="{ danger: ui.confirmRequest.danger }" :autofocus="!ui.confirmRequest.danger || undefined"
                @click="ui.resolveConfirm(true)">{{ ui.confirmRequest.confirmLabel }}</button>
      </div>
    </template>
  </BaseModal>
</template>
