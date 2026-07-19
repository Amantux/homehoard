<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import LocationTreeNode from '../components/LocationTreeNode.vue'
import { buildTree, indexById, pathString } from '../locationTree'

const router = useRouter()
const ui = useUI()
const locations = ref([])
const loading = ref(true)
const q = ref('')
const showCreate = ref(false)
const form = ref({ name: '', description: '', parentId: '' })
const busy = ref(false)

const byId = computed(() => indexById(locations.value))
const tree = computed(() => buildTree(locations.value))

// Parent options, each labelled with its full path so nested sites are
// unambiguous ("Lake House › Garage" vs. "City Flat › Garage").
const parentOptions = computed(() =>
  locations.value
    .map((l) => ({ id: l.id, path: pathString(l, byId.value) }))
    .sort((a, b) => a.path.localeCompare(b.path)),
)

// When searching, a flat list of matches (with path) beats hunting the tree.
const matches = computed(() => {
  const term = q.value.trim().toLowerCase()
  if (!term) return []
  return locations.value
    .map((l) => ({ ...l, path: pathString(l, byId.value) }))
    .filter((l) => l.path.toLowerCase().includes(term))
    .sort((a, b) => a.path.localeCompare(b.path))
})

async function load() {
  loading.value = true
  locations.value = await api.get('/locations')
  loading.value = false
}
onMounted(load)

async function create() {
  if (busy.value) return
  busy.value = true
  try {
    await api.post('/locations', {
      name: form.value.name.trim(),
      description: form.value.description,
      parentId: form.value.parentId || null,
    })
    ui.toast('Location created')
    showCreate.value = false
    form.value = { name: '', description: '', parentId: '' }
    await load()
  } catch (e) {
    ui.error(e.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page-head">
    <h1>Locations</h1>
    <span class="badge">{{ locations.length }}</span>
    <div class="grow"></div>
    <button @click="showCreate = true">＋ New location</button>
  </div>

  <div v-if="!loading && locations.length" class="toolbar">
    <input v-model="q" placeholder="Search all locations…" aria-label="Search locations"
           style="max-width:340px" />
  </div>

  <div v-if="loading" class="card">
    <div v-for="i in 5" :key="i" class="skeleton" style="height:34px;margin:6px 0"></div>
  </div>

  <!-- Search results: flat, path-qualified -->
  <div v-else-if="q.trim()" class="card card-flush">
    <div v-if="matches.length">
      <button v-for="m in matches" :key="m.id" class="tree-label search-hit"
              @click="router.push('/locations/' + m.id)">
        <span class="tree-name">📍 {{ m.path }}</span>
        <span class="tree-counts">
          <span v-if="m.itemCount" class="badge">{{ m.itemCount }} item{{ m.itemCount === 1 ? '' : 's' }}</span>
          <span v-if="m.bins?.length" class="badge">{{ m.bins.length }} bin{{ m.bins.length === 1 ? '' : 's' }}</span>
        </span>
      </button>
    </div>
    <div v-else class="muted" style="padding:18px">No locations match “{{ q }}”.</div>
  </div>

  <!-- The site tree -->
  <div v-else-if="locations.length" class="card card-flush">
    <LocationTreeNode v-for="root in tree" :key="root.id" :node="root" :depth="0" />
  </div>

  <div v-else class="card">
    <EmptyState icon="📍" title="No locations yet"
                hint="Add a top-level site — a home, a storage locker, a rental — then nest rooms, shelves, and bins inside it.">
      <button @click="showCreate = true">Add your first site</button>
    </EmptyState>
  </div>

  <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
    <div class="card modal">
      <div class="modal-head"><h2>New location</h2>
        <button class="ghost icon-btn" @click="showCreate = false">✕</button></div>
      <label class="field"><span>Name</span>
        <input v-model="form.name" autofocus placeholder="e.g. Lake House, or Garage"
               @keyup.enter="create" /></label>
      <label class="field"><span>Description</span>
        <textarea v-model="form.description" rows="2"></textarea></label>
      <label class="field"><span>Parent location (optional)</span>
        <select v-model="form.parentId">
          <option value="">None — this is a top-level site</option>
          <option v-for="o in parentOptions" :key="o.id" :value="o.id">{{ o.path }}</option>
        </select></label>
      <div class="row" style="justify-content:flex-end">
        <button class="secondary" @click="showCreate = false">Cancel</button>
        <button :disabled="!form.name.trim() || busy" @click="create">Create</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-hit {
  width: 100%; display: flex; align-items: center; gap: 10px;
  background: none; border: none; border-bottom: 1px solid var(--border);
  color: var(--text); padding: 10px 14px; cursor: pointer; text-align: left;
  font-weight: 500; font-size: 0.92rem;
}
.search-hit:hover { background: var(--accent-soft); }
.search-hit .tree-name { flex: 1; }
.search-hit .tree-counts { display: flex; gap: 5px; }
</style>
