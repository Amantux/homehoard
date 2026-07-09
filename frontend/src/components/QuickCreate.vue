<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'

const props = defineProps({ initialKind: { type: String, default: 'item' } })
const emit = defineEmits(['close', 'created'])
const router = useRouter()
const ui = useUI()

const kind = ref(props.initialKind)
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

onMounted(async () => {
  try {
    const [locs, bs] = await Promise.all([api.get('/locations'), api.get('/bins')])
    locations.value = locs
    bins.value = bs
  } catch (e) { /* ignore */ }
})
watch(() => props.initialKind, (k) => (kind.value = k))

// An item placed in a bin inherits that bin's location, so mirror it in the UI.
watch(binId, (id) => {
  const b = bins.value.find((x) => x.id === id)
  if (b && b.location) locationId.value = b.location.id
})

const kinds = [
  { id: 'item', label: 'Item', icon: '📦' },
  { id: 'bin', label: 'Bin', icon: '🗃️' },
  { id: 'location', label: 'Location', icon: '📍' },
  { id: 'label', label: 'Label', icon: '🏷️' },
]

// Optionally attach a scanned/typed barcode to the freshly-created thing.
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

// stay = keep the modal open for the next item (bin/location stay selected).
async function submit(stay = false) {
  if (!name.value) return
  busy.value = true
  try {
    let created
    if (kind.value === 'item') {
      // binId wins — the backend inherits the bin's location automatically.
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
      // Keep the sticky container; clear only the per-item fields.
      name.value = ''
      description.value = ''
      code.value = ''
      quantity.value = 1
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

      <label class="field"><span>Name</span>
        <input ref="nameInput" v-model="name" autofocus placeholder="e.g. Cordless Drill"
               @keyup.enter="submit(true)" /></label>
      <label class="field"><span>Description</span>
        <textarea v-model="description" rows="2"></textarea></label>

      <label v-if="kind === 'item'" class="field" style="max-width:130px"><span>Quantity</span>
        <input type="number" min="1" v-model.number="quantity" @keyup.enter="submit(true)" /></label>

      <!-- Item: choose a bin (location follows) or a bare location -->
      <div v-if="kind === 'item'" class="row">
        <label class="field fill"><span>Bin</span>
          <select v-model="binId">
            <option value="">None</option>
            <option v-for="b in bins" :key="b.id" :value="b.id">
              {{ b.name }}<template v-if="b.location"> · {{ b.location.name }}</template>
            </option>
          </select>
        </label>
        <label class="field fill">
          <span>Location{{ binId ? ' (from bin)' : '' }}</span>
          <select v-model="locationId" :disabled="!!binId">
            <option value="">None</option>
            <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
          </select>
        </label>
      </div>

      <!-- Bin: choose its location -->
      <label v-if="kind === 'bin'" class="field"><span>Location</span>
        <select v-model="locationId">
          <option value="">None</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
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
