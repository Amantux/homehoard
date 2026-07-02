<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const ui = useUI()
const locations = ref([])
const loading = ref(true)
const showCreate = ref(false)
const form = ref({ name: '', description: '', parentId: '' })

async function load() {
  locations.value = await api.get('/locations')
  loading.value = false
}
onMounted(load)

async function create() {
  await api.post('/locations', form.value)
  ui.toast('Location created')
  showCreate.value = false
  form.value = { name: '', description: '', parentId: '' }
  await load()
}
</script>

<template>
  <div class="page-head">
    <h1>Locations</h1>
    <span class="badge">{{ locations.length }}</span>
    <div class="grow"></div>
    <button @click="showCreate = true">＋ New location</button>
  </div>

  <div v-if="loading" class="card-grid">
    <div v-for="i in 4" :key="i" class="skeleton" style="height:120px"></div>
  </div>
  <div v-else-if="locations.length" class="card-grid">
    <div v-for="l in locations" :key="l.id" class="item-card" @click="router.push('/locations/' + l.id)">
      <div class="body">
        <div class="title">📍 {{ l.name }}</div>
        <div class="sub" v-if="l.parent">in {{ l.parent.name }}</div>
        <div class="sub">{{ l.description }}</div>
        <div class="labels">
          <span class="badge">{{ l.bins?.length || 0 }} bins</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="card">
    <EmptyState icon="📍" title="No locations" hint="Add rooms, shelves, or areas.">
      <button @click="showCreate = true">Add location</button>
    </EmptyState>
  </div>

  <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
    <div class="card modal">
      <div class="modal-head"><h2>New location</h2>
        <button class="ghost icon-btn" @click="showCreate = false">✕</button></div>
      <label class="field"><span>Name</span><input v-model="form.name" autofocus @keyup.enter="create" /></label>
      <label class="field"><span>Description</span><textarea v-model="form.description" rows="2"></textarea></label>
      <label class="field"><span>Parent location</span>
        <select v-model="form.parentId"><option value="">None</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option></select></label>
      <div class="row" style="justify-content:flex-end">
        <button class="secondary" @click="showCreate = false">Cancel</button>
        <button :disabled="!form.name" @click="create">Create</button>
      </div>
    </div>
  </div>
</template>
