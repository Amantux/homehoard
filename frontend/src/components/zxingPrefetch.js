// Shared across scanner instances: the zxing chunk (~125 kB gz) is fetched once,
// and the 📷 opener can start it on hover/focus before the modal mounts.
// Lives outside ScannerModal.vue so App.vue can import it without pulling the
// (lazy) modal back into the main chunk. Reset on failure so a retry issues a
// fresh request.
let zxingPromise = null
export function prefetchZxing() {
  if (!zxingPromise) {
    zxingPromise = import('@zxing/browser').catch((e) => {
      zxingPromise = null
      throw e
    })
    // A hover-prefetch caller ignores the result; don't surface that as an
    // unhandled rejection. Real callers still see the rejection.
    zxingPromise.catch(() => {})
  }
  return zxingPromise
}

// Drop a hung request so the next prefetchZxing() starts a fresh one.
export function resetZxing() {
  zxingPromise = null
}
