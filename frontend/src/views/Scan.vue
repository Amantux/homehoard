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
const product = ref(null)
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
  // One call: resolves a registered code, else returns product info for barcodes.
  const res = await api.get('/barcode/' + encodeURIComponent(code.value))
  if (res.status === 'registered') {
    router.replace(dest(res.kind, res.targetId))
    return
  }
  product.value = res.product
  newName.value = res.product?.name || ''
  state.value = 'unknown'
  const [items, bins, locs] = await Promise.all([
    api.get('/items?pageSize=500'), api.get('/bins'), api.get('/locations'),
  ])
  targets.value = { item: items.items, bin: bins, location: locs }
}

async function createFromBarcode() {
  if (!newName.value.trim()) return
  busy.value = true
  try {
    const item = await api.post('/items', {
      name: newName.value.trim(),
      manufacturer: product.value?.manufacturer || '',
    })
    // Link the scanned barcode so it resolves straight to this item next time.
    await api.post('/qr-tags', {
      kind: 'item', targetId: item.id, source: 'external',
      code: code.value, codeFormat: 'barcode',
    })
    ui.toast('Item created from barcode')
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
        <p class="muted" style="text-align:center">Looking up code…</p>
      </template>

      <template v-else>
        <h2>New code scanned</h2>
        <p class="muted" style="margin-top:0">
          <code style="font-family:monospace">{{ code }}</code> isn't in your inventory yet.
        </p>

        <div v-if="product" class="card" style="box-shadow:none;display:flex;gap:12px;align-items:center;margin-bottom:14px">
          <img v-if="product.imageUrl" :src="product.imageUrl" alt=""
               style="width:56px;height:56px;object-fit:contain;border-radius:8px"
               @error="$event.target.style.display='none'" />
          <div style="min-width:0">
            <div style="font-weight:600">{{ product.name }}</div>
            <div class="muted" style="font-size:0.85rem">
              {{ product.manufacturer || product.category || 'Product match' }}
            </div>
          </div>
        </div>

        <!-- Create a new item (name prefilled from the barcode lookup) -->
        <label class="field"><span>Create a new item</span>
          <input v-model="newName" placeholder="Item name" /></label>
        <div class="row" style="justify-content:flex-end;margin-bottom:14px">
          <button :disabled="!newName.trim() || busy" @click="createFromBarcode">
            ＋ Create &amp; link
          </button>
        </div>

        <div class="divider"></div>

        <!-- Or link to something that already exists -->
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
