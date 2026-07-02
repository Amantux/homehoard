<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'

const ui = useUI()
const labels = ref([])
const loading = ref(true)
const showModal = ref(false)
const form = ref({ name: '', description: '', color: '#0d9488' })
const editing = ref(null)

async function load() { labels.value = await api.get('/labels'); loading.value = false }
onMounted(load)

function openNew() { editing.value = null; form.value = { name: '', description: '', color: '#0d9488' }; showModal.value = true }
function openEdit(l) { editing.value = l.id; form.value = { name: l.name, description: l.description, color: l.color || '#0d9488' }; showModal.value = true }

async function submit() {
  if (editing.value) await api.put('/labels/' + editing.value, form.value)
  else await api.post('/labels', form.value)
  ui.toast('Label saved'); showModal.value = false; await load()
}
async function remove(l) {
  if (!confirm(`Delete label "${l.name}"?`)) return
  await api.del('/labels/' + l.id); ui.toast('Deleted'); await load()
}
</script>

<template>
  <div class="page-head">
    <h1>Labels</h1><span class="badge">{{ labels.length }}</span>
    <div class="grow"></div>
    <button @click="openNew">＋ New label</button>
  </div>

  <div v-if="loading" class="card-grid"><div v-for="i in 4" :key="i" class="skeleton" style="height:90px"></div></div>
  <div v-else-if="labels.length" class="card-grid">
    <div v-for="l in labels" :key="l.id" class="card" style="display:flex;flex-direction:column;gap:8px">
      <div class="row">
        <span class="color-dot" :style="{ background: l.color || 'var(--accent)' }"></span>
        <strong style="flex:1">{{ l.name }}</strong>
      </div>
      <div class="muted" style="font-size:0.85rem;min-height:1.2em">{{ l.description }}</div>
      <div class="row" style="gap:6px">
        <button class="secondary sm" @click="openEdit(l)">Edit</button>
        <button class="danger secondary sm" @click="remove(l)">Delete</button>
      </div>
    </div>
  </div>
  <div v-else class="card"><EmptyState icon="🏷️" title="No labels" hint="Create labels to tag and filter items.">
    <button @click="openNew">Add label</button></EmptyState></div>

  <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
    <div class="card modal">
      <div class="modal-head"><h2>{{ editing ? 'Edit' : 'New' }} label</h2>
        <button class="ghost icon-btn" @click="showModal = false">✕</button></div>
      <label class="field"><span>Name</span><input v-model="form.name" autofocus @keyup.enter="submit" /></label>
      <label class="field"><span>Description</span><input v-model="form.description" /></label>
      <label class="field"><span>Color</span><input type="color" v-model="form.color" /></label>
      <div class="row" style="justify-content:flex-end">
        <button class="secondary" @click="showModal = false">Cancel</button>
        <button :disabled="!form.name" @click="submit">Save</button>
      </div>
    </div>
  </div>
</template>
