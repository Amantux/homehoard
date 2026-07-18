<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { money, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import ItemCard from '../components/ItemCard.vue'
import QrPanel from '../components/QrPanel.vue'
import { indexById, pathString } from '../locationTree'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id
const loc = ref(null)
const path = ref([])
const allLocations = ref([])
const allItems = ref([])
const addItemId = ref('')
const newItemName = ref('')
const newItemQty = ref(1)
const tab = ref('items')
const editing = ref(false)

const byId = computed(() => indexById(allLocations.value))

// Valid parents = everything except this location and its descendants (moving a
// location under its own descendant would be a cycle — the API rejects it too).
const descendantIds = computed(() => {
  const out = new Set([id])
  let added = true
  while (added) {
    added = false
    for (const l of allLocations.value) {
      if (l.parent?.id && out.has(l.parent.id) && !out.has(l.id)) {
        out.add(l.id)
        added = true
      }
    }
  }
  return out
})
const parentOptions = computed(() =>
  allLocations.value
    .filter((l) => !descendantIds.value.has(l.id))
    .map((l) => ({ id: l.id, path: pathString(l, byId.value) }))
    .sort((a, b) => a.path.localeCompare(b.path)),
)

async function load() {
  loc.value = await api.get('/locations/' + id)
  path.value = await api.get(`/locations/${id}/path`)
}
async function refreshItems() { allItems.value = (await api.get('/items?pageSize=500')).items }
onMounted(async () => {
  await loadCurrency()
  await load()
  ;[allLocations.value] = await Promise.all([api.get('/locations'), refreshItems()])
})

async function createItemHere() {
  if (!newItemName.value.trim()) return
  await api.post('/items', {
    name: newItemName.value.trim(), quantity: Number(newItemQty.value) || 1, locationId: id,
  })
  newItemName.value = ''
  newItemQty.value = 1
  ui.toast('Item created here')
  await load(); await refreshItems()
}
async function addItem() {
  if (!addItemId.value) return
  // Directly in a location means it's not in a bin.
  await api.patch('/items/' + addItemId.value, { locationId: id, binId: null })
  addItemId.value = ''
  ui.toast('Item moved here')
  await load(); await refreshItems()
}

const editParentId = ref('')
function startEdit() {
  editParentId.value = loc.value.parent?.id || ''
  editing.value = true
}

async function save() {
  try {
    await api.put('/locations/' + id, {
      name: loc.value.name, description: loc.value.description,
      parentId: editParentId.value || null,
    })
    editing.value = false
    ui.toast('Saved')
    await load()
  } catch (e) {
    ui.error(e.message)
  }
}
async function remove() {
  if (!confirm('Delete this location and its bins?')) return
  await api.del('/locations/' + id)
  ui.toast('Location deleted')
  router.push('/locations')
}
</script>

<template>
  <div v-if="loc">
    <div class="breadcrumb" style="margin-bottom:10px">
      <router-link to="/locations">Locations</router-link>
      <template v-for="(p, idx) in path" :key="p.id">
        <span class="sep">/</span>
        <router-link v-if="idx < path.length - 1" :to="'/locations/' + p.id">{{ p.name }}</router-link>
        <span v-else>{{ p.name }}</span>
      </template>
    </div>

    <div class="page-head">
      <h1>📍 {{ loc.name }}</h1>
      <span class="badge">{{ money(loc.totalPrice) }}</span>
      <div class="grow"></div>
      <template v-if="editing">
        <button class="secondary" @click="editing=false;load()">Cancel</button>
        <button @click="save">Save</button>
      </template>
      <template v-else>
        <button class="danger secondary" @click="remove">Delete</button>
        <button @click="startEdit">Edit</button>
      </template>
    </div>

    <div v-if="editing" class="card">
      <label class="field"><span>Name</span><input v-model="loc.name" /></label>
      <label class="field"><span>Description</span><textarea v-model="loc.description" rows="2"></textarea></label>
      <label class="field"><span>Parent location</span>
        <select v-model="editParentId">
          <option value="">None — top-level site</option>
          <option v-for="o in parentOptions" :key="o.id" :value="o.id">{{ o.path }}</option>
        </select></label>
    </div>
    <p v-else-if="loc.description" class="muted">{{ loc.description }}</p>

    <div class="tabs">
      <button class="tab" :class="tab==='items'&&'active'" @click="tab='items'">Items <span class="badge">{{ loc.items?.length||0 }}</span></button>
      <button class="tab" :class="tab==='bins'&&'active'" @click="tab='bins'">Bins <span class="badge">{{ loc.bins?.length||0 }}</span></button>
      <button class="tab" :class="tab==='sub'&&'active'" @click="tab='sub'">Sub-locations <span class="badge">{{ loc.children?.length||0 }}</span></button>
      <button class="tab" :class="tab==='qr'&&'active'" @click="tab='qr'">QR codes</button>
    </div>

    <div v-show="tab==='items'">
      <div class="toolbar" style="flex-wrap:wrap;gap:8px">
        <input v-model="newItemName" style="max-width:200px" placeholder="New item name…"
               @keyup.enter="createItemHere" />
        <input type="number" min="1" v-model.number="newItemQty" style="max-width:76px"
               title="Quantity" @keyup.enter="createItemHere" />
        <button :disabled="!newItemName.trim()" @click="createItemHere">＋ Create here</button>
        <span class="muted" style="align-self:center">or</span>
        <select v-model="addItemId" style="max-width:240px">
          <option value="">Move an existing item here…</option>
          <option v-for="i in allItems" :key="i.id" :value="i.id">{{ i.name }}</option>
        </select>
        <button class="secondary" :disabled="!addItemId" @click="addItem">Move here</button>
      </div>
      <div v-if="loc.items?.length" class="card-grid"><ItemCard v-for="i in loc.items" :key="i.id" :item="i" /></div>
      <div v-else class="card muted">No items directly in this location.</div>
    </div>
    <div v-show="tab==='bins'">
      <div v-if="loc.bins?.length" class="card-grid">
        <div v-for="b in loc.bins" :key="b.id" class="item-card" @click="router.push('/bins/'+b.id)">
          <div class="body"><div class="title">🗃️ {{ b.name }}</div>
            <div class="labels"><span class="badge">{{ b.itemCount }} items</span></div></div>
        </div>
      </div>
      <div v-else class="card muted">No bins here.</div>
    </div>
    <div v-show="tab==='sub'">
      <div v-if="loc.children?.length" class="card-grid">
        <div v-for="c in loc.children" :key="c.id" class="item-card" @click="router.push('/locations/'+c.id)">
          <div class="body"><div class="title">📍 {{ c.name }}</div></div>
        </div>
      </div>
      <div v-else class="card muted">No sub-locations.</div>
    </div>
    <div v-show="tab==='qr'"><QrPanel kind="location" :target-id="loc.id" /></div>
  </div>
  <div v-else class="card"><div class="skeleton" style="height:240px"></div></div>
</template>
