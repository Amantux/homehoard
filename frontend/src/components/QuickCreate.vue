<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'
import Combobox from './Combobox.vue'
import { indexById, pathString } from '../locationTree'
import { parseQuickAdd } from '../quickParse'

const props = defineProps({ initialKind: { type: String, default: 'item' } })
const emit = defineEmits(['close', 'created'])
const router = useRouter()
const ui = useUI()

const kind = ref(props.initialKind)
const smart = ref('')
const name = ref('')
const description = ref('')
const quantity = ref(1)
const locationId = ref('')
const binId = ref('')
const code = ref('')
const locations = ref([])
const bins = ref([])
const busy = ref(false)
const sessionCount = ref(0)
const nameInput = ref(null)
const suggestions = ref([])
const parsedPlace = ref('') // free text from NL that didn't match anything yet

async function loadPlaces() {
  const [locs, bs] = await Promise.all([api.get('/locations'), api.get('/bins')])
  locations.value = locs
  bins.value = bs
}
onMounted(loadPlaces)
watch(() => props.initialKind, (k) => (kind.value = k))

// An item placed in a bin inherits that bin's location, so mirror it in the UI.
watch(binId, (id) => {
  const b = bins.value.find((x) => x.id === id)
  if (b && b.location) locationId.value = b.location.id
})

const byId = computed(() => indexById(locations.value))
const locationOptions = computed(() =>
  locations.value
    .map((l) => ({ id: l.id, label: pathString(l, byId.value) }))
    .sort((a, b) => a.label.localeCompare(b.label)),
)
const binOptions = computed(() =>
  bins.value.map((b) => ({ id: b.id, label: b.name, sublabel: b.location?.name || '' })),
)

// --- Create bins/locations on the fly from the comboboxes ------------------
async function createLocation(newName, { select = true } = {}) {
  const loc = await api.post('/locations', { name: newName })
  await loadPlaces()
  if (select) { binId.value = ''; locationId.value = loc.id }
  return loc
}
async function createBin(newName) {
  // A new bin lives in the currently-chosen location (if any).
  const b = await api.post('/bins', { name: newName, locationId: locationId.value || null })
  await loadPlaces()
  binId.value = b.id
}

// --- Natural-language quick add -------------------------------------------
function applySmart() {
  const parsed = parseQuickAdd(smart.value)
  name.value = parsed.name
  quantity.value = parsed.quantity || 1
  parsedPlace.value = ''
  if (!parsed.placeText) return
  const term = parsed.placeText.toLowerCase()
  const bin = bins.value.find((b) => b.name.toLowerCase().includes(term))
  if (bin) { binId.value = bin.id; return }
  const loc = locations.value.find(
    (l) => pathString(l, byId.value).toLowerCase().includes(term),
  )
  if (loc) { binId.value = ''; locationId.value = loc.id; return }
  parsedPlace.value = parsed.placeText // no match → offer to create it
}
async function createParsedPlace() {
  const text = parsedPlace.value
  parsedPlace.value = ''
  try { await createLocation(text) } catch (e) { ui.error(e.message) }
}

// --- Suggested placement (where similar items already live) ----------------
let suggestTimer
watch([name, kind], () => {
  clearTimeout(suggestTimer)
  suggestions.value = []
  if (kind.value !== 'item' || !name.value.trim()) return
  suggestTimer = setTimeout(async () => {
    try {
      const res = await api.get(
        '/items/suggest-placement?limit=3&name=' + encodeURIComponent(name.value.trim()),
      )
      suggestions.value = res.suggestions || []
    } catch (e) { /* non-critical */ }
  }, 300)
})
onUnmounted(() => clearTimeout(suggestTimer))
function applySuggestion(s) {
  if (s.type === 'bin') binId.value = s.id
  else { binId.value = ''; locationId.value = s.id }
}
const chosenPlaceId = computed(() => binId.value || locationId.value)

const kinds = [
  { id: 'item', label: 'Item', icon: '📦' },
  { id: 'bin', label: 'Bin', icon: '🗃️' },
  { id: 'location', label: 'Location', icon: '📍' },
  { id: 'label', label: 'Label', icon: '🏷️' },
]

async function linkCode(kindName, targetId) {
  if (!code.value.trim()) return
  try {
    await api.post('/qr-tags', {
      kind: kindName, targetId, source: 'external',
      code: code.value.trim(), codeFormat: 'barcode',
    })
  } catch (e) {
    ui.error('Created, but the barcode link failed: ' + e.message)
  }
}

function resetPerItem() {
  smart.value = ''
  name.value = ''
  description.value = ''
  code.value = ''
  quantity.value = 1
  suggestions.value = []
  parsedPlace.value = ''
}

// stay = keep the modal open for the next item (bin/location stay selected).
async function submit(stay = false) {
  if (!name.value || busy.value) return
  busy.value = true
  try {
    let created
    if (kind.value === 'item') {
      created = await api.post('/items', {
        name: name.value, description: description.value,
        quantity: Number(quantity.value) || 1,
        binId: binId.value || null,
        locationId: binId.value ? null : (locationId.value || null),
      })
      await linkCode('item', created.id)
      if (!stay) router.push('/items/' + created.id)
    } else if (kind.value === 'bin') {
      created = await api.post('/bins', {
        name: name.value, description: description.value, locationId: locationId.value || null,
      })
      await linkCode('bin', created.id)
      if (!stay) router.push('/bins/' + created.id)
    } else if (kind.value === 'location') {
      created = await api.post('/locations', { name: name.value, description: description.value })
      await linkCode('location', created.id)
      if (!stay) router.push('/locations')
    } else {
      await api.post('/labels', { name: name.value, description: description.value })
      if (!stay) router.push('/labels')
    }
    sessionCount.value += 1
    ui.toast(`${name.value} created`)
    emit('created')
    if (stay) {
      resetPerItem()
      await nextTick()
      nameInput.value?.focus()
    } else {
      emit('close')
    }
  } catch (e) {
    ui.error(e.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="card modal">
      <div class="modal-head">
        <h2>Create</h2>
        <button class="ghost icon-btn" @click="emit('close')">✕</button>
      </div>

      <div class="row wrap type-picker" style="gap:8px;margin-bottom:16px">
        <button v-for="k in kinds" :key="k.id"
                :class="kind === k.id ? '' : 'secondary'"
                class="sm" @click="kind = k.id">
          {{ k.icon }} {{ k.label }}
        </button>
      </div>

      <!-- Item: natural-language quick add -->
      <template v-if="kind === 'item'">
        <label class="field"><span>Quick add <span class="muted" style="font-weight:400">— optional</span></span>
          <input v-model="smart" placeholder="e.g. 3 AA batteries in the kitchen drawer"
                 aria-label="Quick add" @input="applySmart" @keyup.enter="submit(true)" /></label>
        <p v-if="parsedPlace" class="muted" style="margin:-8px 0 12px;font-size:0.85rem">
          No place called “{{ parsedPlace }}” yet —
          <a href="#" @click.prevent="createParsedPlace">create location “{{ parsedPlace }}”</a>
        </p>
      </template>

      <label class="field"><span>Name</span>
        <input ref="nameInput" v-model="name" autofocus placeholder="e.g. Cordless Drill"
               @keyup.enter="submit(true)" /></label>
      <label class="field"><span>Description</span>
        <textarea v-model="description" rows="2"></textarea></label>

      <label v-if="kind === 'item'" class="field" style="max-width:130px"><span>Quantity</span>
        <input type="number" min="1" v-model.number="quantity" @keyup.enter="submit(true)" /></label>

      <!-- Item: bin (location follows) or a bare location, both free-text -->
      <div v-if="kind === 'item'" class="row wrap">
        <label class="field fill"><span>Bin</span>
          <Combobox v-model="binId" :options="binOptions" allow-create create-noun="bin"
                    aria-label="Bin" placeholder="Search or create a bin…" @create="createBin" />
        </label>
        <label class="field fill">
          <span>Location{{ binId ? ' (from bin)' : '' }}</span>
          <Combobox v-if="!binId" v-model="locationId" :options="locationOptions"
                    allow-create create-noun="location" aria-label="Location"
                    placeholder="Search or create a location…" @create="createLocation" />
          <input v-else :value="bins.find(b => b.id === binId)?.location?.name || '—'" disabled />
        </label>
      </div>

      <!-- Item: one-tap suggested placements -->
      <div v-if="kind === 'item' && suggestions.length && !chosenPlaceId"
           class="suggest-row">
        <span class="muted" style="font-size:0.82rem">Put it in:</span>
        <button v-for="s in suggestions" :key="s.type + s.id" type="button"
                class="chip suggest-chip" @click="applySuggestion(s)">
          {{ s.type === 'bin' ? '🗃️' : '📍' }} {{ s.name }}
          <span class="muted" v-if="s.basis === 'similar'">· {{ s.count }} similar</span>
        </button>
      </div>

      <!-- Bin: choose its location (free-text) -->
      <label v-if="kind === 'bin'" class="field"><span>Location</span>
        <Combobox v-model="locationId" :options="locationOptions" allow-create
                  create-noun="location" aria-label="Location"
                  placeholder="Search or create a location…" @create="createLocation" />
      </label>

      <!-- Barcode / QR — attach a code you can scan later -->
      <label v-if="kind !== 'label'" class="field"><span>Barcode / QR code (optional)</span>
        <input v-model="code" placeholder="Scan or type a code to attach"
               @keyup.enter="submit(true)" /></label>

      <div class="row" style="justify-content:space-between;align-items:center;margin-top:6px">
        <span class="muted" style="font-size:0.85rem">{{ sessionCount ? sessionCount + ' added' : '' }}</span>
        <div class="row" style="gap:8px">
          <button class="secondary" @click="emit('close')">{{ sessionCount ? 'Done' : 'Cancel' }}</button>
          <button class="secondary" :disabled="!name || busy" @click="submit(true)">Save &amp; add another</button>
          <button :disabled="!name || busy" @click="submit(false)">Create {{ kind }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.suggest-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: -4px 0 14px; }
.suggest-chip { cursor: pointer; border: 1px solid var(--accent); background: var(--accent-soft); }
.suggest-chip:hover { background: var(--accent); color: var(--accent-fg); }
.suggest-chip:hover .muted { color: var(--accent-fg); }
</style>
