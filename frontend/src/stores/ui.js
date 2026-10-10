import { defineStore } from 'pinia'
import { THEME } from '../storageKeys'

let toastId = 0

// Live-sync handles, kept off the reactive state so stopLiveSync() can remove
// exactly the listeners startLiveSync() added.
let liveTimer = null
let liveTick = null
let onVisible = null

export const useUI = defineStore('ui', {
  state: () => ({
    theme: localStorage.getItem(THEME) || 'auto',
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
    // Pending in-app confirmation ({title, body, confirmLabel, cancelLabel,
    // danger}); App.vue renders ConfirmDialog while set. See useConfirm().
    confirmRequest: null,
    // Set when a 401 ended a signed-in session; App.vue shows a sign-in banner
    // over the still-mounted view. Cleared on the next successful login.
    sessionExpired: false,
  }),
  actions: {
    // One confirmation at a time: a second request while one is open REJECTS
    // (rather than queueing) — two stacked "are you sure?" prompts is a bug in
    // the caller, and a queued one would fire after the context has changed.
    requestConfirm(opts) {
      // One dialog at a time: a second request is declined (callers never catch).
      if (this.confirmRequest) return Promise.resolve(false)
      return new Promise((resolve) => {
        this._confirmResolve = resolve
        this.confirmRequest = { confirmLabel: 'Confirm', cancelLabel: 'Cancel', danger: false, ...opts }
      })
    },
    resolveConfirm(ok) {
      const resolve = this._confirmResolve
      this._confirmResolve = null
      this.confirmRequest = null
      if (resolve) resolve(!!ok)
    },
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
      localStorage.setItem(THEME, t)
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
      if (liveTimer) return
      let last = null
      let busy = false
      const tick = async () => {
        if (document.hidden || busy) return // skip while a /changes call is outstanding
        busy = true
        try {
          const { cursor } = await api.get('/changes')
          if (last !== null && cursor !== last) this.dataChanged()
          last = cursor
        } catch (e) { /* transient — next tick retries; never surface a toast */ } finally {
          busy = false
        }
      }
      liveTick = tick
      onVisible = () => { if (!document.hidden) tick() }
      liveTimer = setInterval(tick, 12000)
      document.addEventListener('visibilitychange', onVisible)
      window.addEventListener('focus', tick)
      tick()
    },
    // Logout / 401: stop polling (it would only 401) so a later login starts fresh.
    stopLiveSync() {
      if (!liveTimer) return
      clearInterval(liveTimer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', liveTick)
      liveTimer = liveTick = onVisible = null
    },
    // Optional { action: { label, run } } renders a button on the toast
    // (e.g. "Undo" after a merge). Action toasts linger longer — 3.2s is not
    // enough time to read, decide and click — but still auto-dismiss: the
    // action is a convenience, not a modal decision.
    toast(message, type = 'success', { action = null } = {}) {
      const id = ++toastId
      this.toasts.push({ id, message, type, action })
      // Errors persist until dismissed; success/info auto-dismiss.
      if (type !== 'error') setTimeout(() => this.dismiss(id), action ? 8000 : 3200)
    },
    error(message) {
      this.toast(message, 'error')
    },
    dismiss(id) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
