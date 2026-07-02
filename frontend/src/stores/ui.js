import { defineStore } from 'pinia'

let toastId = 0

export const useUI = defineStore('ui', {
  state: () => ({
    theme: localStorage.getItem('easyinv_theme') || 'auto',
    toasts: [],
  }),
  actions: {
    applyTheme() {
      const resolved =
        this.theme === 'auto'
          ? window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
          : this.theme
      document.documentElement.setAttribute('data-theme', resolved)
    },
    setTheme(t) {
      this.theme = t
      localStorage.setItem('easyinv_theme', t)
      this.applyTheme()
    },
    toggleTheme() {
      const resolved = document.documentElement.getAttribute('data-theme')
      this.setTheme(resolved === 'dark' ? 'light' : 'dark')
    },
    toast(message, type = 'success') {
      const id = ++toastId
      this.toasts.push({ id, message, type })
      setTimeout(() => this.dismiss(id), 3200)
    },
    error(message) {
      this.toast(message, 'error')
    },
    dismiss(id) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
