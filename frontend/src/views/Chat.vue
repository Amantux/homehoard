<script setup>
import { ref, nextTick } from 'vue'
import { api } from '../api'

const msgs = ref([]) // { role: 'user'|'assistant', content, actions? }
const input = ref('')
const busy = ref(false)
const needsSetup = ref(false)
const sessionId = ref(null)
const body = ref(null)

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

async function send(text) {
  const message = (text ?? input.value).trim()
  if (!message || busy.value) return
  input.value = ''
  needsSetup.value = false
  msgs.value.push({ role: 'user', content: message })
  busy.value = true
  scrollDown()
  try {
    const r = await api.post('/chat', { message, sessionId: sessionId.value })
    sessionId.value = r.sessionId
    msgs.value.push({ role: 'assistant', content: r.reply, actions: r.actions || [] })
  } catch (e) {
    if (String(e.message || '').toLowerCase().includes('provider')) {
      needsSetup.value = true
      msgs.value.pop() // drop the unanswered user turn; the setup panel explains why
    } else {
      msgs.value.push({ role: 'assistant', content: '', error: e.message || 'Something went wrong.' })
    }
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
    <button v-if="msgs.length" class="secondary" @click="newChat">New chat</button>
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
          <span v-else style="white-space:pre-wrap">{{ m.content }}</span>
          <div v-if="m.actions && m.actions.length" class="chat-actions">
            <span v-for="(a, j) in m.actions" :key="j" class="chip">✓ {{ a.tool.replace(/_/g, ' ') }}</span>
          </div>
        </div>
      </div>
      <div v-if="busy" class="chat-row assistant"><div class="chat-bubble muted">Thinking…</div></div>
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
</style>
