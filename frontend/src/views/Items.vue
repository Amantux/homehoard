<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { money } from '../format'
import { useUI } from '../stores/ui'
import ItemCard from '../components/ItemCard.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()

const items = ref([])
const total = ref(0)
const loading = ref(true)
const locations = ref([])
const bins = ref([])
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
const hasFilters = computed(
  () => !!(q.value || locationFilter.value || labelFilter.value || includeArchived.value),
)

// --- Bulk selection -------------------------------------------------------
// Selection is scoped to the items currently loaded (this page). Any change to
// the filters or page reloads the list and clears the selection, so a bulk
// action can never touch an item the user can't see.
const selected = ref(new Set())
const moveTarget = ref('')
const labelTarget = ref('')
const busy = ref(false)

const selectedItems = computed(() => items.value.filter((i) => selected.value.has(i.id)))
const allOnPageSelected = computed(
  () => items.value.length > 0 && items.value.every((i) => selected.value.has(i.id)),
)
const someSelected = computed(() => selected.value.size > 0 && !allOnPageSelected.value)

function isSelected(id) {
  return selected.value.has(id)
}
function toggle(id) {
  const next = new Set(selected.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selected.value = next
}
function toggleAll() {
  selected.value = allOnPageSelected.value
    ? new Set()
    : new Set(items.value.map((i) => i.id))
}
function clearSelection() {
  selected.value = new Set()
}

function setView(v) {
  view.value = v
  localStorage.setItem('easyinv_itemview', v)
}

function resetFilters() {
  q.value = ''
  locationFilter.value = ''
  labelFilter.value = ''
  includeArchived.value = false
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
  clearSelection()
  loading.value = false
}

// --- Bulk actions ---------------------------------------------------------
// The API has no batch endpoint; at home-inventory scale a handful of
// sequential PATCH/DELETE calls is fine. We run them in order, then reload.
async function runBulk(label, fn) {
  const targets = selectedItems.value
  if (!targets.length || busy.value) return
  busy.value = true
  let ok = 0
  try {
    for (const it of targets) {
      await fn(it)
      ok++
    }
    ui.toast(`${label} ${ok} item${ok === 1 ? '' : 's'}`)
  } catch (e) {
    // Persistent error toast (see ui.toast): names how many succeeded so a
    // partial failure can't be missed. Successful items are reflected by the
    // reload below; the rest keep their old state.
    ui.error(`${label} failed after ${ok} of ${targets.length}: ${e.message}`)
  } finally {
    // Reload (which clears the selection) BEFORE re-enabling controls, so the
    // action bar can't re-fire against an already-applied selection.
    try {
      await load()
    } finally {
      busy.value = false
    }
  }
}

async function moveSelected() {
  const val = moveTarget.value
  moveTarget.value = ''
  if (!val) return
  const [kind, id] = val.split(':')
  const dest = (kind === 'bin' ? bins.value : locations.value).find((x) => x.id === id)
  const name = dest?.name || 'destination'
  const patch = kind === 'bin' ? { binId: id } : { binId: null, locationId: id }
  const prefix = kind === 'bin' ? '🗃️ ' : '📍 '
  await runBulk(`Moved to ${prefix}${name} —`, (it) => api.patch('/items/' + it.id, patch))
}

async function labelSelected() {
  const id = labelTarget.value
  labelTarget.value = ''
  if (!id) return
  const name = labels.value.find((l) => l.id === id)?.name || 'label'
  await runBulk(`Labelled “${name}” —`, (it) => {
    const ids = Array.from(new Set([...(it.labels || []).map((l) => l.id), id]))
    return api.patch('/items/' + it.id, { labelIds: ids })
  })
}

async function archiveSelected() {
  const n = selectedItems.value.length
  if (!confirm(`Archive ${n} item${n === 1 ? '' : 's'}? They’ll be hidden from the default list, not deleted.`))
    return
  await runBulk('Archived', (it) => api.patch('/items/' + it.id, { archived: true }))
}

async function deleteSelected() {
  const n = selectedItems.value.length
  if (!confirm(`Delete ${n} item${n === 1 ? '' : 's'}? This can’t be undone.`)) return
  await runBulk('Deleted', (it) => api.del('/items/' + it.id))
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
  ;[locations.value, labels.value, bins.value] = await Promise.all([
    api.get('/locations'),
    api.get('/labels'),
    api.get('/bins'),
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
      <button class="sm" :class="view === 'grid' ? '' : 'ghost'" title="Grid view"
              aria-label="Grid view" @click="setView('grid')">▦</button>
      <button class="sm" :class="view === 'table' ? '' : 'ghost'" title="Table view"
              aria-label="Table view" @click="setView('table')">☰</button>
    </div>
    <button @click="ui.openCreate('item')">＋ New item</button>
  </div>

  <div class="toolbar">
    <div style="position:relative;flex:1;min-width:200px;max-width:340px">
      <input v-model="q" placeholder="Search…" aria-label="Search items" />
    </div>
    <select v-model="locationFilter" style="width:auto" aria-label="Filter by location">
      <option value="">All locations</option>
      <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
    </select>
    <select v-model="labelFilter" style="width:auto" aria-label="Filter by label">
      <option value="">All labels</option>
      <option v-for="l in labels" :key="l.id" :value="l.id">{{ l.name }}</option>
    </select>
    <select v-model="orderBy" style="width:auto" aria-label="Sort by">
      <option value="name">Name</option>
      <option value="createdAt">Newest</option>
      <option value="updatedAt">Recently updated</option>
      <option value="purchasePrice">Price</option>
    </select>
    <label class="row" style="gap:6px;font-size:0.85rem">
      <input type="checkbox" v-model="includeArchived" /> Archived
    </label>
    <button v-if="hasFilters" class="ghost sm" @click="resetFilters">Clear filters</button>
  </div>

  <!-- Bulk action bar: appears when one or more items are selected -->
  <div v-if="selected.size" class="bulk-bar" role="region" aria-label="Bulk actions">
    <button class="ghost icon-btn" title="Clear selection" aria-label="Clear selection"
            @click="clearSelection">✕</button>
    <strong>{{ selected.size }} selected</strong>
    <div class="grow"></div>
    <select v-model="moveTarget" :disabled="busy" aria-label="Move selected to"
            style="width:auto" @change="moveSelected">
      <option value="">Move to…</option>
      <optgroup label="Bins">
        <option v-for="b in bins" :key="'b' + b.id" :value="'bin:' + b.id">🗃️ {{ b.name }}</option>
      </optgroup>
      <optgroup label="Locations">
        <option v-for="l in locations" :key="'l' + l.id" :value="'loc:' + l.id">📍 {{ l.name }}</option>
      </optgroup>
    </select>
    <select v-model="labelTarget" :disabled="busy || !labels.length" aria-label="Add label to selected"
            style="width:auto" @change="labelSelected">
      <option value="">Add label…</option>
      <option v-for="l in labels" :key="l.id" :value="l.id">🏷️ {{ l.name }}</option>
    </select>
    <button class="secondary sm" :disabled="busy" @click="archiveSelected">Archive</button>
    <button class="danger secondary sm" :disabled="busy" @click="deleteSelected">Delete</button>
  </div>

  <div v-if="loading" class="card-grid">
    <div v-for="i in 8" :key="i" class="skeleton" style="height:190px"></div>
  </div>

  <template v-else-if="items.length">
    <!-- Select-all affordance -->
    <label class="select-all">
      <input type="checkbox" :checked="allOnPageSelected"
             :indeterminate.prop="someSelected" @change="toggleAll" />
      <span>{{ allOnPageSelected ? 'Deselect' : 'Select' }} all {{ items.length }} on this page</span>
    </label>

    <div v-if="view === 'grid'" class="card-grid">
      <div v-for="i in items" :key="i.id" class="select-wrap" :class="{ selected: isSelected(i.id) }">
        <label class="select-check" @click.stop>
          <input type="checkbox" :checked="isSelected(i.id)"
                 :aria-label="'Select ' + i.name" @change="toggle(i.id)" />
        </label>
        <ItemCard :item="i" />
      </div>
    </div>

    <div v-else class="card card-flush">
      <table>
        <thead>
          <tr>
            <th style="width:34px">
              <input type="checkbox" :checked="allOnPageSelected"
                     :indeterminate.prop="someSelected"
                     aria-label="Select all on page" @change="toggleAll" />
            </th>
            <th>Name</th><th>Location</th><th>Labels</th><th>Qty</th><th>Price</th><th>Asset</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in items" :key="i.id" class="clickable"
              :class="{ 'row-selected': isSelected(i.id) }"
              @click="router.push('/items/' + i.id)">
            <td @click.stop>
              <input type="checkbox" :checked="isSelected(i.id)"
                     :aria-label="'Select ' + i.name" @change="toggle(i.id)" />
            </td>
            <td>
              <strong>{{ i.name }}</strong>
              <div class="muted" style="font-size:0.8rem">{{ i.description }}</div>
            </td>
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

  <!-- Filtered-empty: matched nothing, but items exist -->
  <div v-else-if="hasFilters" class="card">
    <EmptyState icon="🔍" title="No items match these filters"
                hint="Try a different search, or clear the filters to see everything.">
      <button class="secondary" @click="resetFilters">Clear filters</button>
    </EmptyState>
  </div>

  <!-- First-run: no items at all -->
  <div v-else class="card">
    <EmptyState icon="📦" title="No items yet"
                hint="Items are the things you own — tools, gadgets, keepsakes. Add your first one to start tracking where it lives.">
      <button @click="ui.openCreate('item')">＋ Add your first item</button>
    </EmptyState>
  </div>
</template>
