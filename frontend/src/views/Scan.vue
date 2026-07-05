<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUI()

const state = ref('resolving') // resolving | unknown | action
const code = ref('')
const kind = ref('item')
const targetId = ref('')
const targets = ref({ item: [], bin: [], location: [] })
const newName = ref('')
const busy = ref(false)
// When the scan was launched in "check out / in" mode we act on the item
// instead of just opening it.
const action = ref(route.query.action || '')
const item = ref(null)
const container = ref(null)
const containerKind = ref('')

function dest(k, id) {
  return { item: '/items/' + id, bin: '/bins/' + id, location: '/locations/' + id }[k]
}

async function resolve() {
  code.value = decodeURIComponent(route.params.token)
  // Inventory-only check — no outbound lookups.
  const res = await api.get('/barcode/' + encodeURIComponent(code.value))
  if (res.status === 'registered') {
    // In an action-mode scan, show a quick card instead of navigating away.
    if (action.value && res.kind === 'item') {
      item.value = res.target
      state.value = 'action'
      return
    }
    // Bin / location scanned in action mode → glance at what's inside.
    if (action.value && (res.kind === 'bin' || res.kind === 'location')) {
      container.value = res.target
      containerKind.value = res.kind
      state.value = 'container'
      return
    }
    // Otherwise: item → its page; bin/location → its page listing what's inside.
    router.replace(dest(res.kind, res.targetId))
    return
  }
  state.value = 'unknown'
  const [items, bins, locs] = await Promise.all([
    api.get('/items?pageSize=500'), api.get('/bins'), api.get('/locations'),
  ])
  targets.value = { item: items.items, bin: bins, location: locs }
}

async function checkOut() {
  busy.value = true
  try {
    await api.post(`/items/${item.value.id}/checkout`, {})
    ui.toast('Checked out ' + item.value.name)
    router.replace('/items/' + item.value.id)
  } catch (e) { ui.error(e.message); busy.value = false }
}
async function checkIn() {
  busy.value = true
  try {
    await api.post(`/items/${item.value.id}/checkin`, {})
    ui.toast('Checked in ' + item.value.name)
    router.replace('/items/' + item.value.id)
  } catch (e) { ui.error(e.message); busy.value = false }
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

      <!-- Scan-to-checkout: act on the item right here. -->
      <template v-else-if="state === 'action'">
        <h2 style="margin-top:0">{{ item.name }}</h2>
        <p class="muted" style="margin-top:0">
          {{ item.bin?.name || item.location?.name || 'Unassigned' }}
          <span v-if="item.checkedOut" class="badge danger" style="margin-left:6px">📤 Checked out{{ item.checkedOutTo ? ' to ' + item.checkedOutTo : '' }}</span>
          <span v-else class="badge ok" style="margin-left:6px">✅ Here</span>
        </p>

        <div class="row" style="gap:8px">
          <button v-if="!item.checkedOut" :disabled="busy" @click="checkOut">📤 Check out</button>
          <button v-else :disabled="busy" @click="checkIn">📥 Check in</button>
          <button class="secondary" @click="router.replace('/items/' + item.id)">Open</button>
          <button class="ghost" @click="router.push('/')">Cancel</button>
        </div>
      </template>

      <!-- Scanned a bin / location: glance at what's inside. -->
      <template v-else-if="state === 'container'">
        <h2 style="margin-top:0">
          {{ containerKind === 'bin' ? '📦' : '📍' }} {{ container.name }}
        </h2>
        <p class="muted" style="margin-top:0">
          {{ (container.items || []).length }} item{{ (container.items || []).length === 1 ? '' : 's' }}
          <span v-if="containerKind === 'location' && (container.bins || []).length">
            · {{ container.bins.length }} bin{{ container.bins.length === 1 ? '' : 's' }}</span>
        </p>

        <ul v-if="(container.items || []).length" style="margin:0 0 12px;padding-left:18px;max-height:220px;overflow:auto">
          <li v-for="i in container.items" :key="i.id">
            {{ i.name }}<span v-if="i.checkedOut" class="badge danger" style="margin-left:6px">out</span>
          </li>
        </ul>
        <p v-else class="muted">It's empty.</p>

        <div v-if="containerKind === 'location' && (container.bins || []).length" class="muted" style="font-size:0.85rem;margin-bottom:12px">
          Bins: <span v-for="(b, idx) in container.bins" :key="b.id">{{ b.name }} ({{ b.itemCount }}){{ idx < container.bins.length - 1 ? ', ' : '' }}</span>
        </div>

        <div class="row" style="gap:8px">
          <button class="secondary" @click="router.replace(dest(containerKind, container.id))">Open</button>
          <button class="ghost" @click="router.push('/')">Done</button>
        </div>
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
