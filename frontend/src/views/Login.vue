<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../stores/auth'
import { useUI } from '../stores/ui'
import { safeRedirect } from '../utils/safeRedirect'

const auth = useAuth()
const router = useRouter()
const route = useRoute()
const ui = useUI()
const mode = ref('login')
const email = ref('')
const password = ref('')
const name = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    if (mode.value === 'login') await auth.login(email.value, password.value)
    else await auth.register({ email: email.value, password: password.value, name: name.value })
    ui.sessionExpired = false
    // ?redirect= comes from the URL, so it is untrusted: in-app paths only.
    router.replace(safeRedirect(route.query.redirect))
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="center-screen">
    <div class="card auth-card">
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:40px">📦</div>
        <h1>HomeHoard</h1>
        <p class="muted" style="margin:4px 0 0">{{ mode === 'login' ? 'Sign in to your inventory' : 'Create your account' }}</p>
      </div>
      <form @submit.prevent="submit">
        <label v-if="mode === 'register'" class="field"><span>Name</span><input v-model="name" autocomplete="name" required /></label>
        <label class="field"><span>Email</span><input v-model="email" type="email" autocomplete="username" /></label>
        <label class="field"><span>Password</span><input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" /></label>
        <p v-if="error" role="alert" style="color:var(--danger);font-size:0.9rem">{{ error }}</p>
        <button type="submit" style="width:100%;justify-content:center" :disabled="busy">
          {{ mode === 'login' ? 'Sign in' : 'Create account' }}
        </button>
      </form>
      <p class="muted" style="text-align:center;margin-top:16px">
        <a href="#" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in' }}</a>
      </p>
    </div>
  </div>
</template>
