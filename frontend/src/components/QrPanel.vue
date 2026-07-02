<script setup>
import { ref, onMounted } from 'vue'
import { api, apiUrl, getToken } from '../api'
import { useUI } from '../stores/ui'

const props = defineProps({
  kind: { type: String, required: true },
  targetId: { type: String, required: true },
})
const ui = useUI()
const tags = ref([])
const images = ref({})
const loading = ref(true)

const mode = ref('generate') // generate | own
const description = ref('')
const ownCode = ref('')
const ownFormat = ref('barcode')

async function load() {
  tags.value = await api.get(`/qr-tags?kind=${props.kind}&targetId=${props.targetId}`)
  loading.value = false
  for (const t of tags.value) if (t.source === 'generated') loadImage(t)
}
async function loadImage(t) {
  const res = await fetch(apiUrl(`/qr-tags/${t.id}/image`), {
    headers: getToken() ? { Authorization: getToken() } : {},
  })
  images.value[t.id] = URL.createObjectURL(await res.blob())
}

async function addGenerated() {
  await api.post('/qr-tags', { kind: props.kind, targetId: props.targetId, description: description.value })
  description.value = ''
  ui.toast('QR code added')
  await load()
}

async function addOwn() {
  if (!ownCode.value.trim()) return
  try {
    await api.post('/qr-tags', {
      kind: props.kind, targetId: props.targetId, source: 'external',
      code: ownCode.value.trim(), codeFormat: ownFormat.value, description: description.value,
    })
    ownCode.value = ''
    description.value = ''
    ui.toast('Your code was linked')
    await load()
  } catch (e) {
    ui.error(e.message.includes('already') ? 'That code is already assigned to something.' : e.message)
  }
}

async function remove(t) {
  if (!confirm('Remove this code?')) return
  await api.del('/qr-tags/' + t.id)
  await load()
}
function copyLink(t) { navigator.clipboard?.writeText(t.scanUrl); ui.toast('Link copied') }
function printTag(t) {
  const w = window.open('', '_blank')
  w.document.write(`<html><head><title>QR ${t.token}</title></head>
    <body style="text-align:center;font-family:sans-serif;padding:40px">
    <img src="${images.value[t.id]}" style="width:260px;height:260px" />
    <h2>${t.description || props.kind}</h2><p style="color:#888">${t.token}</p>
    <script>window.onload=()=>window.print()<\/script></body></html>`)
  w.document.close()
}
onMounted(load)
</script>

<template>
  <div class="card">
    <h2 style="margin-bottom:6px">Codes <span class="badge">{{ tags.length }}</span></h2>
    <p class="muted" style="font-size:0.85rem;margin-top:0">
      Print a HomeHoard QR code, or link your <strong>own</strong> QR labels and product barcodes to this {{ kind }}.
    </p>

    <div v-if="loading" class="skeleton" style="height:120px"></div>
    <div v-else-if="tags.length" class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr))">
      <div v-for="t in tags" :key="t.id" class="card" style="text-align:center;padding:14px">
        <template v-if="t.source === 'generated'">
          <img v-if="images[t.id]" :src="images[t.id]" alt="QR"
               style="width:120px;height:120px;background:#fff;border-radius:8px;padding:6px" />
        </template>
        <div v-else style="height:120px;display:grid;place-items:center;background:var(--surface-2);border-radius:8px">
          <div>
            <div style="font-size:26px">🏷️</div>
            <div style="font-family:monospace;font-weight:600;word-break:break-all;font-size:0.8rem;padding:0 6px">{{ t.code }}</div>
          </div>
        </div>
        <div style="font-weight:600;margin-top:8px;font-size:0.88rem">{{ t.description || (t.source === 'external' ? t.codeFormat : '—') }}</div>
        <div class="muted" style="font-size:0.7rem;margin-bottom:8px">
          <span class="badge">{{ t.source === 'external' ? 'your code' : 'homehoard QR' }}</span>
        </div>
        <div class="row" style="gap:5px;justify-content:center">
          <button v-if="t.source === 'generated'" class="ghost sm" title="Copy link" @click="copyLink(t)">🔗</button>
          <button v-if="t.source === 'generated'" class="ghost sm" title="Print" @click="printTag(t)">🖨️</button>
          <button class="ghost sm" title="Remove" @click="remove(t)">🗑️</button>
        </div>
      </div>
    </div>
    <p v-else class="muted" style="font-size:0.85rem">No codes linked yet.</p>

    <div class="divider"></div>

    <div class="row" style="gap:6px;margin-bottom:12px">
      <button class="sm" :class="mode==='generate' ? '' : 'secondary'" @click="mode='generate'">Generate QR</button>
      <button class="sm" :class="mode==='own' ? '' : 'secondary'" @click="mode='own'">Use my own code</button>
    </div>

    <div v-if="mode==='generate'" class="row">
      <input v-model="description" placeholder="Label (e.g. lid, side)" @keyup.enter="addGenerated" />
      <button @click="addGenerated">＋ Add QR code</button>
    </div>

    <div v-else class="stack">
      <div class="row wrap" style="gap:10px">
        <input v-model="ownCode" style="flex:2;min-width:160px" placeholder="Scan or type the code / barcode number"
               @keyup.enter="addOwn" />
        <select v-model="ownFormat" style="width:auto">
          <option value="barcode">Barcode</option>
          <option value="ean13">EAN-13</option>
          <option value="upc">UPC</option>
          <option value="code128">Code 128</option>
          <option value="qr">QR</option>
          <option value="custom">Custom</option>
        </select>
        <button :disabled="!ownCode.trim()" @click="addOwn">Link code</button>
      </div>
      <p class="muted" style="font-size:0.8rem;margin:0">
        Tip: use the <strong>📷 Scan</strong> button in the top bar to capture a code with your
        camera — unknown codes can be assigned to any item, bin, or location on the spot.
      </p>
    </div>
  </div>
</template>
