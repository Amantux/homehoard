<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { useUI } from '../stores/ui'
import { useJobRunner } from '../composables/useJobRunner'

const ui = useUI()

// AI provider config — the LLM/SLM used for chat + tooling. Instance-global,
// overrides the add-on options. Only the instance admin (founding household owner)
// may read/edit it; others get 403, so we hide the card rather than show a form
// that can't save.
const PROVIDER_LABELS = {
  ollama: 'Ollama (self-hosted)',
  openai: 'OpenAI-compatible (incl. local SLMs)',
  claude: 'Anthropic Claude',
}
const ai = ref({ provider: '', baseUrl: '', model: '', apiKeySet: false, hasSearchKey: false, validProviders: [] })
const aiForm = ref({ provider: '', baseUrl: '', model: '', apiKey: '', ollamaSearchKey: '' })
const aiModels = ref([])
const aiSaving = ref(false)
const aiLoadingModels = ref(false)
const canEditAi = ref(false)

// Ollama + OpenAI point at a server (base URL); Claude is hosted (no base URL).
const needsBaseUrl = computed(() => ['ollama', 'openai'].includes(aiForm.value.provider))

async function loadAi() {
  try {
    ai.value = await api.get('/settings/ai')
    aiForm.value = { provider: ai.value.provider, baseUrl: ai.value.baseUrl,
      model: ai.value.model, apiKey: '', ollamaSearchKey: '' }
    canEditAi.value = true
  } catch (e) { canEditAi.value = false }
}

// Household default for streaming chat replies (owner-editable). Each browser can
// override it on the Assistant page; the default is classic POST.
const chatStreamDefault = ref(false)
const chatSaving = ref(false)
async function loadChatDefault() {
  try { chatStreamDefault.value = !!(await api.get('/settings/chat')).stream } catch (e) { /* keep default */ }
}
async function saveChatDefault(on) {
  chatSaving.value = true
  try {
    chatStreamDefault.value = !!(await api.put('/settings/chat', { stream: on })).stream
    ui.toast('Saved chat default')
  } catch (e) { ui.error(e.message || 'Could not save') } finally { chatSaving.value = false }
}
onMounted(loadChatDefault)
async function loadAiModels() {
  aiLoadingModels.value = true
  try {
    const r = await api.post('/settings/ai/models', {
      provider: aiForm.value.provider, baseUrl: aiForm.value.baseUrl, apiKey: aiForm.value.apiKey })
    aiModels.value = r.models || []
    if (!aiModels.value.length) ui.toast('No models returned — check the URL/key, or type the model name.')
  } catch (e) { ui.error(e.message || 'Could not list models') } finally { aiLoadingModels.value = false }
}
// Switching provider: drop the previous provider's URL/model/key from the form so
// they can't be saved under the new provider's namespace. (Save also omits blanks.)
watch(() => aiForm.value.provider, (next, prev) => {
  if (prev === undefined || next === prev) return
  // Returning to the currently-saved provider restores its loaded values.
  if (next === ai.value.provider) {
    aiForm.value.baseUrl = ai.value.baseUrl
    aiForm.value.model = ai.value.model
  } else {
    aiForm.value.baseUrl = ''
    aiForm.value.model = ''
  }
  aiForm.value.apiKey = ''
})

function _aiPayload(extra = {}) {
  // Always send the provider; send URL/model/keys only when non-blank, so an
  // untouched field never overwrites or cross-pollutes a saved value.
  const f = aiForm.value
  const p = { provider: f.provider, ...extra }
  if (f.baseUrl) p.baseUrl = f.baseUrl
  if (f.model) p.model = f.model
  if (f.apiKey) p.apiKey = f.apiKey
  if (f.ollamaSearchKey) p.ollamaSearchKey = f.ollamaSearchKey
  return p
}
async function saveAi() {
  aiSaving.value = true
  try {
    ai.value = await api.put('/settings/ai', _aiPayload())
    aiForm.value.apiKey = ''
    aiForm.value.ollamaSearchKey = ''
    ui.toast('AI provider saved')
  } catch (e) { ui.error(e.message || 'Save failed') } finally { aiSaving.value = false }
}
async function clearAiKey() {
  try {
    ai.value = await api.put('/settings/ai', _aiPayload({ clearApiKey: true }))
    aiForm.value.apiKey = ''
    ui.toast('Saved API key cleared')
  } catch (e) { ui.error(e.message || 'Could not clear key') }
}
onMounted(loadAi)

async function runAction(path, label) {
  const res = await api.post('/actions/' + path)
  ui.toast(`${label}: ${res.completed} updated`)
}

// Enrichment now runs as a background job (async, survives navigation). We enqueue
// and poll for progress; on mount we resume showing any job already running.
const enrichJob = ref(null)
const enrichForm = ref({ note: '', provider: '', model: '' })
const enrichStarting = ref(false)
let enrichTimer = null
const enrichActive = computed(() =>
  enrichJob.value && ['pending', 'running'].includes(enrichJob.value.status))

async function startEnrich() {
  if (enrichStarting.value) return
  enrichStarting.value = true
  const body = {}
  if (enrichForm.value.note.trim()) body.note = enrichForm.value.note.trim()
  if (enrichForm.value.provider) body.provider = enrichForm.value.provider
  if (enrichForm.value.model.trim()) body.model = enrichForm.value.model.trim()
  try {
    enrichJob.value = await api.post('/jobs/enrich', body)
    pollEnrich()
  } catch (e) { ui.error(e.message || 'Could not start enrichment.') }
  finally { enrichStarting.value = false }
}
let enrichPollFails = 0
async function pollEnrich() {
  if (!enrichJob.value) return
  const id = enrichJob.value.id
  try {
    enrichJob.value = await api.get(`/jobs/${id}`)
    enrichPollFails = 0
    if (enrichJob.value.status === 'done') {
      const r = enrichJob.value.result || {}
      ui.toast(`Described ${r.described ?? 0} item(s).` +
        (r.remaining ? ` ${r.remaining} still missing — run again to continue.` : ''))
      return
    }
    if (enrichJob.value.status === 'error') {
      ui.error(enrichJob.value.error || 'Enrichment failed.')
      return
    }
  } catch (e) {
    // Give up after a few consecutive failures (job gone / server down) rather
    // than spinning forever.
    if (++enrichPollFails >= 5) {
      enrichJob.value = null
      ui.error('Lost track of the enrichment job.')
      return
    }
  }
  enrichTimer = setTimeout(pollEnrich, 1500)
}
async function resumeEnrich() {
  try {
    const r = await api.get('/jobs?kind=enrich')
    const active = (r.items || []).find(j => ['pending', 'running'].includes(j.status))
    if (active) { enrichJob.value = active; pollEnrich() }
  } catch (e) { /* optional */ }
}
onMounted(resumeEnrich)
onUnmounted(() => clearTimeout(enrichTimer))

// AI organize: auto-categorize (label) items + propose clusters. Both are jobs.
const {
  job: catJob, starting: catStarting, active: catActive,
  start: startCategorize, resume: resumeCategorize, stop: stopCategorize,
} = useJobRunner('categorize', {
  onDone: (j) => j.status === 'error'
    ? ui.error(j.error || 'Categorize failed.')
    : ui.toast(`Categorize: ${j.result?.applied ?? 0} applied, ${j.result?.queued ?? 0} to review.`),
})
const {
  starting: cluStarting, active: cluActive,
  start: startCluster, resume: resumeCluster, stop: stopCluster,
} = useJobRunner('cluster', {
  onDone: (j) => j.status === 'error'
    ? ui.error(j.error || 'Clustering failed.')
    : ui.toast(`Found ${j.result?.proposed ?? 0} grouping(s) to review.`),
})
const organizeForm = ref({ note: '', model: '' })
function organizeBody() {
  const b = {}
  if (organizeForm.value.note.trim()) b.note = organizeForm.value.note.trim()
  if (organizeForm.value.model.trim()) b.model = organizeForm.value.model.trim()
  return b
}
onMounted(() => { resumeCategorize(); resumeCluster() })
onUnmounted(() => { stopCategorize(); stopCluster() })

const actions = [
  { p: 'ensure-asset-ids', l: 'Ensure asset IDs', d: 'Assign missing asset IDs' },
  { p: 'ensure-import-refs', l: 'Ensure import refs', d: 'Backfill import references' },
  { p: 'zero-item-time-fields', l: 'Zero time fields', d: 'Strip time from date fields' },
  { p: 'set-primary-photos', l: 'Set primary photos', d: 'Pick a primary photo per item' },
]
</script>

<template>
  <div class="page-head"><h1>Tools</h1></div>

  <div v-if="canEditAi" class="card">
    <h2>AI provider</h2>
    <p class="muted">The LLM or local SLM used for chat and tooling (AI descriptions,
      barcode identify). Set it here (overrides the add-on options) or in the add-on
      configuration. Pick <strong>OpenAI-compatible</strong> and a base URL to use a local
      model server (LM Studio, vLLM, llama.cpp, Ollama's <code>/v1</code>).</p>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Provider</span>
      <select v-model="aiForm.provider" style="width:100%;margin-top:4px">
        <option value="">Disabled</option>
        <option v-for="p in ai.validProviders" :key="p" :value="p">{{ PROVIDER_LABELS[p] || p }}</option>
      </select>
    </label>
    <label v-if="needsBaseUrl" style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Base URL</span>
      <input v-model="aiForm.baseUrl"
        :placeholder="aiForm.provider === 'ollama' ? 'http://localhost:11434' : 'http://localhost:1234/v1'"
        style="width:100%;margin-top:4px" />
    </label>
    <label v-if="aiForm.provider" style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Model</span>
      <input v-model="aiForm.model" list="ai-model-list" placeholder="model name" style="width:100%;margin-top:4px" />
      <datalist id="ai-model-list"><option v-for="m in aiModels" :key="m" :value="m" /></datalist>
      <button v-if="needsBaseUrl" class="secondary sm" style="margin-top:6px"
        :disabled="aiLoadingModels" @click="loadAiModels">
        {{ aiLoadingModels ? 'Listing…' : 'List models' }}</button>
    </label>
    <label v-if="aiForm.provider" style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">API key</span>
      <input v-model="aiForm.apiKey" type="password"
        :placeholder="aiForm.provider === 'ollama' ? 'optional for a local server' : 'provider API key'"
        style="width:100%;margin-top:4px" />
      <span v-if="ai.apiKeySet" class="muted" style="font-size:0.78rem">A key is saved — leave blank to keep it.
        <a href="#" style="color:var(--danger)" @click.prevent="clearAiKey">Clear saved key</a></span>
    </label>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Ollama web-search key (for enrichment)</span>
      <input v-model="aiForm.ollamaSearchKey" type="password" placeholder="ollama.com API key"
        style="width:100%;margin-top:4px" />
      <span v-if="ai.hasSearchKey" class="muted" style="font-size:0.78rem">A key is saved — leave blank to keep it.</span>
    </label>
    <p class="muted" style="font-size:0.8rem;max-width:520px">Enrichment's <em>web search</em> uses
      Ollama's hosted search (ollama.com) regardless of the provider above; the provider only
      writes the description.</p>
    <div class="row" style="justify-content:flex-end;max-width:520px">
      <button :disabled="aiSaving" @click="saveAi">{{ aiSaving ? 'Saving…' : 'Save' }}</button>
    </div>
  </div>

  <div v-if="canEditAi" class="card">
    <h2>Chat</h2>
    <p class="muted">Household default for how chat replies arrive. <strong>Stream</strong>
      shows the answer as it's written; <strong>classic</strong> shows it all at once. Each
      person can override this for their own browser on the Assistant page.</p>
    <label style="display:flex;gap:8px;align-items:center;max-width:520px">
      <input type="checkbox" style="width:auto" :checked="chatStreamDefault" :disabled="chatSaving"
        @change="saveChatDefault($event.target.checked)" />
      <span>Stream chat responses by default</span>
    </label>
  </div>

  <div class="card">
    <h2>AI descriptions</h2>
    <p class="muted">Look items up online (Ollama web search) and store a short searchable description,
      so search finds them by what they actually are. Needs an Ollama search key set in the add-on options
      (or <code>HBOX_OLLAMA_SEARCH_KEY</code>). Runs in the background — you can leave this page.
      Per-item, use ✨ Describe on the item page.</p>
    <div v-if="!enrichActive">
      <label style="display:block;max-width:520px;margin-bottom:8px">
        <span class="muted" style="font-size:0.85rem">Note (optional guidance for the AI)</span>
        <textarea v-model="enrichForm.note" rows="2"
          placeholder="e.g. these are camping items — note brand and model" style="width:100%;margin-top:4px"></textarea>
      </label>
      <div style="display:flex;gap:8px;max-width:520px;margin-bottom:10px">
        <label style="flex:1">
          <span class="muted" style="font-size:0.85rem">Model to use</span>
          <select v-model="enrichForm.provider" style="width:100%;margin-top:4px">
            <option value="">Default provider</option>
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI-compatible</option>
            <option value="claude">Anthropic Claude</option>
          </select>
        </label>
        <label style="flex:1">
          <span class="muted" style="font-size:0.85rem">Model name (optional)</span>
          <input v-model="enrichForm.model" placeholder="override model" style="width:100%;margin-top:4px" />
        </label>
      </div>
      <button class="secondary" :disabled="enrichStarting" @click="startEnrich">
        {{ enrichStarting ? 'Starting…' : '✨ Describe items missing a description' }}</button>
    </div>
    <div v-else style="max-width:520px">
      <div class="muted" style="font-size:0.85rem;margin-bottom:6px">
        Describing… {{ enrichJob.done }}<span v-if="enrichJob.total">/{{ enrichJob.total }}</span> items</div>
      <progress :value="enrichJob.done" :max="enrichJob.total || 1" style="width:100%"></progress>
    </div>
  </div>

  <div class="card">
    <h2>AI organize</h2>
    <p class="muted">Use your AI provider to auto-label items and propose groupings.
      Confident labels are applied automatically; the rest wait for your review, and
      your accept/reject choices teach later runs.</p>
    <div style="display:flex;gap:8px;max-width:520px;margin-bottom:10px">
      <label style="flex:2">
        <span class="muted" style="font-size:0.85rem">Note (optional guidance)</span>
        <input v-model="organizeForm.note" placeholder="e.g. group by room" style="width:100%;margin-top:4px" />
      </label>
      <label style="flex:1">
        <span class="muted" style="font-size:0.85rem">Model (optional)</span>
        <input v-model="organizeForm.model" placeholder="override model" style="width:100%;margin-top:4px" />
      </label>
    </div>
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
      <button class="secondary" :disabled="catStarting || catActive" @click="startCategorize(organizeBody())">
        {{ catActive ? `Categorizing… ${catJob.done}/${catJob.total || '…'}` : 'Auto-categorize items' }}
      </button>
      <button class="secondary" :disabled="cluStarting || cluActive" @click="startCluster(organizeBody())">
        {{ cluActive ? 'Finding groupings…' : 'Propose groupings' }}
      </button>
      <router-link to="/review" class="muted" style="font-size:.9rem">Review suggestions →</router-link>
    </div>
  </div>

  <div class="card">
    <h2>Inventory report</h2>
    <p class="muted">A valuation &amp; insurance summary of everything you own — totals by location and label,
      warranty status, and a photo appendix. Print to PDF or export CSV for your insurer.</p>
    <router-link to="/report"><button class="secondary">📄 Open inventory report</button></router-link>
  </div>

  <div class="card">
    <h2>Maintenance actions</h2>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">
      <div v-for="a in actions" :key="a.p" class="card" style="box-shadow:none">
        <h3>{{ a.l }}</h3>
        <p class="muted" style="font-size:0.85rem">{{ a.d }}</p>
        <button class="secondary sm" @click="runAction(a.p, a.l)">Run</button>
      </div>
    </div>
  </div>
</template>
