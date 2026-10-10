import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useUI } from '../stores/ui'

// Standard async-load state for a view: loading / error / reload. Wraps a fetch
// function so every screen gets a consistent skeleton -> error+retry -> content
// flow instead of a stuck skeleton (or blank page) when the API fails.
//
// Live updating: the view refetches on the in-app signal (ui.dataVersion), fired
// when data changes anywhere. That refresh is QUIET — no skeleton flash, and a
// transient failure keeps the current data rather than replacing the view with
// an error. HomeHoard has no change signal yet, so the watch is skipped unless
// the store exposes one; adding `dataVersion` to the UI store later switches
// this on with no change to any view.
export function useLoader(loadFn, { immediate = true, live = true } = {}) {
  const loading = ref(immediate)
  const error = ref(null)
  const ui = useUI()

  // One loadFn call in flight per instance. loadFns assign the view's refs
  // themselves, so a stale response can't be discarded from out here — overlapping
  // calls must be serialized instead. A call arriving mid-load is remembered
  // (`pending`; a visible reload outranks a quiet refresh) and run once after
  // the current one, so the view always ends on the latest data.
  let inFlight = null
  let pending = null

  async function once(visible) {
    if (visible) {
      loading.value = true
      error.value = null
      try {
        await loadFn()
      } catch (e) {
        error.value = e?.message || 'Something went wrong loading this page.'
      } finally {
        loading.value = false
      }
    } else {
      // Quiet background refresh for live updates: no skeleton flash, and a
      // transient error is swallowed (keep showing the last-good data).
      try {
        await loadFn()
        error.value = null
      } catch {
        // Keep stale data; leave any existing error untouched.
      }
    }
  }

  function run(visible) {
    if (inFlight) {
      pending = pending === 'reload' || visible ? 'reload' : 'refresh'
      return inFlight
    }
    inFlight = (async () => {
      try {
        let kind = visible
        for (;;) {
          await once(kind)
          if (!pending) break
          kind = pending === 'reload'
          pending = null
        }
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  // reload() is the explicit, visible path (initial load + user-triggered
  // "Try again"); refresh() is the quiet live-update path.
  const reload = () => run(true)
  const refresh = () => run(false)

  if (immediate) onMounted(reload)

  if (live && 'dataVersion' in ui) {
    const stopWatch = watch(() => ui.dataVersion, () => refresh())
    onUnmounted(stopWatch)
  }

  return { loading, error, reload, refresh }
}
