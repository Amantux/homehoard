// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

// Contract under test (docs/chat-and-providers.md): status on mount, streamed
// deltas then the authoritative `done` reply, and a provider failure mid-chat
// flips back to the setup state and pops the orphaned user message.
let diagnostics
let streamEvents
let streamError

vi.mock('../api', () => {
  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(async (url) => {
        if (url === '/settings/chat') return { stream: true }
        if (url === '/diagnostics') return diagnostics
        return {}
      }),
      post: vi.fn(),
    },
    streamPost: vi.fn(async (path, body, onEvent) => {
      for (const ev of streamEvents) onEvent(ev)
      if (streamError) throw streamError
    }),
  }
})

import ChatAssistant from './ChatAssistant.vue'
import { ApiError, streamPost } from '../api'

async function mountOpen() {
  const w = mount(ChatAssistant, {
    global: { stubs: { 'router-link': { template: '<a><slot /></a>' }, transition: false } },
    attachTo: document.body,
  })
  await flushPromises()
  await w.find('.fab').trigger('click')
  await flushPromises()
  return w
}

async function say(w, text) {
  await w.find('.pinput').setValue(text)
  await w.find('.send').trigger('click')
  await flushPromises()
}

describe('ChatAssistant', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.body.innerHTML = ''
    diagnostics = { aiProvider: 'ollama' }
    streamEvents = []
    streamError = null
    vi.clearAllMocks()
  })

  it('shows the setup state, not the input, when no provider is configured', async () => {
    diagnostics = { aiProvider: 'none' }
    const w = await mountOpen()
    expect(w.text()).toContain('No AI provider is set up yet')
    expect(w.find('.ai-tag').text()).toBe('not set up')
    expect(w.find('.pinput').element.disabled).toBe(true)
    expect(w.find('.send').element.disabled).toBe(true)
    expect(w.findAll('.chip')).toHaveLength(0)
    w.unmount()
  })

  it('shows the input and suggestions when a provider is configured', async () => {
    const w = await mountOpen()
    expect(w.find('.ai-tag').text()).toBe('ollama')
    expect(w.find('.pinput').element.disabled).toBe(false)
    expect(w.findAll('.chip').length).toBeGreaterThan(0)
    w.unmount()
  })

  it('streams deltas, then the done event supplies the authoritative reply', async () => {
    streamEvents = [
      { type: 'delta', text: 'Your drill ' },
      { type: 'delta', text: 'is in the gar' },
      { type: 'done', sessionId: 's1', reply: 'Your drill is in the garage.', actions: [] },
    ]
    const w = await mountOpen()
    await say(w, 'Where is my drill?')
    const bubbles = w.findAll('.bubble').map((b) => b.text())
    expect(bubbles).toEqual(['Where is my drill?', 'Your drill is in the garage.'])
    expect(streamPost).toHaveBeenCalledWith(
      '/chat/stream', { message: 'Where is my drill?', sessionId: null }, expect.any(Function))
    w.unmount()
  })

  it('concatenates deltas when no done event rewrites them', async () => {
    streamEvents = [{ type: 'delta', text: 'Hel' }, { type: 'delta', text: 'lo' }]
    const w = await mountOpen()
    await say(w, 'hi')
    expect(w.findAll('.bubble').map((b) => b.text())).toEqual(['hi', 'Hello'])
    w.unmount()
  })

  it('a provider error mid-stream pops the user turn and flips to the setup state', async () => {
    streamEvents = [{ type: 'error', error: 'AI provider unreachable' }]
    const w = await mountOpen()
    await say(w, 'Where is my drill?')
    expect(w.findAll('.turn')).toHaveLength(0)
    expect(w.find('.ai-tag').text()).toBe('not set up')
    expect(w.text()).toContain('No AI provider is set up yet')
    w.unmount()
  })

  it('a non-provider stream error keeps the user turn and shows the error bubble', async () => {
    streamEvents = [{ type: 'error', error: 'Boom' }]
    const w = await mountOpen()
    await say(w, 'hello')
    const bubbles = w.findAll('.bubble')
    expect(bubbles.map((b) => b.text())).toEqual(['hello', 'Boom'])
    expect(bubbles[1].classes()).toContain('err')
    w.unmount()
  })

  it('a 401 from the stream shows the inline error (session-expiry is the api layer hook)', async () => {
    // The 401 hook (setUnauthorizedHook) fires inside api.js, which is mocked here;
    // the component itself has no sessionExpired path, so it renders the message.
    streamError = new ApiError('Sign in again.', 401)
    const w = await mountOpen()
    await say(w, 'hello')
    const bubbles = w.findAll('.bubble')
    expect(bubbles.map((b) => b.text())).toEqual(['hello', 'Sign in again.'])
    expect(bubbles[1].classes()).toContain('err')
    w.unmount()
  })
})
