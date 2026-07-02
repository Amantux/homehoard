<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, apiUrl } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const ui = useUI()
const bins = ref([])
const locations = ref([])
const loading = ref(true)
const showCreate = ref(false)
const form = ref({ name: '', description: '', locationId: '' })

async function load() { bins.value = await api.get('/bins'); loading.value = false }
onMounted(async () => {
  locations.value = await api.get('/locations')
  await load()
})
function locName(id) { return locations.value.find((l) => l.id === id)?.name || 'No location' }

async function create() {
  const b = await api.post('/bins', form.value)
  ui.toast('Bin created')
  showCreate.value = false
  form.value = { name: '', description: '', locationId: '' }
  router.push('/bins/' + b.id)
}
</script>

<template>
  <div class="page-head">
    <h1>Bins</h1><span class="badge">{{ bins.length }}</span>
    <div class="grow"></div>
    <button @click="showCreate = true">＋ New bin</button>
  </div>

  <div v-if="loading" class="card-grid"><div v-for="i in 4" :key="i" class="skeleton" style="height:120px"></div></div>
  <div v-else-if="bins.length" class="card-grid">
    <div v-for="b in bins" :key="b.id" class="item-card" @click="router.push('/bins/' + b.id)">
      <div class="thumb">
        <img v-if="b.imageId" :src="apiUrl('/documents/' + b.imageId)" alt=""
             @error="$event.target.style.display='none'" />
        <span v-else>🗃️</span>
      </div>
      <div class="body">
        <div class="title">{{ b.name }}</div>
        <div class="sub">📍 {{ locName(b.locationId) }}</div>
        <div class="labels"><span class="chip">{{ b.itemCount }} items</span></div>
      </div>
    </div>
  </div>
  <div v-else class="card">
    <EmptyState icon="🗃️" title="No bins yet"
                hint="A bin lives in a location and holds a collection of items.">
      <button @click="showCreate = true">Create a bin</button>
    </EmptyState>
  </div>

  <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
    <div class="card modal">
      <div class="modal-head"><h2>New bin</h2>
        <button class="ghost icon-btn" @click="showCreate = false">✕</button></div>
      <label class="field"><span>Name</span><input v-model="form.name" autofocus @keyup.enter="create" /></label>
      <label class="field"><span>Description</span><textarea v-model="form.description" rows="2"></textarea></label>
      <label class="field"><span>Location</span>
        <select v-model="form.locationId"><option value="">None</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option></select></label>
      <div class="row" style="justify-content:flex-end">
        <button class="secondary" @click="showCreate = false">Cancel</button>
        <button :disabled="!form.name" @click="create">Create</button>
      </div>
    </div>
  </div>
</template>
