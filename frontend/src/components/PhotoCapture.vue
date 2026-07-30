<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

const emit = defineEmits(['captured', 'close'])

const video = ref(null)
const canvas = ref(null)
const shot = ref('')      // data URL of the captured still, for preview
const error = ref('')     // '' | 'denied' | 'no-camera'
let stream = null
let shotFile = null

async function start() {
  error.value = ''
  if (!navigator.mediaDevices?.getUserMedia) { error.value = 'no-camera'; return }
  try {
    // Prefer the rear camera; fall back to any camera (e.g. a laptop webcam).
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
  } catch {
    try { stream = await navigator.mediaDevices.getUserMedia({ video: true }) }
    catch (e2) { error.value = e2?.name === 'NotAllowedError' ? 'denied' : 'no-camera'; return }
  }
  await nextTick()
  if (video.value) { video.value.srcObject = stream; await video.value.play().catch(() => {}) }
}

function stop() {
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null }
}

function capture() {
  const v = video.value
  if (!v || !v.videoWidth) return
  const c = canvas.value
  // Use the real frame dimensions so the still is upright and uncropped — drawing the
  // video onto a canvas bakes in what you see, so there's no EXIF-rotation surprise.
  c.width = v.videoWidth
  c.height = v.videoHeight
  c.getContext('2d').drawImage(v, 0, 0, c.width, c.height)
  shot.value = c.toDataURL('image/jpeg', 0.85)
  c.toBlob((blob) => {
    if (blob) shotFile = new File([blob], `photo-${Date.now()}.jpg`, { type: 'image/jpeg' })
  }, 'image/jpeg', 0.85)
}

function retake() { shot.value = ''; shotFile = null }
function use() { if (shotFile) { emit('captured', shotFile); close() } }
function close() { stop(); emit('close') }
function onFile(e) {
  const f = e.target.files?.[0]
  if (f) { emit('captured', f); close() }
}

onMounted(start)
onUnmounted(stop)
</script>

<template>
  <div class="modal-backdrop" @click.self="close">
    <div class="card modal" style="width:min(520px,100%)">
      <div class="modal-head">
        <h2>📷 Take a photo</h2>
        <button class="ghost icon-btn" aria-label="Close" @click="close">✕</button>
      </div>

      <!-- No camera / blocked → offer the OS picker (which can still use the camera). -->
      <div v-if="error">
        <p class="muted" style="margin-top:0">
          {{ error === 'denied' ? 'Camera access was blocked. Choose a photo instead:'
             : 'No camera available here. Choose a photo instead:' }}
        </p>
        <label class="field"><span class="sr-only">Choose a photo</span>
          <input type="file" accept="image/*" capture="environment"
                 aria-label="Choose a photo" @change="onFile" /></label>
      </div>

      <template v-else>
        <div class="cap-frame">
          <video v-show="!shot" ref="video" playsinline muted autoplay></video>
          <img v-if="shot" :src="shot" alt="Captured photo preview" />
        </div>
        <canvas ref="canvas" hidden></canvas>
        <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px">
          <button v-if="!shot" @click="capture">📸 Capture</button>
          <template v-else>
            <button class="secondary" @click="retake">Retake</button>
            <button @click="use">Use photo</button>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.cap-frame {
  background: #000; border-radius: 10px; overflow: hidden;
  aspect-ratio: 4 / 3; display: grid; place-items: center;
}
.cap-frame video, .cap-frame img { width: 100%; height: 100%; object-fit: contain; }
</style>
