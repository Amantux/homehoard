<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, apiUrl, getToken } from '../api'
import { money, shortDate, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import QrPanel from '../components/QrPanel.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id

const item = ref(null)
const path = ref([])
const locations = ref([])
const bins = ref([])
const allLabels = ref([])
const maint = ref({ entries: [], costTotal: 0 })
const tab = ref('details')
const editing = ref(false)
const newMaint = ref({ name: '', cost: 0, scheduledDate: '', completedDate: '' })

const selectedLabels = computed({
  get: () => (item.value?.labels || []).map((l) => l.id),
  set: (ids) => { item.value.labels = allLabels.value.filter((l) => ids.includes(l.id)) },
})
function dateInput(v) { return v ? v.slice(0, 10) : '' }
const primaryImg = computed(() => {
  const a = item.value?.attachments?.find((x) => x.primary)
  return a ? apiUrl('/documents/' + a.document.id) : null
})

async function loadAll() {
  item.value = await api.get('/items/' + id)
  ;[path.value, maint.value] = await Promise.all([
    api.get(`/items/${id}/path`),
    api.get(`/items/${id}/maintenance`),
  ])
}
onMounted(async () => {
  await loadCurrency()
  await loadAll()
  ;[locations.value, bins.value, allLabels.value] = await Promise.all([
    api.get('/locations'), api.get('/bins'), api.get('/labels'),
  ])
})

async function save() {
  const i = item.value
  item.value = await api.put('/items/' + id, {
    name: i.name, description: i.description, notes: i.notes,
    quantity: Number(i.quantity) || 1, insured: i.insured, archived: i.archived,
    serialNumber: i.serialNumber, modelNumber: i.modelNumber, manufacturer: i.manufacturer,
    purchaseFrom: i.purchaseFrom, purchasePrice: Number(i.purchasePrice) || 0,
    purchaseDate: i.purchaseDate || null, warrantyExpires: i.warrantyExpires || null,
    lifetimeWarranty: i.lifetimeWarranty, warrantyDetails: i.warrantyDetails,
    locationId: i.location?.id || null, binId: i.bin?.id || null,
    labelIds: i.labels.map((l) => l.id),
  })
  editing.value = false
  ui.toast('Item saved')
  await loadAll()
}

async function remove() {
  if (!confirm('Delete this item?')) return
  await api.del('/items/' + id)
  ui.toast('Item deleted')
  router.push('/items')
}

async function upload(e) {
  const file = e.target.files[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('type', file.type.startsWith('image') ? 'photo' : 'attachment')
  form.append('name', file.name)
  item.value = await api.upload(`/items/${id}/attachments`, form)
  ui.toast('Attachment uploaded')
}

async function addMaint() {
  if (!newMaint.value.name) return
  await api.post(`/items/${id}/maintenance`, newMaint.value)
  newMaint.value = { name: '', cost: 0, scheduledDate: '', completedDate: '' }
  maint.value = await api.get(`/items/${id}/maintenance`)
  ui.toast('Maintenance logged')
}
</script>

<template>
  <div v-if="item">
    <div class="breadcrumb" style="margin-bottom:10px">
      <router-link to="/items">Items</router-link>
      <template v-for="p in path" :key="p.id">
        <span class="sep">/</span>
        <router-link v-if="p.type === 'location'" :to="'/locations/' + p.id">{{ p.name }}</router-link>
        <span v-else>{{ p.name }}</span>
      </template>
    </div>

    <div class="page-head">
      <h1>{{ item.name }}</h1>
      <span class="badge">{{ item.assetId }}</span>
      <span v-if="item.archived" class="badge warn">Archived</span>
      <div class="grow"></div>
      <template v-if="editing">
        <button class="secondary" @click="editing = false; loadAll()">Cancel</button>
        <button @click="save">Save</button>
      </template>
      <template v-else>
        <button class="danger secondary" @click="remove">Delete</button>
        <button @click="editing = true">Edit</button>
      </template>
    </div>

    <div class="tabs">
      <button class="tab" :class="tab==='details'&&'active'" @click="tab='details'">Details</button>
      <button class="tab" :class="tab==='attachments'&&'active'" @click="tab='attachments'">
        Attachments <span class="badge" style="margin-left:4px">{{ item.attachments.length }}</span></button>
      <button class="tab" :class="tab==='maintenance'&&'active'" @click="tab='maintenance'">
        Maintenance <span class="badge" style="margin-left:4px">{{ maint.entries.length }}</span></button>
      <button class="tab" :class="tab==='qr'&&'active'" @click="tab='qr'">QR codes</button>
    </div>

    <!-- DETAILS -->
    <div v-show="tab==='details'">
      <div class="row top" style="gap:16px;align-items:stretch">
        <div class="card" style="flex:1">
          <template v-if="!editing">
            <p v-if="item.description">{{ item.description }}</p>
            <dl class="kv">
              <dt>Location</dt><dd>{{ item.location?.name || '—' }}</dd>
              <dt>Bin</dt><dd>{{ item.bin?.name || '—' }}</dd>
              <dt>Quantity</dt><dd>{{ item.quantity }}</dd>
              <dt>Manufacturer</dt><dd>{{ item.manufacturer || '—' }}</dd>
              <dt>Model #</dt><dd>{{ item.modelNumber || '—' }}</dd>
              <dt>Serial #</dt><dd>{{ item.serialNumber || '—' }}</dd>
              <dt>Purchase price</dt><dd>{{ money(item.purchasePrice) }}</dd>
              <dt>Purchased from</dt><dd>{{ item.purchaseFrom || '—' }}</dd>
              <dt>Purchase date</dt><dd>{{ shortDate(item.purchaseDate) }}</dd>
              <dt>Warranty</dt><dd>
                <span v-if="item.lifetimeWarranty" class="badge ok">Lifetime</span>
                <span v-else>{{ shortDate(item.warrantyExpires) }}</span></dd>
              <dt>Insured</dt><dd>{{ item.insured ? 'Yes' : 'No' }}</dd>
            </dl>
            <div v-if="item.labels.length" style="margin-top:14px">
              <span v-for="l in item.labels" :key="l.id" class="chip"
                :style="l.color ? { background: l.color+'22', color: l.color } : {}">{{ l.name }}</span>
            </div>
            <div v-if="item.notes" class="divider"></div>
            <p v-if="item.notes" class="muted" style="white-space:pre-wrap">{{ item.notes }}</p>
          </template>

          <!-- EDIT FORM -->
          <template v-else>
            <label class="field"><span>Name</span><input v-model="item.name" /></label>
            <label class="field"><span>Description</span><textarea v-model="item.description" rows="2"></textarea></label>
            <div class="row">
              <label class="field fill"><span>Quantity</span><input type="number" v-model.number="item.quantity" /></label>
              <label class="field fill"><span>Location</span>
                <select v-model="item.location"><option :value="null">None</option>
                  <option v-for="l in locations" :key="l.id" :value="l">{{ l.name }}</option></select></label>
              <label class="field fill"><span>Bin</span>
                <select v-model="item.bin"><option :value="null">None</option>
                  <option v-for="b in bins" :key="b.id" :value="b">{{ b.name }}</option></select></label>
            </div>
            <label class="field"><span>Labels</span>
              <select multiple v-model="selectedLabels" size="4">
                <option v-for="l in allLabels" :key="l.id" :value="l.id">{{ l.name }}</option></select></label>
            <div class="row">
              <label class="field fill"><span>Manufacturer</span><input v-model="item.manufacturer" /></label>
              <label class="field fill"><span>Model #</span><input v-model="item.modelNumber" /></label>
              <label class="field fill"><span>Serial #</span><input v-model="item.serialNumber" /></label>
            </div>
            <div class="row">
              <label class="field fill"><span>Purchased from</span><input v-model="item.purchaseFrom" /></label>
              <label class="field fill"><span>Price</span><input type="number" step="0.01" v-model="item.purchasePrice" /></label>
              <label class="field fill"><span>Purchase date</span>
                <input type="date" :value="dateInput(item.purchaseDate)" @input="item.purchaseDate=$event.target.value" /></label>
            </div>
            <div class="row">
              <label class="field fill"><span>Warranty expires</span>
                <input type="date" :value="dateInput(item.warrantyExpires)" @input="item.warrantyExpires=$event.target.value" /></label>
              <label class="row" style="gap:6px;margin-top:20px"><input type="checkbox" v-model="item.lifetimeWarranty" /> Lifetime</label>
              <label class="row" style="gap:6px;margin-top:20px"><input type="checkbox" v-model="item.insured" /> Insured</label>
              <label class="row" style="gap:6px;margin-top:20px"><input type="checkbox" v-model="item.archived" /> Archived</label>
            </div>
            <label class="field"><span>Notes</span><textarea v-model="item.notes" rows="3"></textarea></label>
          </template>
        </div>

        <div v-if="primaryImg || item.attachments.length" class="card" style="width:280px;flex-shrink:0">
          <div class="thumb" style="border-radius:10px;aspect-ratio:1;background:var(--surface-2);display:grid;place-items:center;overflow:hidden">
            <img v-if="primaryImg" :src="primaryImg" style="width:100%;height:100%;object-fit:cover" />
            <span v-else style="font-size:48px">📦</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ATTACHMENTS -->
    <div v-show="tab==='attachments'" class="card">
      <div v-if="item.attachments.length" class="card-grid">
        <div v-for="a in item.attachments" :key="a.id" class="item-card" style="cursor:default">
          <div class="thumb">
            <img v-if="a.type==='photo'" :src="apiUrl('/documents/'+a.document.id)" />
            <span v-else>📄</span>
          </div>
          <div class="body">
            <div class="title" style="font-size:0.9rem">{{ a.document.title }}</div>
            <div class="sub">{{ a.type }}<span v-if="a.primary"> · primary</span></div>
            <a :href="apiUrl('/documents/'+a.document.id)" target="_blank" class="sub">Download ↓</a>
          </div>
        </div>
      </div>
      <p v-else class="muted">No attachments yet.</p>
      <div class="divider"></div>
      <input type="file" @change="upload" />
    </div>

    <!-- MAINTENANCE -->
    <div v-show="tab==='maintenance'" class="card">
      <div class="row" style="margin-bottom:12px">
        <h2 style="margin:0;flex:1">Log</h2>
        <span class="badge">Total: {{ money(maint.costTotal) }}</span>
      </div>
      <table v-if="maint.entries.length">
        <thead><tr><th>Name</th><th>Scheduled</th><th>Completed</th><th>Cost</th></tr></thead>
        <tbody><tr v-for="m in maint.entries" :key="m.id">
          <td>{{ m.name }}<div class="muted" style="font-size:0.8rem">{{ m.description }}</div></td>
          <td>{{ shortDate(m.scheduledDate) }}</td>
          <td>{{ shortDate(m.completedDate) }}</td>
          <td>{{ money(m.cost) }}</td>
        </tr></tbody>
      </table>
      <p v-else class="muted">No maintenance logged.</p>
      <div class="divider"></div>
      <div class="row wrap" style="align-items:flex-end;gap:10px">
        <label class="field fill" style="margin:0;min-width:160px"><span>Task</span><input v-model="newMaint.name" placeholder="e.g. Oil change" /></label>
        <label class="field" style="margin:0;width:110px"><span>Cost</span><input type="number" step="0.01" v-model="newMaint.cost" /></label>
        <label class="field" style="margin:0"><span>Scheduled</span><input type="date" v-model="newMaint.scheduledDate" /></label>
        <label class="field" style="margin:0"><span>Completed</span><input type="date" v-model="newMaint.completedDate" /></label>
        <button :disabled="!newMaint.name" @click="addMaint">Add</button>
      </div>
    </div>

    <!-- QR -->
    <div v-show="tab==='qr'">
      <QrPanel kind="item" :target-id="item.id" />
    </div>
  </div>

  <div v-else class="card"><div class="skeleton" style="height:300px"></div></div>
</template>
