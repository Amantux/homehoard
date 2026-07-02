<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const video = ref(null)
const status = ref('idle') // idle | starting | scanning | error
const error = ref('')
const engine = ref('')
const manual = ref('')

let stream = null
let raf = null
let detector = null
let zxingControls = null
let zxingReader = null

function tokenFromText(text) {
  const m = String(text).match(/\/t\/([^/?#\s]+)/)
  return m ? decodeURIComponent(m[1]) : String(text).trim()
}
function go(text) {
  const token = tokenFromText(text)
  if (token) {
    stop()
    router.push('/t/' + encodeURIComponent(token))
  }
}

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
    if (codes.length) return go(codes[0].rawValue)
  } catch (e) { /* frame not ready */ }
  raf = requestAnimationFrame(loopNative)
}

async function startZxing() {
  // JS decoder fallback for Safari / iOS which lack BarcodeDetector.
  const { BrowserMultiFormatReader } = await import('@zxing/browser')
  zxingReader = new BrowserMultiFormatReader()
  engine.value = 'zxing'
  zxingControls = await zxingReader.decodeFromConstraints(
    { video: { facingMode: 'environment' } },
    video.value,
    (result) => { if (result) go(result.getText()) }
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
    else if (!window.isSecureContext) error.value = 'Camera needs a secure (HTTPS) connection. Use manual entry, or access Shelfie over HTTPS / Home Assistant ingress.'
    else error.value = 'Could not start the camera: ' + (e.message || e.name)
  }
}

function stop() {
  if (raf) cancelAnimationFrame(raf)
  raf = null
  detector = null
  try { zxingControls?.stop() } catch (e) { /* noop */ }
  zxingControls = null
  if (stream) stream.getTracks().forEach((t) => t.stop())
  stream = null
}

onMounted(start)
onBeforeUnmount(stop)
</script>

<template>
  <div class="page-head"><h1>📷 Scan</h1></div>

  <div class="card" style="max-width:520px">
    <div style="border-radius:12px;overflow:hidden;background:#000;aspect-ratio:1;position:relative">
      <video ref="video" playsinline muted autoplay
             style="width:100%;height:100%;object-fit:cover"></video>
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

    <p class="muted" style="margin-top:10px">
      Point at any QR code or product barcode. Unknown codes can be linked to an item on the next screen.
      <span v-if="engine" class="badge" style="margin-left:6px">{{ engine === 'native' ? 'fast scanner' : 'compatibility scanner' }}</span>
    </p>

    <div class="divider"></div>
    <div class="row">
      <input v-model="manual" placeholder="…or paste a QR link / barcode number" @keyup.enter="go(manual)" />
      <button :disabled="!manual" @click="go(manual)">Go</button>
    </div>
  </div>
</template>
