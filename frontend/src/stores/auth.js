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
    logout() {
      setToken(null)
      this.user = null
      location.hash = '#/login'
    },
  },
})
