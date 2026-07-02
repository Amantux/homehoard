<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { money, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import ItemCard from '../components/ItemCard.vue'
import QrPanel from '../components/QrPanel.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id
const loc = ref(null)
const allLocations = ref([])
const tab = ref('items')
const editing = ref(false)

async function load() {
  loc.value = await api.get('/locations/' + id)
}
onMounted(async () => {
  await loadCurrency()
  await load()
  allLocations.value = await api.get('/locations')
})

async function save() {
  await api.put('/locations/' + id, {
    name: loc.value.name, description: loc.value.description,
    parentId: loc.value.parent?.id || '',
  })
  editing.value = false
  ui.toast('Saved')
  await load()
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
      <template v-if="loc.parent">
        <span class="sep">/</span>
        <router-link :to="'/locations/' + loc.parent.id">{{ loc.parent.name }}</router-link>
      </template>
      <span class="sep">/</span><span>{{ loc.name }}</span>
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
        <button @click="editing=true">Edit</button>
      </template>
    </div>

    <div v-if="editing" class="card">
      <label class="field"><span>Name</span><input v-model="loc.name" /></label>
      <label class="field"><span>Description</span><textarea v-model="loc.description" rows="2"></textarea></label>
      <label class="field"><span>Parent</span>
        <select v-model="loc.parent"><option :value="null">None</option>
          <option v-for="l in allLocations.filter(x=>x.id!==id)" :key="l.id" :value="l">{{ l.name }}</option></select></label>
    </div>
    <p v-else-if="loc.description" class="muted">{{ loc.description }}</p>

    <div class="tabs">
      <button class="tab" :class="tab==='items'&&'active'" @click="tab='items'">Items <span class="badge">{{ loc.items?.length||0 }}</span></button>
      <button class="tab" :class="tab==='bins'&&'active'" @click="tab='bins'">Bins <span class="badge">{{ loc.bins?.length||0 }}</span></button>
      <button class="tab" :class="tab==='sub'&&'active'" @click="tab='sub'">Sub-locations <span class="badge">{{ loc.children?.length||0 }}</span></button>
      <button class="tab" :class="tab==='qr'&&'active'" @click="tab='qr'">QR codes</button>
    </div>

    <div v-show="tab==='items'">
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
