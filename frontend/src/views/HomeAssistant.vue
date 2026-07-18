<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { shortDate } from '../format'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'

const ui = useUI()

const tokens = ref([])
const loading = ref(true)
const creating = ref(false)
const newName = ref('')
// The raw token is returned by the API exactly once — held here until the user
// dismisses it, since it can never be shown again.
const revealed = ref(null)

async function load() {
  loading.value = true
  tokens.value = await api.get('/tokens')
  loading.value = false
}
onMounted(load)

async function create() {
  creating.value = true
  try {
    const t = await api.post('/tokens', { name: newName.value.trim() || 'Home Assistant' })
    revealed.value = t
    newName.value = ''
    await load()
  } catch (e) {
    ui.error(e.message)
  } finally {
    creating.value = false
  }
}

async function revoke(t) {
  if (!confirm(`Revoke the token “${t.name}”? Anything using it will stop working immediately.`))
    return
  await api.del('/tokens/' + t.id)
  ui.toast('Token revoked')
  await load()
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ui.toast('Copied to clipboard')
  } catch (e) {
    ui.error('Could not copy — select and copy manually.')
  }
}

// Best-effort MCP SSE URL for the Home Assistant "MCP Client" integration.
// The MCP server listens on 7766 regardless of how the app itself is reached.
const mcpUrl = computed(() => {
  const host = window.location.hostname || 'your-homehoard-host'
  return `http://${host}:7766/sse`
})
</script>

<template>
  <div class="page-head">
    <h1>🔌 Home Assistant</h1>
  </div>
  <p class="muted" style="margin:-8px 0 20px;max-width:640px">
    HomeHoard plugs into Home Assistant for inventory sensors, a warranties &amp;
    maintenance calendar, voice, and an AI chat assistant that can search your
    stuff and check things in and out.
  </p>

  <!-- Add-on users: zero-config reassurance -->
  <div class="card info-card" style="margin-bottom:16px">
    <strong>🎉 Running the HomeHoard add-on?</strong>
    <p class="muted" style="margin:6px 0 0">
      You’re already connected — Home Assistant auto-discovers the add-on and no
      token is needed. Everything below is only for connecting a
      <em>standalone</em> HomeHoard to Home Assistant.
    </p>
  </div>

  <!-- Chat & voice via MCP (the recommended path) -->
  <div class="card" style="margin-bottom:16px">
    <h2>Voice &amp; AI chat assistant</h2>
    <p class="muted" style="margin-top:0">
      The easiest way to talk to your inventory — <em>“where’s my drill?”</em>,
      <em>“check out the projector to Sam”</em> — is Home Assistant’s
      <strong>MCP Client</strong> with any LLM-powered Assist pipeline. It calls
      HomeHoard directly, so there are no sentences to install.
    </p>
    <ol class="steps">
      <li>In Home Assistant: <strong>Settings → Devices &amp; Services → Add
        Integration → Model Context Protocol</strong>.</li>
      <li>Point it at the HomeHoard MCP server:</li>
    </ol>
    <div class="code-row">
      <code>{{ mcpUrl }}</code>
      <button class="secondary sm" @click="copy(mcpUrl)">Copy</button>
    </div>
    <p class="muted" style="font-size:0.82rem;margin-bottom:0">
      Add-on installs expose this automatically. Standalone: run the bundled
      <code>mcp_server.py</code> (port 7766) and, if app auth is on, set
      <code>HBOX_MCP_API_TOKEN</code> to a token below.
    </p>
  </div>

  <!-- API tokens -->
  <div class="card">
    <div class="row" style="margin-bottom:6px">
      <h2 style="margin:0;flex:1">API tokens</h2>
    </div>
    <p class="muted" style="margin-top:0">
      Generate a token to connect a standalone HomeHoard when app authentication
      is enabled. Paste it into the HomeHoard integration’s “API token” field.
    </p>

    <!-- One-time reveal of a freshly created token -->
    <div v-if="revealed" class="reveal">
      <div class="row" style="gap:8px;align-items:flex-start">
        <span style="font-size:18px;line-height:1.2">🔑</span>
        <div style="flex:1;min-width:0">
          <strong>Copy your new token now — it won’t be shown again.</strong>
          <div class="code-row" style="margin-top:8px">
            <code class="tok">{{ revealed.token }}</code>
            <button class="sm" @click="copy(revealed.token)">Copy</button>
          </div>
        </div>
        <button class="ghost icon-btn" aria-label="Dismiss" @click="revealed = null">✕</button>
      </div>
    </div>

    <div class="row wrap" style="align-items:flex-end;gap:10px;margin:14px 0">
      <label class="field fill" style="margin:0;max-width:280px">
        <span>Token name</span>
        <input v-model="newName" placeholder="e.g. Home Assistant" @keyup.enter="create" />
      </label>
      <button :disabled="creating" @click="create">Generate token</button>
    </div>

    <div v-if="loading" class="skeleton" style="height:80px"></div>

    <table v-else-if="tokens.length">
      <thead>
        <tr><th>Name</th><th>Token</th><th>Created</th><th>Last used</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="t in tokens" :key="t.id">
          <td><strong>{{ t.name }}</strong></td>
          <td class="muted"><code>{{ t.hint }}…</code></td>
          <td class="muted">{{ shortDate(t.createdAt) }}</td>
          <td class="muted">{{ t.lastUsedAt ? shortDate(t.lastUsedAt) : 'Never' }}</td>
          <td style="text-align:right">
            <button class="danger secondary sm" @click="revoke(t)">Revoke</button>
          </td>
        </tr>
      </tbody>
    </table>

    <EmptyState v-else icon="🔑" title="No API tokens yet"
                hint="Generate one above to connect a standalone HomeHoard to Home Assistant." />
  </div>
</template>

<style scoped>
.info-card { border-left: 4px solid var(--accent); background: var(--accent-soft); }
.steps { margin: 8px 0 12px; padding-left: 20px; }
.steps li { margin-bottom: 4px; }
.code-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 8px 10px; margin: 8px 0;
}
.code-row code { flex: 1; min-width: 0; overflow-x: auto; white-space: nowrap; font-size: 0.85rem; }
.reveal {
  border: 1px solid var(--accent); background: var(--accent-soft);
  border-radius: var(--radius-sm); padding: 12px 14px; margin-top: 6px;
}
.reveal .code-row { background: var(--surface); }
.tok { user-select: all; font-weight: 600; }
</style>
