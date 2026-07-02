<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { money } from '../format'
import ItemCard from '../components/ItemCard.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const router = useRouter()

const items = ref([])
const total = ref(0)
const loading = ref(true)
const locations = ref([])
const labels = ref([])

const q = ref(route.query.q || '')
const locationFilter = ref('')
const labelFilter = ref('')
const orderBy = ref('name')
const includeArchived = ref(false)
const view = ref(localStorage.getItem('easyinv_itemview') || 'grid')
const page = ref(1)
const pageSize = 24

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function setView(v) {
  view.value = v
  localStorage.setItem('easyinv_itemview', v)
}

async function load() {
  loading.value = true
  const params = new URLSearchParams()
  if (q.value) params.set('q', q.value)
  if (locationFilter.value) params.set('locations', locationFilter.value)
  if (labelFilter.value) params.set('labels', labelFilter.value)
  if (includeArchived.value) params.set('includeArchived', 'true')
  params.set('orderBy', orderBy.value)
  params.set('page', page.value)
  params.set('pageSize', pageSize)
  const res = await api.get('/items?' + params.toString())
  items.value = res.items
  total.value = res.total
  loading.value = false
}

let timer
watch([q, locationFilter, labelFilter, orderBy, includeArchived], () => {
  page.value = 1
  clearTimeout(timer)
  timer = setTimeout(load, 250)
})
watch(page, load)
watch(() => route.query.q, (v) => { if (v !== q.value) { q.value = v || '' } })

onMounted(async () => {
  ;[locations.value, labels.value] = await Promise.all([
    api.get('/locations'),
    api.get('/labels'),
  ])
  await load()
})
</script>

<template>
  <div class="page-head">
    <h1>Items</h1>
    <span class="badge">{{ total }}</span>
    <div class="grow"></div>
    <div class="row" style="gap:2px;border:1px solid var(--border);border-radius:9px;padding:2px">
      <button class="sm" :class="view === 'grid' ? '' : 'ghost'" @click="setView('grid')">▦</button>
      <button class="sm" :class="view === 'table' ? '' : 'ghost'" @click="setView('table')">☰</button>
    </div>
  </div>

  <div class="toolbar">
    <div style="position:relative;flex:1;min-width:200px;max-width:340px">
      <input v-model="q" placeholder="Search…" />
    </div>
    <select v-model="locationFilter" style="width:auto">
      <option value="">All locations</option>
      <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
    </select>
    <select v-model="labelFilter" style="width:auto">
      <option value="">All labels</option>
      <option v-for="l in labels" :key="l.id" :value="l.id">{{ l.name }}</option>
    </select>
    <select v-model="orderBy" style="width:auto">
      <option value="name">Name</option>
      <option value="createdAt">Newest</option>
      <option value="updatedAt">Recently updated</option>
      <option value="purchasePrice">Price</option>
    </select>
    <label class="row" style="gap:6px;font-size:0.85rem">
      <input type="checkbox" v-model="includeArchived" /> Archived
    </label>
  </div>

  <div v-if="loading" class="card-grid">
    <div v-for="i in 8" :key="i" class="skeleton" style="height:190px"></div>
  </div>

  <template v-else-if="items.length">
    <div v-if="view === 'grid'" class="card-grid">
      <ItemCard v-for="i in items" :key="i.id" :item="i" />
    </div>
    <div v-else class="card card-flush">
      <table>
        <thead>
          <tr><th>Name</th><th>Location</th><th>Labels</th><th>Qty</th><th>Price</th><th>Asset</th></tr>
        </thead>
        <tbody>
          <tr v-for="i in items" :key="i.id" class="clickable" @click="router.push('/items/' + i.id)">
            <td><strong>{{ i.name }}</strong>
              <div class="muted" style="font-size:0.8rem">{{ i.description }}</div></td>
            <td>{{ i.bin ? '🗃️ ' + i.bin.name : (i.location?.name || '—') }}</td>
            <td><span v-for="l in i.labels" :key="l.id" class="chip"
                :style="l.color ? { background: l.color+'22', color: l.color } : {}">{{ l.name }}</span></td>
            <td>{{ i.quantity }}</td>
            <td>{{ money(i.purchasePrice) }}</td>
            <td class="muted">{{ i.assetId }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="pages > 1" class="row" style="justify-content:center;margin-top:20px;gap:10px">
      <button class="secondary sm" :disabled="page <= 1" @click="page--">← Prev</button>
      <span class="muted">Page {{ page }} / {{ pages }}</span>
      <button class="secondary sm" :disabled="page >= pages" @click="page++">Next →</button>
    </div>
  </template>

  <div v-else class="card">
    <EmptyState icon="🔍" title="No items found"
                hint="Try clearing filters or create a new item." />
  </div>
</template>
