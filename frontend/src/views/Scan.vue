<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUI()

const state = ref('resolving') // resolving | unknown
const code = ref('')
const kind = ref('item')
const targetId = ref('')
const targets = ref({ item: [], bin: [], location: [] })
const newName = ref('')
const busy = ref(false)

function dest(k, id) {
  return { item: '/items/' + id, bin: '/bins/' + id, location: '/locations/' + id }[k]
}

async function resolve() {
  code.value = decodeURIComponent(route.params.token)
  // Inventory-only check — no outbound lookups.
  const res = await api.get('/barcode/' + encodeURIComponent(code.value))
  if (res.status === 'registered') {
    // Item → its page; bin/location → its page, which lists what's inside.
    router.replace(dest(res.kind, res.targetId))
    return
  }
  state.value = 'unknown'
  const [items, bins, locs] = await Promise.all([
    api.get('/items?pageSize=500'), api.get('/bins'), api.get('/locations'),
  ])
  targets.value = { item: items.items, bin: bins, location: locs }
}

async function createAndLink() {
  if (!newName.value.trim()) return
  busy.value = true
  try {
    const item = await api.post('/items', { name: newName.value.trim() })
    await api.post('/qr-tags', {
      kind: 'item', targetId: item.id, source: 'external',
      code: code.value, codeFormat: 'barcode',
    })
    ui.toast('Item created and code linked')
    router.replace('/items/' + item.id)
  } catch (e) {
    ui.error(e.message)
    busy.value = false
  }
}

async function linkExisting() {
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
    <div class="card" style="width:460px;max-width:100%">
      <template v-if="state === 'resolving'">
        <p class="muted" style="text-align:center">Checking inventory…</p>
      </template>

      <template v-else>
        <h2>Not in inventory</h2>
        <p class="muted" style="margin-top:0">
          <code style="font-family:monospace">{{ code }}</code> isn't linked to anything yet.
        </p>

        <label class="field"><span>Create a new item &amp; link this code</span>
          <input v-model="newName" placeholder="Item name" @keyup.enter="createAndLink" /></label>
        <div class="row" style="justify-content:flex-end;margin-bottom:14px">
          <button :disabled="!newName.trim() || busy" @click="createAndLink">＋ Create &amp; link</button>
        </div>

        <div class="divider"></div>

        <p class="muted" style="font-size:0.85rem">Or link this code to an existing record:</p>
        <div class="row">
          <select v-model="kind" @change="targetId=''" style="width:auto">
            <option value="item">Item</option>
            <option value="bin">Bin</option>
            <option value="location">Location</option>
          </select>
          <select v-model="targetId">
            <option value="">Select…</option>
            <option v-for="t in targets[kind]" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <button class="secondary" :disabled="!targetId || busy" @click="linkExisting">Link</button>
        </div>

        <div class="row" style="justify-content:flex-end;margin-top:14px">
          <button class="ghost" @click="router.push('/')">Cancel</button>
        </div>
      </template>
    </div>
  </div>
</template>
