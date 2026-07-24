<script setup>
import { ref, onMounted, computed } from 'vue'
import { api, apiUrl, getToken } from '../api'
import { useUI } from '../stores/ui'

const ui = useUI()
const report = ref(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true; error.value = ''
  try { report.value = await api.get('/reports/inventory') }
  catch (e) { error.value = e.message || 'Could not load the report.' }
  finally { loading.value = false }
}
onMounted(load)

const cur = computed(() => (report.value?.currency || 'usd').toUpperCase())
function money(v) {
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur.value }).format(v || 0) }
  catch (e) { return (v || 0).toFixed(2) }
}
const WLABEL = { lifetime: 'Lifetime', active: 'Active', expiring: 'Expiring soon', expired: 'Expired', none: '—' }
function wlabel(s) { return WLABEL[s] || s }

const generated = computed(() => {
  const d = report.value?.generatedAt
  return d ? new Date(d).toLocaleString() : ''
})
const photoItems = computed(() => (report.value?.items || []).filter((i) => i.imageId))

function printPage() { window.print() }
async function downloadCsv() {
  try {
    const res = await fetch(apiUrl('/reports/inventory.csv'), { headers: getToken() ? { Authorization: getToken() } : {} })
    if (!res.ok) throw new Error('failed')
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url; a.download = 'homehoard-inventory-report.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { ui.error('Could not download the CSV.') }
}
</script>

<template>
  <div class="page-head">
    <h1>Inventory report</h1>
    <div class="grow"></div>
    <div class="no-print" style="display:flex;gap:8px">
      <button class="secondary" @click="downloadCsv">⬇️ CSV</button>
      <button @click="printPage">🖨️ Print / Save as PDF</button>
    </div>
  </div>

  <div v-if="loading" class="card muted">Loading your inventory report…</div>

  <div v-else-if="error" class="card" style="border-color:var(--danger,#c0392b)">
    <strong>Couldn’t load the report.</strong> <span class="muted">{{ error }}</span>
    <button class="secondary sm no-print" style="margin-left:8px" @click="load">Retry</button>
  </div>

  <div v-else-if="report && report.summary.totalItems === 0" class="card">
    <h2>No items yet</h2>
    <p class="muted">Add items with a purchase price to build a valuation you can hand to your insurer.</p>
    <router-link to="/items" class="no-print"><button>Go to items</button></router-link>
  </div>

  <div v-else-if="report" class="report">
    <p class="muted" style="margin-top:-4px">Documented value (purchase price × quantity) · generated {{ generated }}</p>

    <!-- Summary -->
    <div class="sum-grid">
      <div class="sum"><div class="v">{{ money(report.summary.totalValue) }}</div><div class="l">Total value</div></div>
      <div class="sum"><div class="v">{{ money(report.summary.insuredValue) }}</div><div class="l">Insured ({{ report.summary.insuredCount }} items)</div></div>
      <div class="sum"><div class="v">{{ money(report.summary.uninsuredValue) }}</div><div class="l">Not insured</div></div>
      <div class="sum"><div class="v">{{ report.summary.totalItems }}</div><div class="l">Items</div></div>
    </div>

    <div class="card">
      <strong>Warranty:</strong>
      <span class="chip">{{ report.summary.warranty.active + report.summary.warranty.lifetime }} covered</span>
      <span class="chip">{{ report.summary.warranty.expiring }} expiring soon</span>
      <span class="chip">{{ report.summary.warranty.expired }} expired</span>
      <span class="chip">{{ report.summary.warranty.none }} none</span>
    </div>

    <!-- Breakdowns -->
    <div class="cols">
      <div class="card">
        <h2>By location</h2>
        <table v-if="report.byLocation.length">
          <thead><tr><th>Location</th><th class="num">Items</th><th class="num">Value</th></tr></thead>
          <tbody>
            <tr v-for="b in report.byLocation" :key="b.name"><td>{{ b.name }}</td><td class="num">{{ b.count }}</td><td class="num">{{ money(b.value) }}</td></tr>
          </tbody>
        </table>
        <p v-else class="muted">No items assigned to a location.</p>
      </div>
      <div class="card">
        <h2>By label</h2>
        <table v-if="report.byLabel.length">
          <thead><tr><th>Label</th><th class="num">Items</th><th class="num">Value</th></tr></thead>
          <tbody>
            <tr v-for="b in report.byLabel" :key="b.name"><td>{{ b.name }}</td><td class="num">{{ b.count }}</td><td class="num">{{ money(b.value) }}</td></tr>
          </tbody>
        </table>
        <p v-else class="muted">No labelled items.</p>
      </div>
    </div>

    <!-- Full item list -->
    <div class="card">
      <h2>Items ({{ report.items.length }})</h2>
      <table class="items">
        <thead><tr>
          <th>Item</th><th>Location</th><th>Serial</th><th>Purchased</th>
          <th class="num">Qty</th><th class="num">Unit</th><th class="num">Value</th><th>Insured</th><th>Warranty</th>
        </tr></thead>
        <tbody>
          <tr v-for="it in report.items" :key="it.id">
            <td><strong>{{ it.name }}</strong></td>
            <td>{{ it.location || '—' }}</td>
            <td class="muted">{{ it.serialNumber || '—' }}</td>
            <td>{{ it.purchaseDate ? it.purchaseDate.slice(0,10) : '—' }}</td>
            <td class="num">{{ it.quantity }}</td>
            <td class="num">{{ money(it.purchasePrice) }}</td>
            <td class="num">{{ money(it.lineValue) }}</td>
            <td>{{ it.insured ? '✓' : '—' }}</td>
            <td>{{ wlabel(it.warrantyStatus) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Photo appendix -->
    <div class="card" v-if="photoItems.length">
      <h2>Photos ({{ photoItems.length }})</h2>
      <div class="photos">
        <figure v-for="it in photoItems" :key="it.id">
          <img :src="apiUrl('/documents/' + it.imageId)" alt="" loading="lazy"
            @error="$event.target.style.display='none'" />
          <figcaption>{{ it.name }} · {{ money(it.lineValue) }}</figcaption>
        </figure>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sum-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:14px; }
.sum { border:1px solid var(--border,#e2e2e2); border-radius:8px; padding:14px 16px; background:var(--surface-raised,#fafafa); }
.sum .v { font-size:1.5rem; font-weight:650; font-variant-numeric:tabular-nums; }
.sum .l { color:var(--muted,#777); font-size:0.82rem; margin-top:2px; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
@media (max-width:640px){ .cols{ grid-template-columns:1fr; } }
table { width:100%; border-collapse:collapse; font-size:0.9rem; }
th, td { text-align:left; padding:5px 8px; border-bottom:1px solid var(--border,#eee); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.chip { display:inline-block; margin-right:6px; padding:2px 8px; border-radius:999px; background:var(--surface-raised,#f0f0f0); font-size:0.8rem; }
.photos { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; }
.photos figure { margin:0; }
.photos img { width:100%; height:120px; object-fit:cover; border-radius:6px; border:1px solid var(--border,#e2e2e2); }
.photos figcaption { font-size:0.78rem; color:var(--muted,#777); margin-top:4px; }
</style>
