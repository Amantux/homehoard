import { defineStore } from 'pinia'
import { THEME } from '../storageKeys'

let toastId = 0

// Live-sync handles, kept off the reactive state so stopLiveSync() can remove
// exactly the listeners startLiveSync() added.
let liveTimer = null
let liveTick = null
let onVisible = null
// Auto-dismiss timers for non-error toasts: id -> { handle, remaining, started }.
// Kept off reactive state so Toasts.vue can pause them on hover/focus.
const toastTimers = new Map()
let toastsPaused = false

function armToastTimer(store, id, ms) {
  // First toast into an empty stack: nothing can be hovered or focused, and a
  // region that shrank to nothing under the pointer never fired mouseleave.
  if (toastsPaused && store.toasts.length === 1) toastsPaused = false
  const t = { handle: null, remaining: ms, started: Date.now() }
  if (!toastsPaused) t.handle = setTimeout(() => store.dismiss(id), ms)
  toastTimers.set(id, t)
}

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
      if (type !== 'error') armToastTimer(this, id, action ? 8000 : 3200)
    },
    // Hover/focus on the toast region holds every pending auto-dismiss, so a
    // toast can't vanish while it is being read or its action is focused.
    pauseToasts() {
      if (toastsPaused) return
      toastsPaused = true
      const now = Date.now()
      for (const t of toastTimers.values()) {
        clearTimeout(t.handle)
        t.handle = null
        t.remaining = Math.max(0, t.remaining - (now - t.started))
      }
    },
    resumeToasts() {
      if (!toastsPaused) return
      toastsPaused = false
      for (const [id, t] of toastTimers) {
        t.started = Date.now()
        t.handle = setTimeout(() => this.dismiss(id), t.remaining)
      }
    },
    // Route change: an error toast is about the page being left, so it goes.
    // Success/info toasts (e.g. "Deleted" after a navigating delete) stay.
    clearErrorToasts() {
      this.toasts = this.toasts.filter((t) => t.type !== 'error')
    },
    error(message) {
      this.toast(message, 'error')
    },
    dismiss(id) {
      const timer = toastTimers.get(id)
      if (timer) { clearTimeout(timer.handle); toastTimers.delete(id) }
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
