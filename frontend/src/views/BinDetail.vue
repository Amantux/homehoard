<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, apiUrl } from '../api'
import { money, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import QrPanel from '../components/QrPanel.vue'
import { confirmNotDuplicate } from '../composables/useDuplicateCheck'
import PhotoCapture from '../components/PhotoCapture.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id
const showCapture = ref(false)
// The camera serves two things on this page — the BIN's own photo and a photo
// for the item about to be created — so it needs a target, or capturing for a
// new item would silently replace the bin's picture.
const captureTarget = ref('bin')
const newItemPhoto = ref(null)      // staged File, uploaded after the item exists
const newItemPreview = ref('')      // object URL for the thumbnail
const creating = ref(false)
const bin = ref(null)
const locations = ref([])
const allItems = ref([])
const addItemId = ref('')
const newItemName = ref('')
const newItemQty = ref(1)
const newItemLabels = ref([])   // picked label ids for the item being created
const labels = ref([])
const tab = ref('items')
const editing = ref(false)

const primaryImg = computed(() => {
  const a = bin.value?.attachments?.find((x) => x.primary)
  return a ? apiUrl('/documents/' + a.document.id) : null
})

async function load() { bin.value = await api.get('/bins/' + id) }

async function uploadPhotoFile(file) {
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('type', file.type.startsWith('image') ? 'photo' : 'attachment')
  form.append('name', file.name)
  bin.value = await api.upload(`/bins/${id}/attachments`, form)
  ui.toast('Photo added')
}
async function uploadPhoto(e) { await uploadPhotoFile(e.target.files[0]); e.target.value = '' }
function onCapture(file) {
  showCapture.value = false
  if (captureTarget.value === 'newItem') stageItemPhoto(file)
  else uploadPhotoFile(file)
}

// Staged rather than uploaded on capture: an attachment needs an item id, and
// creating a throwaway item just to hold a photo would litter the bin if the
// user changed their mind. Shoot first or name first — either order works.
function stageItemPhoto(file) {
  if (!file) return
  if (newItemPreview.value) URL.revokeObjectURL(newItemPreview.value)
  newItemPhoto.value = file
  newItemPreview.value = URL.createObjectURL(file)
}
function clearItemPhoto() {
  if (newItemPreview.value) URL.revokeObjectURL(newItemPreview.value)
  newItemPhoto.value = null
  newItemPreview.value = ''
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
  labels.value = await api.get('/labels')
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
function pickLabel(e) {
  const lid = e.target.value
  e.target.value = ''
  if (lid && !newItemLabels.value.includes(lid)) newItemLabels.value.push(lid)
}
function labelName(lid) { return labels.value.find((l) => l.id === lid)?.name || '' }

async function createItemHere() {
  if (!newItemName.value.trim() || creating.value) return
  const name = newItemName.value.trim()
  if (!(await confirmNotDuplicate(name))) return
  creating.value = true
  let created
  try {
    created = await api.post('/items', {
      name, quantity: Number(newItemQty.value) || 1, binId: id,
      labelIds: newItemLabels.value,
    })
  } catch (e) {
    // Values are preserved so the user can retry without retyping.
    ui.error(e.message || `Could not create “${name}”.`)
    creating.value = false
    return
  }

  // The photo is a SECOND request, so it can fail on its own. Say exactly what
  // happened rather than a bare error: the item does exist, and the user needs
  // to know that before they try again and end up with two.
  let photoFailed = false
  if (newItemPhoto.value) {
    const form = new FormData()
    form.append('file', newItemPhoto.value)
    form.append('type', 'photo')
    form.append('name', newItemPhoto.value.name || 'photo.jpg')
    try {
      await api.upload(`/items/${created.id}/attachments`, form)
    } catch (e) {
      photoFailed = true
      ui.error(`“${name}” was created, but its photo didn’t upload (${e.message || 'upload failed'}). Open the item to add it.`)
    }
  }

  newItemName.value = ''
  newItemQty.value = 1
  newItemLabels.value = []
  clearItemPhoto()
  creating.value = false
  if (!photoFailed) ui.toast(newItemPhoto.value ? 'Item created with photo' : 'Item created in bin')
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
               aria-label="New item name" @keyup.enter="createItemHere" />
        <input type="number" min="1" v-model.number="newItemQty" style="max-width:76px"
               title="Quantity" aria-label="Quantity" @keyup.enter="createItemHere" />

        <!-- Photo before the item exists: staged here, uploaded once it does.
             The camera is the primary path (this is used on a phone, in front
             of the thing); the file input is the fallback on desktop. -->
        <button v-if="!newItemPhoto" type="button" class="secondary sm"
                title="Take a photo for this item" @click="captureTarget = 'newItem'; showCapture = true">
          📷 Photo
        </button>
        <span v-else class="row" style="gap:6px;align-items:center">
          <img :src="newItemPreview" alt="Photo staged for the new item"
               style="height:32px;width:32px;object-fit:cover;border-radius:var(--radius)" />
          <button type="button" class="ghost sm" title="Remove this photo"
                  @click="clearItemPhoto">✕</button>
        </span>

        <!-- Labels ride the create (labelIds goes through _apply) — before
             this, a labelled item still needed the open-item detour even
             though QuickCreate couldn't assign labels either. -->
        <select v-if="labels.length" style="max-width:150px" aria-label="Add a label to the new item"
                @change="pickLabel">
          <option value="">＋ Label…</option>
          <option v-for="l in labels" :key="l.id" :value="l.id">🏷️ {{ l.name }}</option>
        </select>
        <span v-for="lid in newItemLabels" :key="lid" class="chip">
          {{ labelName(lid) }}
          <button type="button" class="ghost sm" style="padding:0 4px" title="Remove label"
                  @click="newItemLabels = newItemLabels.filter((x) => x !== lid)">✕</button>
        </span>

        <button :disabled="!newItemName.trim() || creating" @click="createItemHere">
          {{ creating ? 'Creating…' : (newItemPhoto ? '＋ Create with photo' : '＋ Create here') }}
        </button>
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
      <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
        <input type="file" accept="image/*" @change="uploadPhoto" aria-label="Upload a photo" />
        <button type="button" class="secondary sm"
                @click="captureTarget = 'bin'; showCapture = true">📷 Take photo</button>
      </div>
    </div>

    <!-- v-if, not v-show: the panel autofocuses its code field for hardware
         scanners, and an always-mounted panel would steal the caret on page
         load. Mounting on open makes "open tab, scan" the whole flow. -->
    <div v-if="tab==='qr'"><QrPanel kind="bin" :target-id="bin.id" /></div>
    <PhotoCapture v-if="showCapture" @captured="onCapture" @close="showCapture = false" />
  </div>
  <div v-else class="card"><div class="skeleton" style="height:240px"></div></div>
</template>
