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

  async function reload() {
    loading.value = true
    error.value = null
    try {
      await loadFn()
    } catch (e) {
      error.value = e?.message || 'Something went wrong loading this page.'
    } finally {
      loading.value = false
    }
  }

  // Quiet background refresh for live updates: no skeleton flash, and a transient
  // error is swallowed (keep showing the last-good data). reload() stays the
  // explicit, visible path (initial load + user-triggered "Try again").
  async function refresh() {
    if (loading.value) return // don't race an in-flight full load
    try {
      await loadFn()
      error.value = null
    } catch {
      // Keep stale data; leave any existing error untouched.
    }
  }

  if (immediate) onMounted(reload)

  if (live && 'dataVersion' in ui) {
    const stopWatch = watch(() => ui.dataVersion, () => refresh())
    onUnmounted(stopWatch)
  }

  return { loading, error, reload, refresh }
}
