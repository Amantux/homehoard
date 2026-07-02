<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const router = useRouter()
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
    router.push('/')
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
      <label v-if="mode === 'register'" class="field"><span>Name</span><input v-model="name" /></label>
      <label class="field"><span>Email</span><input v-model="email" type="email" @keyup.enter="submit" /></label>
      <label class="field"><span>Password</span><input v-model="password" type="password" @keyup.enter="submit" /></label>
      <p v-if="error" style="color:var(--danger);font-size:0.9rem">{{ error }}</p>
      <button style="width:100%;justify-content:center" :disabled="busy" @click="submit">
        {{ mode === 'login' ? 'Sign in' : 'Create account' }}
      </button>
      <p class="muted" style="text-align:center;margin-top:16px">
        <a href="#" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in' }}</a>
      </p>
    </div>
  </div>
</template>
