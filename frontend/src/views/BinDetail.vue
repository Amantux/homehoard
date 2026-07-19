<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, apiUrl } from '../api'
import { money, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import QrPanel from '../components/QrPanel.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id
const bin = ref(null)
const locations = ref([])
const allItems = ref([])
const addItemId = ref('')
const newItemName = ref('')
const newItemQty = ref(1)
const tab = ref('items')
const editing = ref(false)

const primaryImg = computed(() => {
  const a = bin.value?.attachments?.find((x) => x.primary)
  return a ? apiUrl('/documents/' + a.document.id) : null
})

async function load() { bin.value = await api.get('/bins/' + id) }

async function uploadPhoto(e) {
  const file = e.target.files[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('type', file.type.startsWith('image') ? 'photo' : 'attachment')
  form.append('name', file.name)
  bin.value = await api.upload(`/bins/${id}/attachments`, form)
  ui.toast('Photo added')
  e.target.value = ''
}
async function removeAttachment(a) {
  await api.del(`/bins/${id}/attachments/${a.id}`)
  await load()
}
onMounted(async () => {
  await loadCurrency()
  await load()
  locations.value = await api.get('/locations')
  allItems.value = (await api.get('/items?pageSize=500')).items
})

async function save() {
  bin.value = await api.put('/bins/' + id, {
    name: bin.value.name, description: bin.value.description,
    locationId: bin.value.locationId || null,
  })
  editing.value = false
  ui.toast('Saved')
}
async function addItem() {
  if (!addItemId.value) return
  await api.put(`/bins/${id}/items/${addItemId.value}`)
  addItemId.value = ''
  ui.toast('Item added to bin')
  await load()
}
async function createItemHere() {
  if (!newItemName.value.trim()) return
  await api.post('/items', {
    name: newItemName.value.trim(), quantity: Number(newItemQty.value) || 1, binId: id,
  })
  newItemName.value = ''
  newItemQty.value = 1
  ui.toast('Item created in bin')
  await load()
  allItems.value = (await api.get('/items?pageSize=500')).items
}
async function removeItem(item) {
  await api.del(`/bins/${id}/items/${item.id}`)
  await load()
}
async function remove() {
  if (!confirm('Delete this bin? Items are kept but removed from the bin.')) return
  await api.del('/bins/' + id)
  ui.toast('Bin deleted')
  router.push('/bins')
}
</script>

<template>
  <div v-if="bin">
    <div class="breadcrumb" style="margin-bottom:10px">
      <router-link to="/bins">Bins</router-link>
      <template v-if="bin.location"><span class="sep">/</span>
        <router-link :to="'/locations/'+bin.location.id">{{ bin.location.name }}</router-link></template>
      <span class="sep">/</span><span>{{ bin.name }}</span>
    </div>

    <div class="page-head">
      <img v-if="primaryImg" :src="primaryImg" alt=""
           style="width:44px;height:44px;border-radius:10px;object-fit:cover;border:1px solid var(--border)" />
      <h1>🗃️ {{ bin.name }}</h1>
      <span class="badge">{{ money(bin.totalPrice) }}</span>
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
      <label class="field"><span>Name</span><input v-model="bin.name" /></label>
      <label class="field"><span>Description</span><textarea v-model="bin.description" rows="2"></textarea></label>
      <label class="field"><span>Location</span>
        <select v-model="bin.locationId"><option value="">None</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option></select></label>
    </div>
    <p v-else-if="bin.description" class="muted">{{ bin.description }}</p>

    <div class="tabs">
      <button class="tab" :class="tab==='items'&&'active'" @click="tab='items'">Items <span class="badge">{{ bin.itemCount }}</span></button>
      <button class="tab" :class="tab==='photos'&&'active'" @click="tab='photos'">Photos <span class="badge">{{ bin.attachments.length }}</span></button>
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
          <option value="">Add an existing item…</option>
          <option v-for="i in allItems" :key="i.id" :value="i.id">{{ i.name }}</option>
        </select>
        <button class="secondary" :disabled="!addItemId" @click="addItem">Add to bin</button>
      </div>
      <div v-if="bin.items.length" class="card-grid">
        <div v-for="i in bin.items" :key="i.id" class="item-card">
          <div class="body">
            <div class="title" @click.stop="router.push('/items/'+i.id)" style="cursor:pointer">{{ i.name }}</div>
            <div class="sub">Qty: {{ i.quantity }}</div>
            <div class="labels"><button class="secondary sm" @click.stop="removeItem(i)">Remove</button></div>
          </div>
        </div>
      </div>
      <div v-else class="card muted">No items in this bin yet.</div>
    </div>

    <div v-show="tab==='photos'" class="card">
      <div v-if="bin.attachments.length" class="card-grid">
        <div v-for="a in bin.attachments" :key="a.id" class="item-card" style="cursor:default">
          <div class="thumb">
            <img v-if="a.type==='photo'" :src="apiUrl('/documents/'+a.document.id)" />
            <span v-else>📄</span>
          </div>
          <div class="body">
            <div class="title" style="font-size:0.9rem">{{ a.document.title }}</div>
            <div class="sub">{{ a.type }}<span v-if="a.primary"> · primary</span></div>
            <div class="labels">
              <a :href="apiUrl('/documents/'+a.document.id)" target="_blank" class="sub">Download ↓</a>
              <button class="secondary sm" @click="removeAttachment(a)">Remove</button>
            </div>
          </div>
        </div>
      </div>
      <p v-else class="muted">No photos yet.</p>
      <div class="divider"></div>
      <input type="file" accept="image/*" @change="uploadPhoto" />
    </div>

    <div v-show="tab==='qr'"><QrPanel kind="bin" :target-id="bin.id" /></div>
  </div>
  <div v-else class="card"><div class="skeleton" style="height:240px"></div></div>
</template>
