// localStorage keys. The app was once called "easyinv"; migrateLegacyKeys()
// carries those values over so an upgrade doesn't log people out or reset prefs.
export const TOKEN = 'homehoard_token'
export const ITEM_VIEW = 'homehoard_itemview'
export const THEME = 'homehoard_theme'

const LEGACY = {
  easyinv_token: TOKEN,
  easyinv_itemview: ITEM_VIEW,
  easyinv_theme: THEME,
}

// Copy each legacy value to its new key (unless the new key is already set),
// then drop the legacy key. Storage can throw (private mode, blocked site
// data) — a failed migration must never stop the app from booting.
export function migrateLegacyKeys() {
  for (const [oldKey, newKey] of Object.entries(LEGACY)) {
    try {
      const old = localStorage.getItem(oldKey)
      if (old === null) continue
      if (localStorage.getItem(newKey) === null) localStorage.setItem(newKey, old)
      localStorage.removeItem(oldKey)
    } catch {
      // ignore: storage unavailable
    }
  }
}
