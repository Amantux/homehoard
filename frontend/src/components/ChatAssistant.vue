<script setup>
// Ambient inventory assistant — a floating button on every page, matching the
// Edibl / myMeal chat experience. Reuses HomeHoard's /chat backend (streaming
// optional) and shows suggestion chips + a proactive setup state.
import { ref, computed, onMounted, nextTick } from 'vue'
import { api, streamPost } from '../api'
import { useUI } from '../stores/ui'
import { hideMarker, finalizeReply } from '../utils/bugMarker'

const ui = useUI()

const open = ref(false)
const msgs = ref([]) // { role, content, actions?, error? }
const input = ref('')
const busy = ref(false)
const sessionId = ref(null)
const body = ref(null)

// Provider status → badge + proactive setup state (via the login-gated
// /diagnostics, which reports the effective provider name — never a secret).
const aiStatus = ref({ enabled: true, provider: '' })
const notConfigured = computed(() => aiStatus.value.enabled === false)
async function loadStatus() {
  try {
    const d = await api.get('/diagnostics')
    const p = (d.aiProvider || '').toLowerCase()
    aiStatus.value = { enabled: !!p && p !== 'none', provider: p === 'none' ? '' : p }
  } catch (e) { /* stay optimistic */ }
}

// Transport: per-browser override (localStorage) over the household default
// (backend), which defaults to classic POST. See docs/chat-and-providers.md.
const STREAM_KEY = 'hbox_chat_stream'
const householdDefault = ref(false)
const streamOverride = ref(readOverride())
const streaming = computed(() =>
  streamOverride.value === null ? householdDefault.value : streamOverride.value)
function readOverride() {
  const v = localStorage.getItem(STREAM_KEY)
  if (v === 'true') return true
  if (v === 'false') return false
  return null
}
function setStreaming(on) {
  streamOverride.value = !!on
  localStorage.setItem(STREAM_KEY, on ? 'true' : 'false')
}

onMounted(async () => {
  try { householdDefault.value = !!(await api.get('/settings/chat')).stream } catch (e) { /* default false */ }
  loadStatus()
})

const suggestions = [
  'Where is my drill?',
  "What's in the garage?",
  'Search for winter clothes',
  'List my labels',
]

function toggle() {
  open.value = !open.value
  if (open.value) { loadStatus(); scrollDown() }
}
function reset() { msgs.value = []; sessionId.value = null }

async function scrollDown() {
  await nextTick()
  if (body.value) body.value.scrollTop = body.value.scrollHeight
}

async function sendPost(message) {
  const r = await api.post('/chat', { message, sessionId: sessionId.value })
  sessionId.value = r.sessionId
  const { content, summary } = finalizeReply(r.reply)
  msgs.value.push({ role: 'assistant', content, actions: r.actions || [], bugReportSummary: summary })
}

async function sendStream(message) {
  msgs.value.push({ role: 'assistant', content: '', raw: '', actions: [] })
  const idx = msgs.value.length - 1 // mutate via the reactive proxy, not the raw object
  let errored = null
  try {
    await streamPost('/chat/stream', { message, sessionId: sessionId.value }, (ev) => {
      const a = msgs.value[idx]
      if (ev.type === 'delta') {
        a.raw += ev.text
        a.content = hideMarker(a.raw)   // hide the marker (incl. a mid-stream partial) as it streams
        scrollDown()
      } else if (ev.type === 'done') {
        sessionId.value = ev.sessionId
        a.raw = ev.reply || a.raw
        const { content, summary } = finalizeReply(a.raw)
        a.content = content
        a.actions = ev.actions || []
        a.bugReportSummary = summary
      } else if (ev.type === 'error') { errored = new Error(ev.error || 'Something went wrong.') }
    })
  } catch (e) {
    if (!msgs.value[idx].content) msgs.value.splice(idx, 1)
    throw e
  }
  if (errored) {
    if (!msgs.value[idx].content) msgs.value.splice(idx, 1)
    throw errored
  }
}

async function send(text) {
  const message = (text ?? input.value).trim()
  if (!message || busy.value) return
  input.value = ''
  msgs.value.push({ role: 'user', content: message })
  busy.value = true
  await scrollDown()
  try {
    if (streaming.value) await sendStream(message)
    else await sendPost(message)
    if (notConfigured.value) aiStatus.value = { enabled: true, provider: aiStatus.value.provider }
  } catch (e) {
    if (String(e.message || '').toLowerCase().includes('provider')) {
      aiStatus.value = { enabled: false, provider: '' }
      if (msgs.value.length && msgs.value[msgs.value.length - 1].role === 'user') msgs.value.pop()
    } else {
      msgs.value.push({ role: 'assistant', error: true, content: e.message || 'Something went wrong.' })
    }
  } finally {
    busy.value = false
    await scrollDown()
  }
}
</script>

<template>
  <div class="asst">
    <button class="fab" :class="{ open }" @click="toggle"
            :aria-label="open ? 'Close assistant' : 'Open assistant'">
      <span v-if="!open">💬</span><span v-else>✕</span>
    </button>

    <transition name="asst-panel">
      <section v-if="open" class="panel" role="dialog" aria-label="HomeHoard assistant">
        <header class="phead">
          <div style="display:flex;gap:8px;align-items:center">
            <strong>🔎 Assistant</strong>
            <span class="ai-tag" :class="aiStatus.enabled ? 'on' : 'off'">
              {{ aiStatus.enabled ? (aiStatus.provider || 'ready') : 'not set up' }}
            </span>
          </div>
          <div style="display:flex;gap:10px;align-items:center">
            <label class="stream-toggle" title="Stream the reply as it's written (this browser)">
              <input type="checkbox" :checked="streaming" @change="setStreaming($event.target.checked)" /> Stream
            </label>
            <button v-if="msgs.length" class="linkish" @click="reset">New chat</button>
          </div>
        </header>

        <div ref="body" class="pbody">
          <div v-if="!msgs.length" class="empty">
            <template v-if="notConfigured">
              <p class="muted">🔌 No AI provider is set up yet. An instance admin can wire one up in
                <router-link to="/tools" @click="toggle">Tools → AI provider</router-link>
                (Ollama, a local OpenAI-compatible model, or Claude).</p>
            </template>
            <template v-else>
              <p class="muted">Ask about your inventory — where something is, what's in a location, or to tag an item.</p>
              <button v-for="s in suggestions" :key="s" class="chip" @click="send(s)">{{ s }}</button>
            </template>
          </div>

          <div v-for="(m, i) in msgs" :key="i" class="turn" :class="m.role">
            <div class="bubble" :class="{ err: m.error }">
              <template v-if="m.content">{{ m.content }}</template>
              <span v-else-if="!m.error" class="muted">…</span>
            </div>
            <div v-if="m.actions && m.actions.length" class="actions">
              <span v-for="(a, j) in m.actions" :key="j" class="action">✓ {{ a.tool.replace(/_/g, ' ') }}</span>
            </div>
            <div v-if="m.bugReportSummary" class="actions">
              <button class="bug-btn" @click="ui.openBugReport({ description: m.bugReportSummary })">
                🐞 Open bug report
              </button>
            </div>
          </div>

          <div v-if="busy && !streaming" class="muted thinking">Thinking…</div>
        </div>

        <div class="pfoot">
          <input v-model="input" class="pinput"
                 :placeholder="notConfigured ? 'Set up an AI provider to chat' : 'Ask the assistant…'"
                 :disabled="busy || notConfigured" @keyup.enter="send()"
                 aria-label="Message the assistant" />
          <button class="send" :disabled="busy || notConfigured || !input.trim()" @click="send()">Send</button>
        </div>
      </section>
    </transition>
  </div>
</template>

<style scoped>
.fab {
  position: fixed; right: 24px; bottom: 24px;
  width: 56px; height: 56px; border-radius: 50%; border: none;
  background: var(--accent); color: var(--accent-fg);
  font-size: 1.4rem; cursor: pointer; box-shadow: var(--shadow-lg); z-index: 60;
}
.fab.open { background: var(--surface-2); color: var(--text); border: 1px solid var(--border); }

.panel {
  position: fixed; right: 24px; bottom: 92px;
  width: 360px; max-width: calc(100vw - 32px);
  height: 520px; max-height: calc(100vh - 128px);
  display: flex; flex-direction: column;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-lg); z-index: 60; overflow: hidden;
}
.phead {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.linkish { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 0.8rem; }
.stream-toggle { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; color: var(--muted); cursor: pointer; user-select: none; }
.stream-toggle input { width: auto; margin: 0; }
.ai-tag { font-size: 0.66rem; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
.ai-tag.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.ai-tag.off { background: var(--danger-soft); color: var(--danger); border-color: transparent; }

.pbody { flex: 1; overflow-y: auto; padding: 16px; }
.empty { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.chip {
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  border-radius: 999px; padding: 7px 13px; font-size: 0.82rem; cursor: pointer; text-align: left;
}
.chip:hover { border-color: var(--accent); }

.turn { margin-bottom: 14px; }
.turn.user { text-align: right; }
.bubble {
  display: inline-block; padding: 9px 13px; border-radius: 14px; max-width: 85%;
  text-align: left; white-space: pre-wrap; font-size: 0.88rem; background: var(--surface-2);
}
.turn.user .bubble { background: var(--accent-soft); color: var(--accent); }
.bubble.err { background: var(--danger-soft); color: var(--danger); }

.actions { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; }
.bug-btn { font-size: .8rem; padding: 5px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface-2, transparent); color: var(--text); font-weight: 600; }
.bug-btn:hover { border-color: var(--accent); }
.action {
  display: inline-flex; align-items: center; gap: 6px; font-size: 0.74rem;
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 999px; padding: 2px 9px;
}
.thinking { font-size: 0.85rem; }

.pfoot { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
.pinput {
  flex: 1; border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 9px 12px; background: var(--surface); color: var(--text); font-size: 0.88rem;
}
.send {
  border: none; background: var(--accent); color: var(--accent-fg);
  border-radius: var(--radius-sm); padding: 0 16px; cursor: pointer;
}
.send:disabled { opacity: 0.5; cursor: default; }

.asst-panel-enter-active, .asst-panel-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.asst-panel-enter-from, .asst-panel-leave-to { opacity: 0; transform: translateY(8px); }
@media (prefers-reduced-motion: reduce) {
  .asst-panel-enter-active, .asst-panel-leave-active { transition: none; }
}

/* On phones the panel docks as a full-height sheet. */
@media (max-width: 560px) {
  .panel {
    right: 0; left: 0; bottom: 0; top: 0;
    width: 100%; max-width: none; height: 100%; max-height: none;
    border: 0; border-radius: 0; z-index: 80;
  }
}
</style>
