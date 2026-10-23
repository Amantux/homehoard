<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { api, apiUrl, getToken } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

// Printable sheet of HomeHoard QR labels. The user picks any generated tags
// (across items, bins, and locations), previews the grid, and prints. Cells
// are sized for common 63.5×38.1mm label sheets (3 per row) under @media
// print; on screen the same grid is shown as a preview.

// Layout presets: each defines print CSS column count, cell dimensions in mm,
// QR size in mm, and whether to show extra text (asset/short code).
const LAYOUTS = {
  'address-3up': {
    name: 'Address labels, 3-up',
    description: '63.5×38.1mm (standard address labels)',
    printCols: 3,
    cellWidth: 63.5,
    cellHeight: 38.1,
    qrSize: 30,
    showExtraText: false,
  },
  'small-4up': {
    name: 'Small labels, 4-up',
    description: '50.8×25.4mm (dense small-bin/jar size)',
    printCols: 4,
    cellWidth: 50.8,
    cellHeight: 25.4,
    qrSize: 20,
    showExtraText: false,
  },
  'large-2up': {
    name: 'Large labels, 2-up',
    description: '101.6×50.8mm (bigger size for bins/totes)',
    printCols: 2,
    cellWidth: 101.6,
    cellHeight: 50.8,
    qrSize: 40,
    showExtraText: true,
  },
}

const ui = useUI()
const tags = ref([])
const selected = reactive({}) // tag id -> true
const images = reactive({}) // tag id -> blob URL (loaded on demand)
const pendingImages = ref(0)

// Layout selection with localStorage persistence
const layoutKey = 'homehoard-label-layout'
const savedLayout = localStorage.getItem(layoutKey)
const currentLayout = ref(savedLayout || 'address-3up')

// Update localStorage when layout changes
function setLayout(layoutId) {
  currentLayout.value = layoutId
  localStorage.setItem(layoutKey, layoutId)
}

const { loading, error, reload: load } = useLoader(async () => {
  const all = await api.get('/qr-tags')
  // Only generated tags have a printable QR image; external codes are the
  // user's own pre-printed labels, so there is nothing to print for them.
  tags.value = all.filter((t) => t.source === 'generated')
})

const KIND_LABELS = { item: 'Items', bin: 'Bins', location: 'Locations' }
const groups = computed(() =>
  ['item', 'bin', 'location']
    .map((kind) => ({ kind, label: KIND_LABELS[kind], tags: tags.value.filter((t) => t.kind === kind) }))
    .filter((g) => g.tags.length),
)

const selectedTags = computed(() => tags.value.filter((t) => selected[t.id]))
const selectedCount = computed(() => selectedTags.value.length)

// Current layout object
const layout = computed(() => LAYOUTS[currentLayout.value])

function tagName(t) {
  const target = t.target?.name || ''
  if (t.description && target) return `${target} — ${t.description}`
  return target || t.description || t.kind
}

// Extra text: item asset/short code if present, empty for bins/locations
function extraText(t) {
  if (t.kind === 'item' && t.assetId) return t.assetId
  if (t.kind === 'item' && t.shortCode) return t.shortCode
  return ''
}

async function loadImage(t) {
  if (images[t.id]) return
  pendingImages.value++
  try {
    const res = await fetch(apiUrl(`/qr-tags/${t.id}/image`), {
      headers: getToken() ? { Authorization: getToken() } : {},
    })
    if (!res.ok) throw new Error('image failed')
    images[t.id] = URL.createObjectURL(await res.blob())
  } catch {
    ui.error(`Could not load the QR image for "${tagName(t)}".`)
  } finally {
    pendingImages.value--
  }
}

function toggle(t) {
  if (selected[t.id]) delete selected[t.id]
  else {
    selected[t.id] = true
    loadImage(t)
  }
}
function setGroup(g, on) {
  for (const t of g.tags) {
    if (on) {
      if (!selected[t.id]) {
        selected[t.id] = true
        loadImage(t)
      }
    } else delete selected[t.id]
  }
}
function groupAllSelected(g) {
  return g.tags.every((t) => selected[t.id])
}
function clearAll() {
  for (const id of Object.keys(selected)) delete selected[id]
}

const preparing = computed(() => pendingImages.value > 0)
function printSheet() {
  if (!selectedCount.value || preparing.value) return
  window.print()
}
</script>

<template>
  <div class="page-head no-print">
    <h1>Print QR labels</h1>
    <span class="badge">{{ selectedCount }} selected</span>
    <div class="grow"></div>
    <button :disabled="!selectedCount || preparing" @click="printSheet">
      {{ preparing ? 'Preparing images…' : '🖨️ Print sheet' }}
    </button>
  </div>

  <div v-if="loading" class="card-grid no-print">
    <div v-for="i in 4" :key="i" class="skeleton" style="height:90px"></div>
  </div>
  <ErrorState v-else-if="error" class="no-print" :message="error" @retry="load" />
  <template v-else-if="tags.length">
    <div class="card no-print">
      <p class="muted" style="margin-top:0;font-size:0.9rem">
        Pick the HomeHoard QR codes to put on the sheet.
      </p>

      <!-- Layout selector -->
      <div class="stack" style="margin-bottom:12px">
        <label class="muted" style="font-size:0.85rem">Label sheet layout</label>
        <div class="stack" style="gap:6px">
          <label v-for="(layoutDef, id) in LAYOUTS" :key="id" class="row" style="gap:8px;cursor:pointer">
            <input
              type="radio"
              :name="'layout'"
              :value="id"
              v-model="currentLayout"
            />
            <div>
              <strong>{{ layoutDef.name }}</strong>
              <span class="muted" style="font-size:0.85rem"> — {{ layoutDef.description }}</span>
            </div>
          </label>
        </div>
      </div>

      <!-- Extra text toggle (only show for layouts that support it) -->
      <div v-if="layout.showExtraText" class="stack" style="margin-bottom:12px">
        <label class="row" style="gap:8px;cursor:pointer">
          <input type="checkbox" :checked="true" disabled />
          <span class="muted" style="font-size:0.85rem">
            Extra text (asset/short code) is enabled for this layout
          </span>
        </label>
      </div>

      <p class="muted" style="font-size:0.9rem">
        The grid prints at {{ layout.cellWidth }}&times;{{ layout.cellHeight }}&nbsp;mm per label
        ({{ layout.printCols }} across) — {{ layout.description }}.
      </p>
      <div v-for="g in groups" :key="g.kind" class="stack" style="margin-bottom:12px">
        <div class="row" style="gap:8px">
          <h2 style="margin:0;font-size:1rem">{{ g.label }} <span class="badge">{{ g.tags.length }}</span></h2>
          <button class="ghost sm" @click="setGroup(g, !groupAllSelected(g))">
            {{ groupAllSelected(g) ? 'Deselect all' : 'Select all' }}
          </button>
        </div>
        <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px">
          <label v-for="t in g.tags" :key="t.id" class="row" style="gap:8px;cursor:pointer;align-items:center">
            <input type="checkbox" :checked="!!selected[t.id]" @change="toggle(t)" />
            <span style="font-size:0.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ tagName(t) }}</span>
          </label>
        </div>
      </div>
      <div class="row" style="gap:8px">
        <button class="secondary sm" :disabled="!selectedCount" @click="clearAll">Clear selection</button>
      </div>
    </div>

    <h2 v-if="selectedCount" class="no-print" style="font-size:1rem">Sheet preview</h2>
    <div v-if="selectedCount" class="label-sheet" :style="{ '--print-cols': layout.printCols }">
      <div v-for="t in selectedTags" :key="t.id" class="label-cell" :style="{
        width: layout.cellWidth + 'mm',
        height: layout.cellHeight + 'mm',
      }">
        <img v-if="images[t.id]" :src="images[t.id]" alt="QR code" class="label-qr" :style="{ width: layout.qrSize + 'mm', height: layout.qrSize + 'mm' }" />
        <div v-else class="skeleton label-qr" :style="{ width: layout.qrSize + 'mm', height: layout.qrSize + 'mm' }"></div>
        <div class="label-text">
          <div class="label-name">{{ tagName(t) }}</div>
          <div v-if="extraText(t)" class="label-asset">{{ extraText(t) }}</div>
          <div class="label-token">{{ t.token }}</div>
        </div>
      </div>
    </div>
    <p v-else class="muted no-print">Nothing selected yet — tick the codes above to build the sheet.</p>
  </template>
  <div v-else class="card no-print">
    <EmptyState icon="🖨️" title="No printable QR codes"
      hint="Generate HomeHoard QR codes on an item, bin, or location first — external codes you linked are already printed." />
  </div>
</template>

<style scoped>
/* On-screen preview mirrors the print layout at the same physical size so
   what you see is what comes out of the printer. */
.label-sheet {
  display: grid;
  grid-template-columns: repeat(v-bind(--print-cols), v-bind(cellWidth + 'mm'));
  gap: 2mm;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px;
  overflow-x: auto;
}
.label-cell {
  width: v-bind(cellWidth + 'mm');
  height: v-bind(cellHeight + 'mm');
  display: flex;
  align-items: center;
  gap: 2mm;
  padding: 2mm;
  box-sizing: border-box;
  border: 1px dashed var(--border);
  border-radius: 2px;
  break-inside: avoid;
  page-break-inside: avoid;
  overflow: hidden;
}
.label-qr {
  width: v-bind(qrSize + 'mm');
  height: v-bind(qrSize + 'mm');
  flex: none;
  /* The QR PNG carries its own white quiet zone; no background needed. */
}
.label-text {
  min-width: 0;
  overflow: hidden;
}
.label-name {
  font-weight: 600;
  font-size: 9pt;
  line-height: 1.2;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.label-asset {
  font-size: 7pt;
  color: var(--muted);
  word-break: break-all;
}
.label-token {
  font-family: monospace;
  font-size: 6.5pt;
  color: var(--muted);
  word-break: break-all;
}

@media print {
  .label-sheet {
    background: none;
    border: none;
    border-radius: 0;
    padding: 0;
    gap: 0 2.5mm;
    overflow: visible;
  }
  /* Keep the cut guides off the printout; the cell size is the label size. */
  .label-cell {
    border: none;
  }
  .label-token {
    color: inherit;
  }
}
</style>
