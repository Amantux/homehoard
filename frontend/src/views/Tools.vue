<script setup>
import { ref, onMounted } from 'vue'
import { api, getToken, apiUrl } from '../api'
import { useUI } from '../stores/ui'

const ui = useUI()
const busy = ref(false)

// Migrate to PostgreSQL: copy the whole SQLite DB into an empty Postgres.
const dbBackend = ref('sqlite')
const pgUrl = ref('')
const pgBusy = ref(false)
const pgResult = ref(null)
onMounted(async () => {
  try { dbBackend.value = (await api.get('/status')).dbBackend || 'sqlite' } catch (e) { /* leave default */ }
})
async function migratePg() {
  if (!pgUrl.value.trim()) return
  if (!confirm('Copy all data into this PostgreSQL database? It must be empty. Your current SQLite data is left untouched.')) return
  pgBusy.value = true; pgResult.value = null
  try {
    pgResult.value = await api.post('/migrate/postgres', { targetUrl: pgUrl.value.trim() })
    ui.toast(`Copied ${pgResult.value.total} rows`)
  } catch (err) {
    ui.error('Migration failed: ' + (err.message || 'error'))
  } finally { pgBusy.value = false }
}

async function doImport(e) {
  const file = e.target.files[0]
  if (!file) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('csv', file)
    const res = await api.upload('/items/import', form)
    ui.toast(`Imported ${res.imported} items`)
  } catch (err) {
    ui.error('Import failed: ' + err.message)
  } finally {
    busy.value = false
    e.target.value = ''
  }
}

async function doExport() {
  const res = await fetch(apiUrl('/items/export'), {
    headers: getToken() ? { Authorization: getToken() } : {},
  })
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = 'homehoard.csv'
  a.click()
  URL.revokeObjectURL(url)
  ui.toast('Export downloaded')
}

async function runAction(path, label) {
  const res = await api.post('/actions/' + path)
  ui.toast(`${label}: ${res.completed} updated`)
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

  <div class="card">
    <h2>Import / Export</h2>
    <p class="muted">CSV format is compatible with homebox (<code>HB.*</code> columns).</p>
    <div class="row" style="max-width:420px">
      <label class="btn" style="flex:1;justify-content:center;cursor:pointer">
        ⬆️ Import CSV
        <input type="file" accept=".csv,.tsv" hidden @change="doImport" :disabled="busy" />
      </label>
      <button class="secondary" style="flex:1;justify-content:center" @click="doExport">⬇️ Export CSV</button>
    </div>
  </div>

  <div class="card" v-if="dbBackend === 'sqlite'">
    <h2>Migrate to PostgreSQL</h2>
    <p class="muted">HomeHoard runs on its built-in SQLite (recommended for most). To move to an external
      PostgreSQL, enter an <strong>empty</strong> Postgres database — HomeHoard copies everything across,
      leaving your SQLite data untouched. Then set <code>HBOX_DATABASE_URL</code> to the same URL and restart.</p>
    <label style="display:block;max-width:520px;margin-bottom:10px">
      <span class="muted" style="font-size:0.85rem">Target PostgreSQL URL</span>
      <input v-model="pgUrl" placeholder="postgresql+psycopg://user:pass@host:5432/dbname"
        style="width:100%;margin-top:4px" />
    </label>
    <button class="secondary" :disabled="pgBusy || !pgUrl.trim()" @click="migratePg">
      {{ pgBusy ? 'Migrating…' : 'Migrate data' }}</button>
    <p v-if="pgResult" class="muted" style="margin-top:10px">✓ Copied {{ pgResult.total }} rows. {{ pgResult.next }}</p>
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
