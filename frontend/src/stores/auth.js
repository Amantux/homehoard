import { defineStore } from 'pinia'
import { api, setToken, getToken } from '../api'

export const useAuth = defineStore('auth', {
  state: () => ({
    user: null,
    authDisabled: false,
    ready: false,
  }),
  getters: {
    isAuthed: (s) => !!s.user || s.authDisabled,
  },
  actions: {
    async bootstrap() {
      // If auth is disabled server-side, /users/self succeeds with no token.
      try {
        const res = await api.get('/users/self')
        this.user = res.item
        if (!getToken()) this.authDisabled = true
      } catch (e) {
        this.user = null
      } finally {
        this.ready = true
      }
    },
    async login(email, password) {
      const res = await api.post('/users/login', { username: email, password })
      setToken(res.token)
      const self = await api.get('/users/self')
      this.user = self.item
    },
    async register(payload) {
      await api.post('/users/register', payload)
      await this.login(payload.email, payload.password)
    },
    // The server rejected our token (a 401; api.js has already cleared it).
    // Unlike logout() this does not navigate: the open view stays mounted and
    // App.vue shows a sign-in banner. Returns true only when a signed-in
    // session actually ended, so a 401 on the login form or during bootstrap
    // (no session yet) raises no banner. With auth disabled there is no token
    // to expire — a 401 there is an endpoint-level refusal (e.g. a wrong vault
    // passphrase), not a lost session — so the user is left in place.
    expire() {
      if (this.authDisabled || !this.user) return false
      this.user = null
      return true
    },
    logout() {
      setToken(null)
      this.user = null
      location.hash = '#/login'
    },
  },
})
