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
// DB-target helper: what this instance runs on, so the sibling add-ons can be
// pointed at the same Postgres. Owner-only; never includes user/password.
const dbTarget = ref(null)
const envVars = ['HBOX_DATABASE_URL (HomeHoard)', 'EDIBL_DATABASE_URL (Edibl)', 'MYMEAL_DATABASE_URL (myMeal)']
onMounted(async () => {
  try { dbBackend.value = (await api.get('/status')).dbBackend || 'sqlite' } catch (e) { /* leave default */ }
  try { dbTarget.value = await api.get('/db/target') } catch (e) { /* owner-only; hide the card */ }
})
function copyDbCoords() {
  const t = dbTarget.value
  if (!t || t.backend !== 'postgresql') return
  navigator.clipboard.writeText(`host=${t.host} port=${t.port} database=${t.database}`).then(
    () => ui.toast('Copied host/port/database (no password)'),
    () => ui.error('Could not copy to clipboard'))
}
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
</script>

<template>
  <div class="page-head"><h1>Database</h1></div>

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
  <div class="card" v-else>
    <h2>PostgreSQL</h2>
    <p class="muted" style="margin:0">HomeHoard is running on an external PostgreSQL database.</p>
  </div>

  <div class="card" v-if="dbTarget">
    <h2>Share this database with your other apps</h2>
    <template v-if="dbTarget.backend === 'postgresql'">
      <p class="muted" style="max-width:560px">Edibl, HomeHoard, and myMeal can share one PostgreSQL
        server (separate databases, or the same — each app keeps its own tables). Point each add-on's
        database option at this server so they're backed up and managed together.</p>
      <div class="row" style="gap:8px;align-items:center;max-width:560px;flex-wrap:wrap">
        <code style="padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface-2)">host={{ dbTarget.host }} · port={{ dbTarget.port }} · database={{ dbTarget.database }}</code>
        <button class="secondary" @click="copyDbCoords">📋 Copy</button>
      </div>
      <p class="muted" style="font-size:0.82rem;margin-top:8px">The username and password are never
        shown here — reuse the same credentials you set for this app. In each add-on's config set:</p>
      <ul class="muted" style="font-size:0.82rem;margin:4px 0 0;padding-left:20px">
        <li v-for="v in envVars" :key="v"><code>{{ v }}</code></li>
      </ul>
    </template>
    <template v-else>
      <p class="muted" style="max-width:560px;margin:0">This instance runs on its built-in
        <strong>SQLite</strong> file, which lives inside this add-on and can't be shared with Edibl or
        myMeal. To put all three on one database, migrate to PostgreSQL above, then set each app's
        <code>*_DATABASE_URL</code> to that same server.</p>
    </template>
  </div>
</template>
