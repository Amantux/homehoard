import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, ApiError, NETWORK_ERROR_MESSAGE, setWriteHook, setUnauthorizedHook, streamPost } from './api.js'

const res = (status, body, ct) => ({
  ok: status < 400, status, statusText: 'x',
  headers: { get: () => ct },
  json: async () => body, text: async () => body,
})

describe('api errors', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { location: { pathname: '/' } })
    vi.stubGlobal('location', { hash: '#/' })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('network failure -> ApiError status 0 with a curated message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const e = await api.get('/items').catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(0)
    expect(e.message).toBe(NETWORK_ERROR_MESSAGE)
  })

  it('500 with an HTML body -> curated message, not the HTML', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(500, '<html>Bad Gateway</html>', 'text/html')))
    const e = await api.get('/items').catch((x) => x)
    expect(e.status).toBe(500)
    expect(e.message).toBe('HomeHoard hit an error. Try again.')
    expect(e.message).not.toContain('<html>')
  })

  it('422 JSON with fields -> fields + requestId carried', async () => {
    const body = { error: 'validation failed', fields: { name: 'Name is required' }, requestId: 'abc123' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(422, body, 'application/json')))
    const e = await api.post('/items', {}).catch((x) => x)
    expect(e).toMatchObject({ status: 422, message: 'validation failed', requestId: 'abc123', fields: { name: 'Name is required' } })
  })

  it('JSON error without fields keeps status (404 checks keep working)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(404, { error: 'item not found' }, 'application/json')))
    const e = await api.get('/items/9').catch((x) => x)
    expect(e).toMatchObject({ status: 404, message: 'item not found', fields: {} })
  })
})

describe('write hook', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { location: { pathname: '/' } })
    vi.stubGlobal('location', { hash: '#/' })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
  })
  afterEach(() => { setWriteHook(null); vi.unstubAllGlobals() })

  it('fires on a successful write, not on GET or a failed write', async () => {
    const hook = vi.fn()
    setWriteHook(hook)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(200, { ok: 1 }, 'application/json')))
    await api.get('/items')
    expect(hook).not.toHaveBeenCalled()
    await api.post('/items', {})
    expect(hook).toHaveBeenCalledTimes(1)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(422, { error: 'bad' }, 'application/json')))
    await api.post('/items', {}).catch(() => {})
    expect(hook).toHaveBeenCalledTimes(1)
  })
})

describe('401 handling', () => {
  let removed
  beforeEach(() => {
    removed = []
    vi.stubGlobal('window', { location: { pathname: '/' } })
    vi.stubGlobal('location', { hash: '#/items/42?q=drill' })
    vi.stubGlobal('localStorage', { getItem: () => 'tok', setItem() {}, removeItem: (k) => removed.push(k) })
  })
  afterEach(() => { setUnauthorizedHook(null); vi.unstubAllGlobals() })

  it('401 -> clears the token, calls the hook once, and leaves the page where it is', async () => {
    const hook = vi.fn()
    setUnauthorizedHook(hook)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(401, { error: 'Unauthorized' }, 'application/json')))
    const e = await api.get('/items').catch((x) => x)
    expect(e.status).toBe(401)
    expect(hook).toHaveBeenCalledTimes(1)
    expect(removed.length).toBe(1)
    expect(location.hash).toBe('#/items/42?q=drill')
  })

  it('streaming 401 -> same: hook once, hash unchanged', async () => {
    const hook = vi.fn()
    setUnauthorizedHook(hook)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ...res(401, { error: 'Unauthorized' }, 'application/json'), body: null }))
    await streamPost('/chat', {}, () => {}).catch(() => {})
    expect(hook).toHaveBeenCalledTimes(1)
    expect(location.hash).toBe('#/items/42?q=drill')
  })

  it('non-401 errors do not end the session', async () => {
    const hook = vi.fn()
    setUnauthorizedHook(hook)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res(403, { error: 'Forbidden' }, 'application/json')))
    await api.get('/items').catch(() => {})
    expect(hook).not.toHaveBeenCalled()
    expect(removed.length).toBe(0)
  })
})

describe('streamPost errors and malformed lines', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { location: { pathname: '/' } })
    vi.stubGlobal('location', { hash: '#/' })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  const streamRes = (...chunks) => {
    const enc = new TextEncoder()
    const queue = chunks.map((c) => enc.encode(c))
    return {
      ok: true, status: 200, headers: { get: () => 'application/x-ndjson' },
      body: { getReader: () => ({ read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true }) }) },
    }
  }

  it('network failure -> ApiError status 0 with a curated message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const e = await streamPost('/chat', {}, () => {}).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(0)
    expect(e.message).toBe(NETWORK_ERROR_MESSAGE)
  })

  it('500 with a non-JSON body -> ApiError 500 with the curated message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 500, statusText: 'Internal Server Error', body: null,
      headers: { get: () => 'text/html' },
      json: async () => { throw new SyntaxError('Unexpected token <') },
    }))
    const e = await streamPost('/chat', {}, () => {}).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(500)
    expect(e.message).toMatch(/^HomeHoard hit an error/)
  })

  it("503 JSON keeps the server's error text (ChatAssistant keys on 'provider')", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ...res(503, { error: 'No AI provider configured' }, 'application/json'), body: null }))
    const e = await streamPost('/chat', {}, () => {}).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(503)
    expect(e.message).toBe('No AI provider configured')
  })

  it('skips a malformed line with one warning and keeps streaming', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamRes('{"a":1}\nnot-json\n{"b', '":2}\nalso bad\n{"c":3}')))
    const events = []
    await streamPost('/chat', {}, (e) => events.push(e))
    expect(events).toEqual([{ a: 1 }, { b: 2 }, { c: 3 }])
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it("does not swallow onEvent's own errors", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamRes('{"a":1}\n')))
    const boom = new Error('handler broke')
    await expect(streamPost('/chat', {}, () => { throw boom })).rejects.toBe(boom)
  })
})
