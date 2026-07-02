<script setup>
import { ref, watch, onMounted } from 'vue'
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
const locationId = ref('')
const locations = ref([])
const busy = ref(false)

onMounted(async () => {
  try { locations.value = await api.get('/locations') } catch (e) { /* ignore */ }
})
watch(() => props.initialKind, (k) => (kind.value = k))

const kinds = [
  { id: 'item', label: 'Item', icon: '📦' },
  { id: 'bin', label: 'Bin', icon: '🗃️' },
  { id: 'location', label: 'Location', icon: '📍' },
  { id: 'label', label: 'Label', icon: '🏷️' },
]

async function submit() {
  if (!name.value) return
  busy.value = true
  try {
    let created
    if (kind.value === 'item') {
      created = await api.post('/items', { name: name.value, description: description.value, locationId: locationId.value || null })
      router.push('/items/' + created.id)
    } else if (kind.value === 'bin') {
      created = await api.post('/bins', { name: name.value, description: description.value, locationId: locationId.value || null })
      router.push('/bins/' + created.id)
    } else if (kind.value === 'location') {
      await api.post('/locations', { name: name.value, description: description.value })
      router.push('/locations')
    } else {
      await api.post('/labels', { name: name.value, description: description.value })
      router.push('/labels')
    }
    ui.toast(`${name.value} created`)
    emit('created')
    emit('close')
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

      <div class="row wrap" style="gap:8px;margin-bottom:16px">
        <button v-for="k in kinds" :key="k.id"
                :class="kind === k.id ? '' : 'secondary'"
                class="sm" @click="kind = k.id">
          {{ k.icon }} {{ k.label }}
        </button>
      </div>

      <label class="field"><span>Name</span>
        <input v-model="name" autofocus placeholder="e.g. Cordless Drill"
               @keyup.enter="submit" /></label>
      <label class="field"><span>Description</span>
        <textarea v-model="description" rows="2"></textarea></label>
      <label v-if="kind === 'item' || kind === 'bin'" class="field"><span>Location</span>
        <select v-model="locationId">
          <option value="">None</option>
          <option v-for="l in locations" :key="l.id" :value="l.id">{{ l.name }}</option>
        </select>
      </label>

      <div class="row" style="justify-content:flex-end;margin-top:6px">
        <button class="secondary" @click="emit('close')">Cancel</button>
        <button :disabled="!name || busy" @click="submit">Create {{ kind }}</button>
      </div>
    </div>
  </div>
</template>
