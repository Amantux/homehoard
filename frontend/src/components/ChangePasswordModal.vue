<script setup>
// Change the signed-in user's password. The server signs out every other
// session and hands back a fresh token for this one, which must be stored or
// this tab's next request would 401 too.
import { ref } from 'vue'
import { api, setToken, ApiError } from '../api'
import { useUI } from '../stores/ui'
import { useAuth } from '../stores/auth'
import BaseModal from './BaseModal.vue'
import Field from './Field.vue'

const emit = defineEmits(['close'])
const ui = useUI()
const auth = useAuth()

const current = ref('')
const next = ref('')
const confirm = ref('')
const fieldErrors = ref({})
const busy = ref(false)

async function submit() {
  if (busy.value) return
  fieldErrors.value = {}
  if (next.value !== confirm.value) {
    fieldErrors.value = { confirm: "Passwords don't match." }
    return
  }
  busy.value = true
  try {
    const res = await api.put('/users/change-password', { current: current.value, new: next.value })
    setToken(res.token)
    ui.toast('Password changed. Other sessions were signed out.')
    emit('close')
  } catch (e) {
    // 400 = wrong current password; 422 = the new one fails the length rules.
    if (e instanceof ApiError && e.status === 400) fieldErrors.value = { current: 'Current password is incorrect.' }
    else if (e instanceof ApiError && e.status === 422) fieldErrors.value = { new: e.message }
    else ui.error(e.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <BaseModal width="420px" @close="emit('close')" v-slot="{ titleId }">
    <div class="modal-head">
      <h2 :id="titleId">Change password</h2>
      <button aria-label="Close" class="ghost icon-btn" @click="emit('close')">✕</button>
    </div>
    <form @submit.prevent="submit">
      <input type="text" name="username" class="visually-hidden" autocomplete="username"
             :value="auth.user?.email" readonly tabindex="-1" aria-hidden="true" />
      <Field label="Current password" :error="fieldErrors.current">
        <input v-model="current" type="password" autocomplete="current-password" autofocus required
               :aria-invalid="fieldErrors.current ? 'true' : undefined" /></Field>
      <Field label="New password" :error="fieldErrors.new">
        <input v-model="next" type="password" autocomplete="new-password" required
               :aria-invalid="fieldErrors.new ? 'true' : undefined" /></Field>
      <Field label="Confirm new password" :error="fieldErrors.confirm">
        <input v-model="confirm" type="password" autocomplete="new-password" required
               :aria-invalid="fieldErrors.confirm ? 'true' : undefined" /></Field>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:6px">
        <button type="button" class="secondary" @click="emit('close')">Cancel</button>
        <button type="submit" :disabled="busy">{{ busy ? 'Changing…' : 'Change password' }}</button>
      </div>
    </form>
  </BaseModal>
</template>
