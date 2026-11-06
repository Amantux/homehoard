<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { api, apiUrl, getToken } from '../api'
import { LABEL_LAYOUT } from '../storageKeys'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

// Printable sheet of HomeHoard QR labels. The user picks any generated tags
// (across items, bins, and locations), previews the grid, and prints. Cells
// are sized in mm from the chosen layout (default: 63.5×38.1mm, 3 per row);
// on screen the same grid is shown as a preview. Printing uses a zero-margin
// page for as long as this view is open (PRINT_PAGE_CSS below), so the sizes
// hold when the browser prints at 100% scale.

// Layout presets: how many labels sit across a row, the label and QR size in
// mm, the gap between columns, and whether items also print their asset id
// under the name. Every row of columns must fit the narrowest paper we print
// on: cols × cellWidth + (cols - 1) × gutter <= 210 (A4); a wider row is shrunk
// by the browser and nothing comes out at the size it claims.
const LAYOUTS = {
  'address-3up': {
    name: 'Address labels, 3-up',
    description: 'standard address labels',
    printCols: 3,
    cellWidth: 63.5,
    cellHeight: 38.1,
    qrSize: 30,
    gutter: 2.5,
    showExtraText: false,
  },
  'small-4up': {
    name: 'Small labels, 4-up',
    description: 'dense small-bin/jar size',
    printCols: 4,
    cellWidth: 50.8,
    cellHeight: 25.4,
    qrSize: 20,
    // 4 × 50.8 + 3 × 2.5 is 210.7 mm: wider than A4, so it would be shrunk.
    gutter: 2,
    showExtraText: false,
  },
  'large-2up': {
    name: 'Large labels, 2-up',
    description: 'bigger size for bins/totes; items also print their asset id',
    printCols: 2,
    cellWidth: 101.6,
    cellHeight: 50.8,
    qrSize: 40,
    gutter: 2.5,
    showExtraText: true,
  },
}
const DEFAULT_LAYOUT = 'address-3up'

// The sheet prints on a page with no margin, so it gets the paper's whole width:
// with the browser's default margins plus the app's own padding the grid is wider
// than the page, the browser shrinks it to fit, and no label comes out at its
// stated size (4-up cannot fit A4 at all). `main.content` is the app's padded
// column (App.vue).
//
// Added to <head> while this view is open, not written into the stylesheet: that
// stays loaded after the user leaves the route, and an @page margin of 0 would
// then strip the margins from every page printed later in the session (the
// inventory report included). It is a plain @page rather than a named one
// (`page: labels`) because Firefox 146 applies a named page's margin but then
// shrinks the grid anyway, so 3-up and 2-up printed at 88%.
const PRINT_PAGE_CSS = `
@page { margin: 0; }
@media print { main.content { padding: 0; } }
`
let printPageStyle = null
onMounted(() => {
  printPageStyle = document.createElement('style')
  printPageStyle.setAttribute('data-label-print-page', '')
  printPageStyle.textContent = PRINT_PAGE_CSS
  document.head.appendChild(printPageStyle)
})
onBeforeUnmount(() => {
  printPageStyle?.remove()
  printPageStyle = null
})

const ui = useUI()
const tags = ref([])
const selected = reactive({}) // tag id -> true
const images = reactive({}) // tag id -> blob URL (loaded on demand)
const failed = reactive({}) // tag id -> true when its QR image could not be loaded
const pendingImages = ref(0)

// The chosen layout is remembered per browser. A saved value is only trusted
// if it still names a layout (a stale or hand-edited key must not break the
// page), and storage itself can throw (private mode, blocked site data), so
// both the read and the write are guarded. setLayout is the only way the
// choice changes.
function savedLayoutId() {
  try {
    const saved = localStorage.getItem(LABEL_LAYOUT)
    if (saved && Object.hasOwn(LAYOUTS, saved)) return saved
  } catch {
    // storage unavailable: use the default
  }
  return DEFAULT_LAYOUT
}
const currentLayout = ref(savedLayoutId())

function setLayout(layoutId) {
  currentLayout.value = layoutId
  try {
    localStorage.setItem(LABEL_LAYOUT, layoutId)
  } catch {
    // storage unavailable: the choice still applies until the page is closed
  }
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

// The <style> block reads the layout through these custom properties (set on
// .label-sheet below), so the preview and the printout share one source.
const sheetVars = computed(() => ({
  '--print-cols': String(layout.value.printCols),
  '--cell-w': `${layout.value.cellWidth}mm`,
  '--cell-h': `${layout.value.cellHeight}mm`,
  '--qr-size': `${layout.value.qrSize}mm`,
  '--gutter': `${layout.value.gutter}mm`,
}))

function tagName(t) {
  const target = t.target?.name || ''
  if (t.description && target) return `${target} — ${t.description}`
  return target || t.description || t.kind
}

// What the API (serializers._fmt_asset) sends for an item that has no asset id.
const NO_ASSET_ID = '000-000'

// Extra line under the name: an item's asset id, on layouts that have room for
// it. Bins and locations have no asset id, and an item without one prints
// nothing rather than "000-000".
function extraText(t) {
  if (!layout.value.showExtraText) return ''
  const id = t.target?.assetId
  return id && id !== NO_ASSET_ID ? id : ''
}

async function loadImage(t) {
  if (images[t.id]) return
  delete failed[t.id]
  pendingImages.value++
  try {
    const res = await fetch(apiUrl(`/qr-tags/${t.id}/image`), {
      headers: getToken() ? { Authorization: getToken() } : {},
    })
    if (!res.ok) throw new Error('image failed')
    images[t.id] = URL.createObjectURL(await res.blob())
  } catch {
    failed[t.id] = true
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
// Selected codes whose image failed. Printing is held while there are any: a
// label without its code looks finished and only fails when someone scans it.
const failedTags = computed(() => selectedTags.value.filter((t) => failed[t.id]))
const canPrint = computed(
  () => selectedCount.value > 0 && !preparing.value && !failedTags.value.length,
)
// A new attempt clears the failure (loadImage), so the notice goes away while it
// runs and the Print button reads "Preparing images…"; if it fails again the
// notice comes straight back.
function retryFailed() {
  for (const t of failedTags.value) loadImage(t)
}
function printSheet() {
  if (!canPrint.value) return
  window.print()
}
</script>

<template>
  <div class="page-head no-print">
    <h1>Print QR labels</h1>
    <span class="badge">{{ selectedCount }} selected</span>
    <div class="grow"></div>
    <button :disabled="!canPrint" @click="printSheet">
      {{ preparing ? 'Preparing images…' : '🖨️ Print sheet' }}
    </button>
  </div>

  <div v-if="loading" class="card-grid no-print">
    <div v-for="i in 4" :key="i" class="skeleton" style="height:90px"></div>
  </div>
  <ErrorState v-else-if="error" class="no-print" :message="error" @retry="load" />
  <template v-else-if="tags.length">
    <div v-if="failedTags.length" class="card load-failed no-print" role="alert">
      <span class="fill">
        <strong>{{ failedTags.length === 1 ? '1 QR image' : `${failedTags.length} QR images` }} could not be loaded.</strong>
        Printing is paused so no label comes out without its code. Try again, or deselect the
        codes marked in the preview.
      </span>
      <button class="secondary sm" @click="retryFailed">Try again</button>
    </div>

    <div class="card no-print">
      <p class="muted" style="margin-top:0;font-size:0.9rem">
        Pick the HomeHoard QR codes to put on the sheet.
      </p>

      <!-- Layout selector -->
      <fieldset class="layout-picker">
        <legend>Label sheet layout</legend>
        <div class="stack" style="gap:6px">
          <label v-for="(layoutDef, id) in LAYOUTS" :key="id" class="row layout-option" style="gap:8px;cursor:pointer">
            <input
              type="radio"
              name="layout"
              :value="id"
              :checked="currentLayout === id"
              @change="setLayout(id)"
            />
            <div>
              <strong>{{ layoutDef.name }}</strong>
              <span class="muted" style="font-size:0.85rem">
                — {{ layoutDef.cellWidth }}&times;{{ layoutDef.cellHeight }}&nbsp;mm, {{ layoutDef.description }}
              </span>
            </div>
          </label>
        </div>
      </fieldset>

      <p class="layout-summary muted" style="font-size:0.9rem">
        The grid prints at {{ layout.cellWidth }}&times;{{ layout.cellHeight }}&nbsp;mm per label,
        {{ layout.printCols }} across, starting at the top-left corner of the page. Print at 100%
        scale (not &ldquo;Fit to page&rdquo;) so the labels come out at that size.
        <template v-if="layout.showExtraText">Items that have an asset id print it under the name.</template>
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
    <div v-if="selectedCount" class="label-sheet" :style="sheetVars">
      <div v-for="t in selectedTags" :key="t.id" class="label-cell">
        <img v-if="images[t.id]" :src="images[t.id]" alt="QR code" class="label-qr" />
        <div v-else-if="failed[t.id]" class="label-qr label-qr-failed">QR image failed to load</div>
        <div v-else class="skeleton label-qr"></div>
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
/* A group of radios needs a name for assistive tech, and a <fieldset> brings its
   own border and padding that the picker does not want. */
.layout-picker {
  border: 0;
  padding: 0;
  margin: 0 0 12px;
  min-width: 0;
}
.layout-picker legend {
  padding: 0;
  margin-bottom: 8px;
  font-size: 0.85rem;
  color: var(--muted);
}
/* style.css makes every input full width and exempts only checkboxes, so a bare
   radio stretched across its row and pushed its text to the far side. */
.layout-option input {
  width: auto;
  flex: none;
  accent-color: var(--accent);
}

.load-failed {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border-left: 4px solid var(--danger);
  background: var(--danger-soft);
}
.load-failed .fill {
  flex: 1;
  min-width: 220px;
}

/* On-screen preview of the print layout: the same cell size, column count and
   column gap. It shows how the labels sit, not what a printer does: on screen
   mm is just a CSS length, and only printing at 100% scale reproduces the real
   size.
   Sizes come from --print-cols / --cell-w / --cell-h / --qr-size / --gutter, set
   by :style on .label-sheet. Not v-bind(): that only reads <script setup>
   bindings, and these live on the layout object, so it compiled to NaN and
   "undefinedmm" and the grid silently printed as one column. */
.label-sheet {
  display: grid;
  grid-template-columns: repeat(var(--print-cols), var(--cell-w));
  column-gap: var(--gutter);
  row-gap: 2mm;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px;
  overflow-x: auto;
}
.label-cell {
  width: var(--cell-w);
  height: var(--cell-h);
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
  width: var(--qr-size);
  height: var(--qr-size);
  flex: none;
  /* The QR PNG carries its own white quiet zone; no background needed. */
}
/* Shown instead of the QR when its image would not load. Print is held while
   any is selected, and if one is printed anyway (Ctrl+P skips the button) it
   says so on the label instead of leaving a blank. */
.label-qr-failed {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1mm;
  box-sizing: border-box;
  border: 1px dashed var(--danger);
  color: var(--danger);
  font-size: 7pt;
  line-height: 1.2;
  text-align: center;
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

/* Print changes the look, never the geometry: no display, track, size or flex
   declaration belongs in here (the stylesheet contract tests enforce it). The
   page itself (no margin, no padding) is PRINT_PAGE_CSS in the script. */
@media print {
  .label-sheet {
    background: none;
    border: none;
    border-radius: 0;
    padding: 0;
    row-gap: 0;
    overflow: visible;
  }
  /* Keep the cut guides off the printout; the cell size is the label size.
     Ink is black on white whatever the app theme: a dark theme's pale text is
     unreadable on paper, and "background graphics" would otherwise print the
     dark page behind black text. */
  .label-cell {
    border: none;
    background: #fff;
  }
  .label-name,
  .label-asset,
  .label-token {
    color: #000;
  }
}
</style>
