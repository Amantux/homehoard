<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { api, streamPost } from '../api'

const msgs = ref([]) // { role: 'user'|'assistant', content, actions?, error? }
const input = ref('')
const busy = ref(false)
const needsSetup = ref(false)
const sessionId = ref(null)
const body = ref(null)

// Transport choice: per-browser override (localStorage) wins over the household
// default (backend), which defaults to classic POST. See docs/chat-and-providers.md.
const STREAM_KEY = 'hbox_chat_stream'
const householdDefault = ref(false)
const override = ref(readOverride())
const streaming = computed(() =>
  override.value === null ? householdDefault.value : override.value)

function readOverride() {
  const v = localStorage.getItem(STREAM_KEY)
  if (v === 'true') return true
  if (v === 'false') return false
  return null
}
function setStreaming(on) {
  override.value = !!on
  localStorage.setItem(STREAM_KEY, on ? 'true' : 'false')
}

onMounted(async () => {
  try {
    const s = await api.get('/settings/chat')
    householdDefault.value = !!s.stream
  } catch (e) { /* default stays false */ }
})

const suggestions = [
  'Where is my drill?',
  'What do I have in the garage?',
  'Search for winter clothes',
  'List my labels',
]

async function scrollDown() {
  await nextTick()
  if (body.value) body.value.scrollTop = body.value.scrollHeight
}

function handleError(e) {
  if (String(e.message || '').toLowerCase().includes('provider')) {
    needsSetup.value = true
    if (msgs.value.length && msgs.value[msgs.value.length - 1].role === 'assistant'
        && !msgs.value[msgs.value.length - 1].content) {
      msgs.value.pop() // drop the empty streaming placeholder
    }
    msgs.value.pop() // drop the unanswered user turn; the setup panel explains why
  } else {
    msgs.value.push({ role: 'assistant', content: '', error: e.message || 'Something went wrong.' })
  }
}

async function sendPost(message) {
  const r = await api.post('/chat', { message, sessionId: sessionId.value })
  sessionId.value = r.sessionId
  msgs.value.push({ role: 'assistant', content: r.reply, actions: r.actions || [] })
}

async function sendStream(message) {
  msgs.value.push({ role: 'assistant', content: '', actions: [] })
  const idx = msgs.value.length - 1 // mutate via the reactive proxy, not the raw object
  let errored = null
  try {
    await streamPost('/chat/stream', { message, sessionId: sessionId.value }, (ev) => {
      const a = msgs.value[idx]
      if (ev.type === 'delta') { a.content += ev.text; scrollDown() }
      else if (ev.type === 'done') {
        sessionId.value = ev.sessionId
        a.content = ev.reply || a.content
        a.actions = ev.actions || []
      } else if (ev.type === 'error') { errored = new Error(ev.error || 'Something went wrong.') }
    })
  } catch (e) {
    // Transport-level failure (connection dropped): drop the empty placeholder so
    // it doesn't linger above the error bubble send() will push.
    if (!msgs.value[idx].content) msgs.value.splice(idx, 1)
    throw e
  }
  if (errored) {
    msgs.value.pop() // remove the streaming placeholder before showing the error
    throw errored
  }
}

async function send(text) {
  const message = (text ?? input.value).trim()
  if (!message || busy.value) return
  input.value = ''
  needsSetup.value = false
  msgs.value.push({ role: 'user', content: message })
  busy.value = true
  scrollDown()
  try {
    if (streaming.value) await sendStream(message)
    else await sendPost(message)
  } catch (e) {
    handleError(e)
  } finally {
    busy.value = false
    scrollDown()
  }
}

function newChat() {
  msgs.value = []
  sessionId.value = null
  needsSetup.value = false
}
</script>

<template>
  <div class="page-head">
    <h1>Assistant</h1>
    <div style="display:flex;gap:12px;align-items:center">
      <label class="stream-toggle" title="Stream the reply token-by-token (this browser)">
        <input type="checkbox" :checked="streaming" @change="setStreaming($event.target.checked)" />
        Stream replies
      </label>
      <button v-if="msgs.length" class="secondary" @click="newChat">New chat</button>
    </div>
  </div>

  <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 170px);min-height:420px">
    <!-- Not configured: point the admin at the provider settings -->
    <div v-if="needsSetup" class="empty-state" style="margin:auto;text-align:center;max-width:420px">
      <div style="font-size:2rem">🤖</div>
      <p>No AI provider is set up yet. An instance admin can wire one up in
        <router-link to="/tools">Tools → AI provider</router-link> (Ollama, a local
        OpenAI-compatible model, or Claude).</p>
    </div>

    <!-- Empty: suggestion chips -->
    <div v-else-if="!msgs.length" class="empty-state" style="margin:auto;text-align:center;max-width:480px">
      <div style="font-size:2rem">💬</div>
      <p class="muted">Ask about your inventory — where something is, what's in a location,
        or to tag an item.</p>
      <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:12px">
        <button v-for="s in suggestions" :key="s" class="secondary sm" @click="send(s)">{{ s }}</button>
      </div>
    </div>

    <!-- Conversation -->
    <div v-else ref="body" style="flex:1;overflow-y:auto;padding:4px 2px">
      <div v-for="(m, i) in msgs" :key="i" class="chat-row" :class="m.role">
        <div class="chat-bubble" :class="{ error: m.error }">
          <span v-if="m.error" class="danger">{{ m.error }}</span>
          <span v-else-if="m.content" style="white-space:pre-wrap">{{ m.content }}</span>
          <span v-else class="muted">…</span>
          <div v-if="m.actions && m.actions.length" class="chat-actions">
            <span v-for="(a, j) in m.actions" :key="j" class="chip">✓ {{ a.tool.replace(/_/g, ' ') }}</span>
          </div>
        </div>
      </div>
      <div v-if="busy && !streaming" class="chat-row assistant"><div class="chat-bubble muted">Thinking…</div></div>
    </div>

    <form style="display:flex;gap:8px;margin-top:12px" @submit.prevent="send()">
      <input v-model="input" :disabled="busy" placeholder="Ask the assistant…"
        style="flex:1" aria-label="Message" />
      <button type="submit" :disabled="busy || !input.trim()">Send</button>
    </form>
  </div>
</template>

<style scoped>
.chat-row { display:flex; margin:8px 0; }
.chat-row.user { justify-content:flex-end; }
.chat-bubble {
  max-width:75%; padding:10px 12px; border-radius:12px; line-height:1.4;
  background:var(--surface-raised, #f1f3f5); border:1px solid var(--border);
}
/* User turns are distinguished by right-alignment + a soft accent tint — the full
   accent stays reserved for the Send button and links (design-system scarcity). */
.chat-row.user .chat-bubble { background:rgba(13,148,136,0.10); border-color:rgba(13,148,136,0.35); }
.chat-bubble.error { border-color:var(--danger); }
.chat-actions { margin-top:6px; display:flex; flex-wrap:wrap; gap:6px; }
.chip {
  font-size:.75rem; padding:2px 8px; border-radius:999px;
  background:var(--surface, #fff); border:1px solid var(--border); color:var(--text);
}
.stream-toggle {
  display:flex; align-items:center; gap:6px; font-size:.85rem; color:var(--muted);
  cursor:pointer; user-select:none;
}
.stream-toggle input { width:auto; }
</style>
