<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'

const props = defineProps({ initialMode: { type: String, default: '' } })
const emit = defineEmits(['close'])
const router = useRouter()
const ui = useUI()

const video = ref(null)
const status = ref('starting') // starting | scanning | error
const error = ref('')
const engine = ref('')
const manual = ref('')
// open | checkout | checkin | onboard — what to do with each code as it comes in
const mode = ref(props.initialMode || 'open')

// onboard state
const bins = ref([])
const locations = ref([])
const targetKind = ref('')   // 'bin' | 'location'
const targetId = ref('')
const targetName = ref('')
const nextName = ref('')      // optional name for the next scanned/added item
const added = ref([])         // running session list: [{id, name}]

const banner = ref(null)      // { ok, text } transient feedback
let bannerTID = null

let stream = null
let raf = null
let detector = null
let zxingControls = null
let zxingReader = null
let navigating = false
let lastCode = ''
let lastAt = 0
let busy = false

const MODES = [
  { id: 'open', label: 'Look up' },
  { id: 'checkout', label: 'Check out' },
  { id: 'checkin', label: 'Check in' },
  { id: 'onboard', label: 'Add to…' },
]

function tokenFromText(text) {
  const m = String(text).match(/\/t\/([^/?#\s]+)/)
  return m ? decodeURIComponent(m[1]) : String(text).trim()
}

function flash(ok, text) {
  banner.value = { ok, text }
  try { if (ok && navigator.vibrate) navigator.vibrate(40) } catch (e) { /* noop */ }
  if (bannerTID) clearTimeout(bannerTID)
  bannerTID = setTimeout(() => { banner.value = null }, 3000)
}

function stopCamera() {
  if (raf) cancelAnimationFrame(raf)
  raf = null
  detector = null
  try { zxingControls?.stop() } catch (e) { /* noop */ }
  zxingControls = null
  if (stream) stream.getTracks().forEach((t) => t.stop())
  stream = null
}

function close() {
  stopCamera()
  emit('close')
}

// Every detected code funnels through here. Continuous: the camera keeps
// running; we debounce the same code so one barcode isn't processed 30×/s.
async function onCode(text) {
  const code = tokenFromText(text)
  if (!code || navigating) return
  const now = Date.now()
  if (code === lastCode && now - lastAt < 2500) return
  lastCode = code
  lastAt = now
  if (busy) return
  busy = true
  try {
    await handle(code)
  } catch (e) {
    flash(false, e.message || 'Something went wrong')
  } finally {
    busy = false
  }
}

async function handle(code) {
  // Look-up mode is a single jump to whatever the code points at.
  if (mode.value === 'open') {
    navigating = true
    close()
    router.push('/t/' + encodeURIComponent(code))
    return
  }

  const res = await api.get('/barcode/' + encodeURIComponent(code))

  if (mode.value === 'checkout' || mode.value === 'checkin') {
    if (res.status !== 'registered' || res.kind !== 'item') {
      flash(false, res.kind ? `That's a ${res.kind}, not an item` : "Not in inventory yet")
      return
    }
    const it = await api.post(`/items/${res.targetId}/${mode.value}`, {})
    flash(true, `${mode.value === 'checkout' ? '📤 Checked out' : '📥 Checked in'}: ${it.name || res.target.name}`)
    return
  }

  // onboard: scanning a bin/location sets the target; scanning items fills it.
  if (res.status === 'registered' && (res.kind === 'bin' || res.kind === 'location')) {
    setTarget(res.kind, res.targetId, res.target.name)
    flash(true, `📦 Adding into ${res.target.name}`)
    return
  }
  if (!targetId.value) {
    flash(false, 'Scan a bin/location first, or pick one above')
    return
  }
  if (res.status === 'registered' && res.kind === 'item') {
    await placeExisting(res.targetId)
    added.value.unshift({ id: res.targetId, name: res.target.name })
    flash(true, `➡️ Moved ${res.target.name} into ${targetName.value}`)
    return
  }
  // Unknown code → create a new item, place it, and remember the barcode.
  const name = nextName.value.trim() || `Item ${code.slice(-5)}`
  const created = await createInTarget(name)
  nextName.value = ''
  api.post('/qr-tags', {
    kind: 'item', targetId: created.id, source: 'external', code, codeFormat: 'barcode',
  }).catch(() => { /* barcode already linked elsewhere — item still created */ })
  added.value.unshift({ id: created.id, name: created.name })
  flash(true, `✓ Added ${created.name}`)
}

function setTarget(kind, id, name) {
  targetKind.value = kind
  targetId.value = id
  targetName.value = name
}
async function createInTarget(name) {
  const payload = { name }
  if (targetKind.value === 'bin') payload.binId = targetId.value
  else payload.locationId = targetId.value
  return api.post('/items', payload)
}
async function placeExisting(itemId) {
  if (targetKind.value === 'bin') return api.put(`/bins/${targetId.value}/items/${itemId}`)
  return api.patch(`/items/${itemId}`, { locationId: targetId.value, binId: null })
}
async function renameAdded(entry) {
  try { await api.patch('/items/' + entry.id, { name: entry.name }) } catch (e) { ui.error(e.message) }
}
// Add an item by name only (no barcode) — for things that aren't labelled.
async function addByName() {
  if (!nextName.value.trim() || !targetId.value) return
  const created = await createInTarget(nextName.value.trim())
  nextName.value = ''
  added.value.unshift({ id: created.id, name: created.name })
  flash(true, `✓ Added ${created.name}`)
}

const targetSel = computed({
  get: () => (targetId.value ? `${targetKind.value === 'bin' ? 'bin' : 'loc'}:${targetId.value}` : ''),
  set: (v) => {
    if (!v) return setTarget('', '', '')
    const [k, id] = v.split(':')
    const kind = k === 'bin' ? 'bin' : 'location'
    const found = (kind === 'bin' ? bins.value : locations.value).find((x) => x.id === id)
    setTarget(kind, id, found ? found.name : '')
  },
})

const NATIVE_FORMATS = [
  'qr_code', 'ean_13', 'ean_8', 'upc_a', 'upc_e',
  'code_128', 'code_39', 'code_93', 'codabar', 'itf', 'data_matrix',
]

async function startNative() {
  const supported = await window.BarcodeDetector.getSupportedFormats()
  const formats = NATIVE_FORMATS.filter((f) => supported.includes(f))
  if (!formats.length) throw new Error('no formats')
  detector = new window.BarcodeDetector({ formats })
  stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
  video.value.srcObject = stream
  await video.value.play()
  engine.value = 'native'
  loopNative()
}
async function loopNative() {
  if (!detector || !video.value) return
  try {
    const codes = await detector.detect(video.value)
    if (codes.length) onCode(codes[0].rawValue)
  } catch (e) { /* frame not ready */ }
  raf = requestAnimationFrame(loopNative)
}

async function startZxing() {
  const { BrowserMultiFormatReader } = await import('@zxing/browser')
  zxingReader = new BrowserMultiFormatReader()
  engine.value = 'zxing'
  zxingControls = await zxingReader.decodeFromConstraints(
    { video: { facingMode: 'environment' } },
    video.value,
    (result) => { if (result) onCode(result.getText()) },
  )
}

async function start() {
  status.value = 'starting'
  error.value = ''
  try {
    if ('BarcodeDetector' in window) {
      try { await startNative() } catch (e) { await startZxing() }
    } else {
      await startZxing()
    }
    status.value = 'scanning'
  } catch (e) {
    status.value = 'error'
    if (e.name === 'NotAllowedError') error.value = 'Camera permission was denied.'
    else if (!window.isSecureContext) error.value = 'Camera needs HTTPS. Use manual entry below, or open HomeHoard over HTTPS / Home Assistant.'
    else error.value = 'Could not start the camera: ' + (e.message || e.name)
  }
}

onMounted(async () => {
  start()
  try {
    const [bs, ls] = await Promise.all([api.get('/bins'), api.get('/locations')])
    bins.value = bs
    locations.value = ls
  } catch (e) { /* ignore */ }
})
onBeforeUnmount(stopCamera)
</script>

<template>
  <div class="modal-backdrop" @click.self="close">
    <div class="card modal" style="width:460px;max-width:96vw">
      <div class="modal-head">
        <h2 style="flex:1">📷 Scan</h2>
        <button class="ghost icon-btn" @click="close">✕</button>
      </div>

      <div class="row wrap" style="gap:6px;margin-bottom:10px">
        <button v-for="m in MODES" :key="m.id" class="sm" :class="mode === m.id ? '' : 'ghost'"
                @click="mode = m.id">{{ m.label }}</button>
      </div>

      <!-- Onboard target -->
      <div v-if="mode === 'onboard'" class="card" style="padding:10px;margin-bottom:10px;background:var(--surface-2)">
        <label class="field" style="margin:0"><span>Adding into</span>
          <select v-model="targetSel">
            <option value="">Scan or pick a bin / location…</option>
            <optgroup label="Bins">
              <option v-for="b in bins" :key="b.id" :value="'bin:'+b.id">🗃️ {{ b.name }}</option>
            </optgroup>
            <optgroup label="Locations">
              <option v-for="l in locations" :key="l.id" :value="'loc:'+l.id">📍 {{ l.name }}</option>
            </optgroup>
          </select>
        </label>
        <p v-if="!targetId" class="muted" style="font-size:0.8rem;margin:8px 0 0">
          Tip: scan a bin/location's QR to set it, then scan items to drop them in.
        </p>
      </div>

      <div style="border-radius:12px;overflow:hidden;background:#000;aspect-ratio:1;position:relative">
        <video ref="video" playsinline muted autoplay
               style="width:100%;height:100%;object-fit:cover"></video>
        <!-- transient result banner -->
        <div v-if="banner" class="scan-banner"
             :style="{ background: banner.ok ? 'rgba(22,130,70,.92)' : 'rgba(160,40,40,.92)' }">
          {{ banner.text }}
        </div>
        <div v-if="status !== 'scanning'"
             style="position:absolute;inset:0;display:grid;place-items:center;color:#fff;text-align:center;padding:20px">
          <div>
            <p v-if="status === 'starting'">Starting camera…</p>
            <template v-else>
              <p style="margin-bottom:12px">{{ error || 'Camera is off.' }}</p>
              <button @click="start">Start camera</button>
            </template>
          </div>
        </div>
      </div>

      <p class="muted" style="margin-top:10px;font-size:0.85rem">
        <template v-if="mode === 'onboard'">Keep scanning — each code drops an item into <strong>{{ targetName || '(pick a target)' }}</strong>.</template>
        <template v-else-if="mode === 'open'">Point at a code to open it.</template>
        <template v-else>Point at item codes to {{ mode === 'checkout' ? 'check them out' : 'check them in' }} — one after another.</template>
        <span v-if="engine" class="badge" style="margin-left:4px">{{ engine === 'native' ? 'fast scanner' : 'compatibility scanner' }}</span>
      </p>

      <!-- Onboard: name-first add + session list -->
      <template v-if="mode === 'onboard'">
        <div class="row" style="gap:8px;margin-top:6px">
          <input v-model="nextName" style="flex:1" placeholder="Name for the next item (optional)"
                 @keyup.enter="addByName" />
          <button class="secondary" :disabled="!nextName.trim() || !targetId" @click="addByName">＋ Add</button>
        </div>
        <div v-if="added.length" style="margin-top:12px">
          <div class="muted" style="font-size:0.82rem;margin-bottom:6px">Added this session ({{ added.length }}) — rename as needed:</div>
          <div style="max-height:180px;overflow:auto;display:flex;flex-direction:column;gap:6px">
            <div v-for="a in added" :key="a.id" class="row" style="gap:6px">
              <input v-model="a.name" style="flex:1" @change="renameAdded(a)" @keyup.enter="renameAdded(a)" />
              <button class="ghost sm" @click="router.push('/items/' + a.id)">Open</button>
            </div>
          </div>
        </div>
      </template>

      <div class="divider"></div>
      <div class="row">
        <input v-model="manual" placeholder="…or paste / type a code" @keyup.enter="onCode(manual); manual=''" />
        <button :disabled="!manual" @click="onCode(manual); manual=''">Go</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scan-banner {
  position: absolute; left: 0; right: 0; bottom: 0;
  padding: 10px 12px; color: #fff; font-weight: 600; text-align: center;
  font-size: 0.95rem;
}
</style>
