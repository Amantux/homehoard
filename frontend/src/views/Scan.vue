<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUI()

const state = ref('resolving') // resolving | assign | error
const code = ref('')
const kind = ref('item')
const targetId = ref('')
const targets = ref({ item: [], bin: [], location: [] })
const busy = ref(false)

function dest(kind, id) {
  return { item: '/items/' + id, bin: '/bins/' + id, location: '/locations/' + id }[kind]
}

async function resolve() {
  code.value = decodeURIComponent(route.params.token)
  try {
    const tag = await api.get('/qr-tags/resolve/' + encodeURIComponent(code.value))
    router.replace(dest(tag.kind, tag.targetId))
  } catch (e) {
    // Unknown code — offer to assign it.
    state.value = 'assign'
    const [items, bins, locs] = await Promise.all([
      api.get('/items?pageSize=500'), api.get('/bins'), api.get('/locations'),
    ])
    targets.value = { item: items.items, bin: bins, location: locs }
  }
}

async function assign() {
  if (!targetId.value) return
  busy.value = true
  try {
    await api.post('/qr-tags', {
      kind: kind.value, targetId: targetId.value,
      source: 'external', code: code.value, codeFormat: 'barcode',
    })
    ui.toast('Code linked')
    router.replace(dest(kind.value, targetId.value))
  } catch (e) {
    ui.error(e.message)
    busy.value = false
  }
}

onMounted(resolve)
</script>

<template>
  <div class="center-screen">
    <div class="card" style="width:440px;max-width:100%">
      <template v-if="state === 'resolving'">
        <p class="muted" style="text-align:center">Resolving code…</p>
      </template>

      <template v-else-if="state === 'assign'">
        <h2>Unrecognized code</h2>
        <p class="muted">
          <code style="font-family:monospace">{{ code }}</code> isn't linked to anything yet.
          Link it to an item, bin, or location:
        </p>
        <label class="field"><span>Type</span>
          <select v-model="kind" @change="targetId=''">
            <option value="item">Item</option>
            <option value="bin">Bin</option>
            <option value="location">Location</option>
          </select>
        </label>
        <label class="field"><span>{{ kind }}</span>
          <select v-model="targetId">
            <option value="">Select…</option>
            <option v-for="t in targets[kind]" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </label>
        <div class="row" style="justify-content:flex-end">
          <button class="secondary" @click="router.push('/')">Cancel</button>
          <button :disabled="!targetId || busy" @click="assign">Link code</button>
        </div>
      </template>
    </div>
  </div>
</template>
