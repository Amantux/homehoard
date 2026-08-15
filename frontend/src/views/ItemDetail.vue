<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, apiUrl } from '../api'
import { money, shortDate, loadCurrency } from '../format'
import { useUI } from '../stores/ui'
import QrPanel from '../components/QrPanel.vue'
import PhotoCapture from '../components/PhotoCapture.vue'

const route = useRoute()
const router = useRouter()
const ui = useUI()
const id = route.params.id
const showCapture = ref(false)

const item = ref(null)
const binId = ref('')
const locationId = ref('')
const path = ref([])
const locations = ref([])
const bins = ref([])
const allLabels = ref([])
const maint = ref({ entries: [], costTotal: 0 })
const tab = ref('details')
const editing = ref(false)
const newMaint = ref({ name: '', cost: 0, scheduledDate: '', completedDate: '' })
const showCheckout = ref(false)
const checkoutForm = ref({ person: '', due: '', notes: '' })

const selectedLabels = computed({
  get: () => (item.value?.labels || []).map((l) => l.id),
  set: (ids) => { item.value.labels = allLabels.value.filter((l) => ids.includes(l.id)) },
})
function dateInput(v) { return v ? v.slice(0, 10) : '' }

// When an item is placed in a bin, its location is inherited from that bin.
function onBinChange() {
  const b = bins.value.find((x) => x.id === binId.value)
  if (b && b.location) locationId.value = b.location.id
}
const primaryImg = computed(() => {
  const a = item.value?.attachments?.find((x) => x.primary)
  return a ? apiUrl('/documents/' + a.document.id) : null
})

async function loadAll() {
  item.value = await api.get('/items/' + id)
  binId.value = item.value.bin?.id || ''
  locationId.value = item.value.location?.id || ''
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
    barcode: i.barcode || '',
    purchaseFrom: i.purchaseFrom, purchasePrice: Number(i.purchasePrice) || 0,
    purchaseDate: i.purchaseDate || null, warrantyExpires: i.warrantyExpires || null,
    lifetimeWarranty: i.lifetimeWarranty, warrantyDetails: i.warrantyDetails,
    // '' (cleared field) and null both mean "stop tracking" — the server
    // treats a null as an explicit clear, unlike absent keys.
    minQuantity: i.minQuantity === '' || i.minQuantity == null ? null : Number(i.minQuantity),
    targetQuantity: i.targetQuantity === '' || i.targetQuantity == null ? null : Number(i.targetQuantity),
    binId: binId.value || null,
    locationId: binId.value ? null : (locationId.value || null),
    labelIds: i.labels.map((l) => l.id),
  })
  editing.value = false
  ui.toast('Item saved')
  await loadAll()
}

// ── Placements (multi-location quantities) ───────────────────────────────────
const placement = ref({ binId: '', quantity: 1 })
const moveFor = ref(null)
const moveForm = ref({ toBinId: '', quantity: null })

async function addPlacement() {
  if (!placement.value.binId) return
  try {
    await api.post(`/items/${id}/holdings`,
      { binId: placement.value.binId, quantity: Number(placement.value.quantity) || 1 })
    placement.value = { binId: '', quantity: 1 }
    await loadAll(); ui.toast('Placement added')
  } catch (e) { ui.error(e.message) }
}
async function editHolding(h, qty) {
  const q = Number(qty)
  if (!(q > 0)) { await loadAll(); return }
  try { await api.put(`/holdings/${h.id}`, { quantity: q }); await loadAll() }
  catch (e) { ui.error(e.message) }
}
async function removeHolding(h) {
  const where = h.bin?.name || h.location?.name || 'Unassigned'
  if (!confirm(`Remove the placement in ${where}?`)) return
  try { await api.del(`/holdings/${h.id}`); await loadAll() } catch (e) { ui.error(e.message) }
}
function openMove(h) { moveFor.value = h; moveForm.value = { toBinId: '', quantity: h.quantity } }
async function doMove() {
  const q = Number(moveForm.value.quantity)
  if (!(q > 0)) { ui.error('Enter a quantity to move'); return }
  try {
    await api.post(`/holdings/${moveFor.value.id}/move`,
      { toBinId: moveForm.value.toBinId || null, quantity: q })
    moveFor.value = null; await loadAll(); ui.toast('Moved')
  } catch (e) { ui.error(e.message) }
}

async function remove() {
  if (!confirm('Delete this item?')) return
  await api.del('/items/' + id)
  ui.toast('Item deleted')
  router.push('/items')
}

// Look this item up online (Ollama web search) → a short searchable description.
const describing = ref(false)
const described = ref(null)   // { description, sources }
async function describe() {
  describing.value = true; described.value = null
  try {
    const r = await api.post(`/items/${id}/describe`, {})
    // Only trust http(s) source links (guard against javascript:/data: URLs).
    const sources = (r.sources || []).filter((s) => /^https?:\/\//i.test(s))
    described.value = { description: r.description, sources }
    ui.toast('Searchable description added')
  } catch (e) {
    ui.error(e.message || 'Could not describe this item.')
  } finally { describing.value = false }
}

// One click checks the item out right away; details are an optional next step.
async function checkOut() {
  item.value = await api.post(`/items/${id}/checkout`, {})
  checkoutForm.value = { person: '', due: '', notes: '' }
  showCheckout.value = true
  ui.toast('Checked out')
}
async function saveCheckoutDetails() {
  item.value = await api.patch(`/items/${id}/checkout`, {
    person: checkoutForm.value.person,
    due: checkoutForm.value.due || null,
    notes: checkoutForm.value.notes,
  })
  showCheckout.value = false
  ui.toast('Details saved')
}
async function checkIn() {
  showCheckout.value = false
  item.value = await api.post(`/items/${id}/checkin`, {})
  ui.toast('Checked in')
}


// --- How-to videos -------------------------------------------------------
// Two placements: on the ITEM ("how this thing works") and on a single
// maintenance task ("how to do this job"), so the right clip is in front of you
// when a job comes due. A video is a link or an uploaded file; the server
// decides which links may be embedded — the UI never builds an embed URL.
const newVideoUrl = ref('')
const newVideoTitle = ref('')
const videoBusy = ref(false)
const videoError = ref('')
// Which maintenance row has its add-a-video form open.
const videoFor = ref(null)

const itemVideos = computed(() =>
  (item.value?.attachments || []).filter((a) => a.type === 'video'))

function videoHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return 'the web' }
}

async function addVideo(entryId = null) {
  const url = newVideoUrl.value.trim()
  if (!url) return
  videoBusy.value = true
  videoError.value = ''
  const path = entryId
    ? `/items/${id}/maintenance/${entryId}/videos`
    : `/items/${id}/videos`
  try {
    await api.post(path, { url, title: newVideoTitle.value.trim() })
    newVideoUrl.value = ''
    newVideoTitle.value = ''
    await loadAll()
    ui.toast('Video added')
  } catch (e) {
    // Kept next to the field rather than a toast that vanishes: the message
    // says which part of the link is wrong.
    videoError.value = e.message || 'Could not add that video'
  } finally {
    videoBusy.value = false
  }
}

async function uploadVideo(ev, entryId = null) {
  const file = ev.target.files?.[0]
  if (!file) return
  videoBusy.value = true
  videoError.value = ''
  const form = new FormData()
  form.append('file', file)
  if (newVideoTitle.value.trim()) form.append('title', newVideoTitle.value.trim())
  const path = entryId
    ? `/items/${id}/maintenance/${entryId}/videos`
    : `/items/${id}/videos`
  try {
    await api.upload(path, form)
    newVideoTitle.value = ''
    await loadAll()
    ui.toast('Video uploaded')
  } catch (e) {
    videoError.value = e.message || 'Could not upload that video'
  } finally {
    videoBusy.value = false
    ev.target.value = ''
  }
}

async function removeVideo(v) {
  if (!confirm(`Remove “${v.title || 'this video'}”? The item and its history are not affected.`)) return
  try {
    await api.del(`/videos/${v.id}`)
    await loadAll()
    ui.toast('Video removed')
  } catch (e) {
    ui.error(e.message || 'Could not remove that video')
  }
}

async function uploadFile(file) {
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('type', file.type.startsWith('image') ? 'photo' : 'attachment')
  form.append('name', file.name)
  try {
    item.value = await api.upload(`/items/${id}/attachments`, form)
    ui.toast('Attachment uploaded')
  } catch (e) {
    // Previously unhandled: an oversized or rejected upload threw into a void
    // and the user saw nothing happen at all.
    ui.error(e.message || 'Could not upload that file')
  }
}
function upload(e) { uploadFile(e.target.files[0]) }
function onCapture(file) { showCapture.value = false; uploadFile(file) }

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
      <span v-if="item.checkedOut" class="badge danger">📤 Checked out</span>
      <span v-else class="badge ok">✅ Here</span>
      <div class="grow"></div>
      <template v-if="editing">
        <button class="secondary" @click="editing = false; loadAll()">Cancel</button>
        <button @click="save">Save</button>
      </template>
      <template v-else>
        <button class="danger secondary" @click="remove">Delete</button>
        <button class="secondary" :disabled="describing" @click="describe"
          title="Look this item up online and store a searchable description">
          {{ describing ? 'Searching…' : '✨ Describe' }}</button>
        <button @click="editing = true">Edit</button>
      </template>
    </div>

    <div v-if="described" class="card" style="margin-bottom:12px">
      <p style="margin:0 0 4px">{{ described.description }}</p>
      <p v-if="described.sources.length" class="muted" style="font-size:0.8rem;margin:0">
        Sources: <a v-for="(s,i) in described.sources" :key="s" :href="s" target="_blank"
          rel="noopener noreferrer" style="margin-right:8px">[{{ i+1 }}]</a></p>
    </div>

    <div class="tabs">
      <button class="tab" :class="tab==='details'&&'active'" @click="tab='details'">Details</button>
      <button class="tab" :class="tab==='attachments'&&'active'" @click="tab='attachments'">
        Attachments <span class="badge" style="margin-left:4px">{{ item.attachments.length }}</span></button>
      <button class="tab" :class="tab==='maintenance'&&'active'" @click="tab='maintenance'">
        Maintenance <span class="badge" style="margin-left:4px">{{ maint.entries.length }}</span></button>
      <button class="tab" :class="tab==='videos'&&'active'" @click="tab='videos'">
        Videos <span class="badge" style="margin-left:4px">{{ itemVideos.length }}</span></button>
      <button class="tab" :class="tab==='qr'&&'active'" @click="tab='qr'">QR codes</button>
    </div>

    <!-- DETAILS -->
    <div v-show="tab==='details'">
      <!-- Check in / out -->
      <div class="card" style="margin-bottom:16px">
        <div class="row" style="flex-wrap:wrap;gap:12px">
          <div style="flex:1;min-width:180px">
            <template v-if="item.checkedOut">
              <strong>📤 Checked out{{ item.checkedOutTo ? ' to ' + item.checkedOutTo : '' }}</strong>
              <div class="muted txt-sm">
                Since {{ shortDate(item.checkedOutAt) }}<span v-if="item.checkoutDue"> · due {{ shortDate(item.checkoutDue) }}</span>
              </div>
            </template>
            <template v-else>
              <strong>✅ It's here</strong>
              <div class="muted txt-sm">Available in inventory.</div>
            </template>
          </div>
          <button v-if="item.checkedOut" @click="checkIn">Check in</button>
          <button v-else class="secondary" @click="checkOut">Check out</button>
        </div>

        <!-- Checked out immediately on click; these details are optional. -->
        <div v-if="showCheckout && item.checkedOut" style="margin-top:12px">
          <div class="muted" style="font-size:0.82rem;margin-bottom:8px">Add details (optional)</div>
          <div class="row" style="flex-wrap:wrap;gap:10px">
            <label class="field fill" style="margin:0;min-width:160px"><span>Who has it?</span>
              <input v-model="checkoutForm.person" placeholder="e.g. Alex, the garage, work" @keyup.enter="saveCheckoutDetails" /></label>
            <label class="field m-0"><span>Due back</span>
              <input type="date" v-model="checkoutForm.due" /></label>
          </div>
          <label class="field" style="margin:10px 0 0"><span>Notes</span>
            <input v-model="checkoutForm.notes" placeholder="e.g. lent for the weekend" @keyup.enter="saveCheckoutDetails" /></label>
          <div class="row" style="justify-content:flex-end;gap:8px;margin-top:10px">
            <button class="ghost" @click="showCheckout=false">Skip</button>
            <button @click="saveCheckoutDetails">Save details</button>
          </div>
        </div>

        <div v-if="item.checkoutHistory && item.checkoutHistory.length" class="muted"
             style="margin-top:12px;font-size:0.82rem">
          <span v-for="(h,idx) in item.checkoutHistory.slice(0,3)" :key="h.id">
            {{ h.action === 'out' ? '📤 out' : '📥 in' }}{{ h.person ? ' · ' + h.person : '' }}
            ({{ shortDate(h.at) }}){{ idx < Math.min(2, item.checkoutHistory.length-1) ? ' — ' : '' }}
          </span>
        </div>
      </div>

      <div class="row top" style="gap:16px;align-items:stretch">
        <div class="card fill">
          <template v-if="!editing">
            <p v-if="item.description">{{ item.description }}</p>
            <dl class="kv">
              <!-- Linked: "where is it" is the question this app exists to
                   answer, and the answer was a dead end you had to re-navigate
                   to by hand. Matches the breadcrumb's existing link style. -->
              <dt>Location</dt>
              <dd><router-link v-if="item.location" :to="'/locations/' + item.location.id">{{ item.location.name }}</router-link>
                  <template v-else>—</template></dd>
              <dt>Bin</dt>
              <dd><router-link v-if="item.bin" :to="'/bins/' + item.bin.id">{{ item.bin.name }}</router-link>
                  <template v-else>—</template></dd>
              <dt>Quantity</dt><dd>{{ item.quantity }}<span v-if="item.placementCount > 1" class="muted"> · in {{ item.placementCount }} places</span></dd>
              <dt>Manufacturer</dt><dd>{{ item.manufacturer || '—' }}</dd>
              <dt>Model #</dt><dd>{{ item.modelNumber || '—' }}</dd>
              <dt>Serial #</dt><dd>{{ item.serialNumber || '—' }}</dd>
              <dt>Barcode</dt><dd>{{ item.barcode || '—' }}</dd>
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

            <!-- Placements: this item's quantity across bins/locations -->
            <div class="divider"></div>
            <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:6px">
              <strong>Placements</strong>
              <span class="muted sm">{{ item.quantity }} total</span>
            </div>
            <div v-for="h in item.holdings" :key="h.id" class="row"
              style="align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
              <span class="fill">
                <router-link v-if="h.bin" :to="'/bins/' + h.bin.id">{{ h.bin.name }}</router-link>
                <router-link v-else-if="h.location" :to="'/locations/' + h.location.id">{{ h.location.name }}</router-link>
                <template v-else>Unassigned</template>
                <span v-if="h.bin && h.location" class="muted sm">·
                  <router-link :to="'/locations/' + h.location.id">{{ h.location.name }}</router-link>
                </span></span>
              <input type="number" min="0" step="1" style="width:76px" :value="h.quantity"
                @change="(e) => editHolding(h, e.target.value)" />
              <button class="secondary sm" @click="openMove(h)">Move</button>
              <button v-if="item.holdings.length > 1" class="danger secondary sm"
                title="Remove this placement" @click="removeHolding(h)">✕</button>
            </div>
            <div class="row" style="gap:8px;margin-top:10px;align-items:flex-end">
              <label class="field fill"><span>Add placement — bin</span>
                <select v-model="placement.binId">
                  <option value="">(choose a bin)</option>
                  <option v-for="b in bins" :key="b.id" :value="b.id">{{ b.name }}</option>
                </select></label>
              <label class="field" style="width:88px"><span>Qty</span>
                <input type="number" min="1" v-model.number="placement.quantity" /></label>
              <button :disabled="!placement.binId" @click="addPlacement">Add</button>
            </div>
          </template>

          <!-- EDIT FORM -->
          <template v-else>
            <label class="field"><span>Name</span><input v-model="item.name" /></label>
            <label class="field"><span>Description</span><textarea v-model="item.description" rows="2"></textarea></label>
            <div class="row">
              <label class="field fill"><span>Quantity</span><input type="number" v-model.number="item.quantity" /></label>
              <label class="field fill" title="At or below this, the item shows on the Restock list. Leave blank for things that aren't consumables.">
                <span>Min (restock at)</span>
                <input type="number" min="0" v-model.number="item.minQuantity" placeholder="—" /></label>
              <label class="field fill" title="Restock suggests buying enough to reach this.">
                <span>Target</span>
                <input type="number" min="0" v-model.number="item.targetQuantity" placeholder="—" /></label>
              <label class="field fill"><span>Bin</span>
                <select v-model="binId" @change="onBinChange"><option value="">None</option>
                  <option v-for="b in bins" :key="b.id" :value="b.id">{{ b.name }}</option></select></label>
              <label class="field fill">
                <span>Location{{ binId ? ' (from bin)' : '' }}</span>
                <select v-model="locationId" :disabled="!!binId">
                  <option value="">None</option>
                  <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option></select></label>
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
              <label class="field fill"><span>Barcode</span>
                <input v-model="item.barcode" maxlength="64" placeholder="UPC / EAN" /></label>
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
      <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
        <input type="file" @change="upload" aria-label="Upload a photo or file" />
        <button type="button" class="secondary sm" @click="showCapture = true">📷 Take photo</button>
      </div>
    </div>
    <PhotoCapture v-if="showCapture" @captured="onCapture" @close="showCapture = false" />

    <!-- MAINTENANCE -->
    <div v-show="tab==='maintenance'" class="card">
      <div class="row" style="margin-bottom:12px">
        <h2 style="margin:0;flex:1">Log</h2>
        <span class="badge">Total: {{ money(maint.costTotal) }}</span>
      </div>
      <table v-if="maint.entries.length">
        <thead><tr><th>Name</th><th>Scheduled</th><th>Completed</th><th>Cost</th></tr></thead>
        <tbody><tr v-for="m in maint.entries" :key="m.id">
          <td>{{ m.name }}<div class="muted" style="font-size:0.8rem">{{ m.description }}</div>
            <div v-if="m.videos && m.videos.length" class="task-videos">
              <a v-for="v in m.videos" :key="v.id"
                 :href="v.url || apiUrl(v.streamUrl.replace('/api/v1',''))"
                 target="_blank" rel="noopener noreferrer" class="badge">▶ {{ v.title }}</a>
            </div>
            <button class="secondary sm mt-6"
                    @click="videoFor = (videoFor === m.id ? null : m.id)">
              {{ videoFor === m.id ? 'Cancel' : '+ Video' }}</button>
            <div v-if="videoFor === m.id" class="row wrap" style="gap:6px;margin-top:6px">
              <input v-model="newVideoUrl" placeholder="https://youtu.be/…" style="min-width:160px" />
              <button :disabled="videoBusy" @click="addVideo(m.id); videoFor = null">Add</button>
              <label class="secondary btnlike sm">Upload
                <input type="file" accept="video/*" hidden :disabled="videoBusy"
                       @change="uploadVideo($event, m.id); videoFor = null" /></label>
            </div>
          </td>
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
        <label class="field m-0"><span>Scheduled</span><input type="date" v-model="newMaint.scheduledDate" /></label>
        <label class="field m-0"><span>Completed</span><input type="date" v-model="newMaint.completedDate" /></label>
        <button :disabled="!newMaint.name" @click="addMaint">Add</button>
      </div>
    </div>

    <!-- VIDEOS -->
    <div v-show="tab==='videos'" class="card">
      <h2 style="margin:0 0 4px">How it works</h2>
      <p class="muted" style="margin:0 0 12px;font-size:0.85rem">
        Videos for the thing itself. For a clip about one job — changing a
        filter, replacing a belt — add it to that task under Maintenance, so it
        is in front of you when the job comes due.
      </p>

      <div v-if="itemVideos.length" class="video-list">
        <div v-for="v in itemVideos" :key="v.id" class="video">
          <video v-if="v.streamUrl" :src="apiUrl(v.streamUrl.replace('/api/v1',''))"
                 controls preload="metadata"></video>
          <iframe v-else-if="v.embedUrl" :src="v.embedUrl" loading="lazy"
                  allowfullscreen referrerpolicy="no-referrer" title="How-to video"></iframe>
          <a v-else :href="v.url" target="_blank" rel="noopener noreferrer" class="video-link">
            ▶ Watch on {{ videoHost(v.url) }} ↗</a>
          <div class="video-foot">
            <span class="fill">{{ v.title }}</span>
            <button class="secondary sm" @click="removeVideo(v)">Remove</button>
          </div>
        </div>
      </div>

      <p v-else class="muted" style="margin:0 0 12px">
        No videos yet. Paste a link to a manual walkthrough or teardown — or
        upload a clip of your own — so you can see how it works without hunting
        for it again.
      </p>

      <div class="row wrap" style="align-items:flex-end;gap:10px">
        <label class="field fill" style="margin:0;min-width:180px"><span>Video link</span>
          <input v-model="newVideoUrl" placeholder="https://youtu.be/…" @keyup.enter="addVideo()" /></label>
        <label class="field" style="margin:0;width:170px"><span>Title (optional)</span>
          <input v-model="newVideoTitle" placeholder="e.g. Filter teardown" /></label>
        <button :disabled="videoBusy" @click="addVideo()">
          {{ videoBusy ? 'Adding…' : 'Add link' }}</button>
        <label class="secondary btnlike">
          {{ videoBusy ? 'Uploading…' : 'Upload a file' }}
          <input type="file" accept="video/*" hidden :disabled="videoBusy" @change="uploadVideo($event)" />
        </label>
      </div>
      <p v-if="videoError" class="err" style="margin:8px 0 0">{{ videoError }}</p>
    </div>

    <!-- QR -->
    <!-- v-if so the panel's scan field can autofocus on open (see BinDetail). -->
    <div v-if="tab==='qr'">
      <QrPanel kind="item" :target-id="item.id" />
    </div>
  </div>

  <div v-else class="card"><div class="skeleton" style="height:300px"></div></div>

  <!-- Move a placement -->
  <div v-if="moveFor" @click.self="moveFor = null"
    style="position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:50">
    <div class="card" style="width:min(420px,92vw)">
      <h3 style="margin-top:0">Move from {{ moveFor.bin?.name || moveFor.location?.name || 'Unassigned' }}</h3>
      <label class="field"><span>To bin</span>
        <select v-model="moveForm.toBinId">
          <option value="">(no bin)</option>
          <option v-for="b in bins" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select></label>
      <label class="field"><span>Quantity to move (max {{ moveFor.quantity }})</span>
        <input type="number" min="1" :max="moveFor.quantity" v-model.number="moveForm.quantity" /></label>
      <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px">
        <button class="ghost" @click="moveFor = null">Cancel</button>
        <button @click="doMove">Move</button>
      </div>
    </div>
  </div>
</template>
