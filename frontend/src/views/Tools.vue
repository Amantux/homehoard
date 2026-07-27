<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { useUI } from '../stores/ui'

const ui = useUI()

// AI provider (Ollama) config — overrides the add-on options from the UI.
const ai = ref({ url: '', model: '', hasSearchKey: false })
const aiForm = ref({ ollamaUrl: '', ollamaModel: '', ollamaSearchKey: '' })
const aiSaving = ref(false)
// Only the instance admin (founding household owner) may read/edit shared AI infra;
// others get 403, so hide the card rather than show an editable form that can't save.
const canEditAi = ref(false)
async function loadAi() {
  try {
    ai.value = await api.get('/settings/ai')
    aiForm.value = { ollamaUrl: ai.value.url, ollamaModel: ai.value.model, ollamaSearchKey: '' }
    canEditAi.value = true
  } catch (e) { canEditAi.value = false }
}
async function saveAi() {
  aiSaving.value = true
  try {
    ai.value = await api.put('/settings/ai', aiForm.value)
    aiForm.value.ollamaSearchKey = ''
    ui.toast('AI settings saved')
  } catch (e) { ui.error(e.message || 'Save failed') } finally { aiSaving.value = false }
}
onMounted(loadAi)

async function runAction(path, label) {
  const res = await api.post('/actions/' + path)
  ui.toast(`${label}: ${res.completed} updated`)
}

const enriching = ref(false)
async function enrichMissing() {
  enriching.value = true
  try {
    const r = await api.post('/items/describe-missing', {})
    ui.toast(r.described ? `Described ${r.described} item(s).` : 'Nothing to describe.')
  } catch (e) { ui.error(e.message || 'Enrichment failed.') } finally { enriching.value = false }
}

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
    <p class="muted">The Ollama server used for AI descriptions and the barcode web-search
      fallback. Set it here (overrides the add-on options) or in the add-on configuration.
      The <strong>search key</strong> is your ollama.com API key for hosted web search.</p>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Ollama URL</span>
      <input v-model="aiForm.ollamaUrl" placeholder="http://localhost:11434" style="width:100%;margin-top:4px" />
    </label>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Model</span>
      <input v-model="aiForm.ollamaModel" placeholder="llama3.1" style="width:100%;margin-top:4px" />
    </label>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Ollama search key {{ ai.hasSearchKey ? '— saved, leave blank to keep' : '' }}</span>
      <input v-model="aiForm.ollamaSearchKey" type="password"
        :placeholder="ai.hasSearchKey ? '•••••••••• saved' : 'ollama.com API key'" style="width:100%;margin-top:4px" />
    </label>
    <div class="row" style="justify-content:flex-end;max-width:520px">
      <button :disabled="aiSaving" @click="saveAi">{{ aiSaving ? 'Saving…' : 'Save' }}</button>
    </div>
  </div>

  <div class="card">
    <h2>AI descriptions</h2>
    <p class="muted">Look items up online (Ollama web search) and store a short searchable description,
      so search finds them by what they actually are. Needs an Ollama search key set in the add-on options
      (or <code>HBOX_OLLAMA_SEARCH_KEY</code>). Per-item, use ✨ Describe on the item page.</p>
    <button class="secondary" :disabled="enriching" @click="enrichMissing">
      {{ enriching ? 'Describing…' : '✨ Describe items missing a description' }}</button>
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
