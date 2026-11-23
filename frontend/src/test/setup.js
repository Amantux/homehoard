// Vitest global setup: give the test environment a `localStorage` global.
//
// happy-dom (the @vitest-environment happy-dom files) does not expose a
// `localStorage` global on its own in the versions we pin — without one the ui
// pinia store blows up in its state initializer (`localStorage.getItem(
// THEME)`) and any view test that touches storage fails with "Cannot read
// properties of undefined (reading 'getItem'/'clear')". Views and stores read
// through the standard global, so a single fallback here covers every suite
// without each test having to stub storage itself.
//
// Tests that need to control storage can still vi.stubGlobal('localStorage', …)
// — those stubs win over this fallback.

class MemStorage {
  constructor() { this._m = new Map() }
  get length() { return this._m.size }
  getItem(k) { return this._m.has(String(k)) ? this._m.get(String(k)) : null }
  setItem(k, v) { this._m.set(String(k), String(v)) }
  removeItem(k) { this._m.delete(String(k)) }
  clear() { this._m.clear() }
  key(i) { return Array.from(this._m.keys())[i] ?? null }
}

if (typeof globalThis.localStorage === 'undefined') {
  globalThis.localStorage = new MemStorage()
}
