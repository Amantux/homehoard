import { defineStore } from 'pinia'

let toastId = 0

export const useUI = defineStore('ui', {
  state: () => ({
    theme: localStorage.getItem('easyinv_theme') || 'auto',
    // Bumped whenever the server reports a data change (see startLiveSync) or a
    // surface knows it wrote. Every useLoader view watches this and quiet-
    // refreshes — no skeleton flash, last-good data kept on a transient failure.
    dataVersion: 0,
    toasts: [],
    // When set, App.vue opens the Create modal pre-set to this kind.
    createKind: null,
    // When set ({description, type?}), App.vue opens the Report-a-bug modal prefilled
    // (used by the chat assistant's bug-report walkthrough).
    bugReport: null,
  }),
  actions: {
    openCreate(kind = 'item') {
      this.createKind = kind
    },
    closeCreate() {
      this.createKind = null
    },
    openBugReport(payload) {
      this.bugReport = payload || {}
    },
    closeBugReport() {
      this.bugReport = null
    },
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
    dataChanged() {
      this.dataVersion += 1
    },
    // Poll a cheap change CURSOR (never the data): background writers — MCP
    // tools, HA service calls, the chat assistant — mutate the DB without the
    // browser knowing. Same cursor -> do nothing; new cursor -> bump
    // dataVersion. Skips when the tab is hidden; also checks on focus/visible.
    startLiveSync(api) {
      if (this._liveTimer) return
      let last = null
      const tick = async () => {
        if (document.hidden) return
        try {
          const { cursor } = await api.get('/changes')
          if (last !== null && cursor !== last) this.dataChanged()
          last = cursor
        } catch (e) { /* transient — next tick retries; never surface a toast */ }
      }
      this._liveTimer = setInterval(tick, 12000)
      document.addEventListener('visibilitychange', () => { if (!document.hidden) tick() })
      window.addEventListener('focus', tick)
      tick()
    },
    toast(message, type = 'success') {
      const id = ++toastId
      this.toasts.push({ id, message, type })
      // Errors persist until dismissed; success/info auto-dismiss.
      if (type !== 'error') setTimeout(() => this.dismiss(id), 3200)
    },
    error(message) {
      this.toast(message, 'error')
    },
    dismiss(id) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
