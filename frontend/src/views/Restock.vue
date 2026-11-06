<script setup>
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

// One tap writes stock with no confirmation, so the row under the pointer must be
// the row the user aimed at. A list that moved on every tap put the NEXT item under
// the second click of a double-click, and under the pointer of someone working down
// the list. So while it is being worked through, rows keep their slots: a bought row
// stays where it was, offering Undo, and nothing re-sorts.
const HOLD_MS = 60000 // this long after the last tap, a refresh may rearrange the list
// Clicks on one row this close together are one gesture (double-click, double-tap,
// key repeat), and a click this soon after rows did move was aimed at what was there.
const SETTLE_MS = 600

const router = useRouter()
const ui = useUI()
const heading = ref(null)
const rows = ref([])
const busy = ref({})        // item id -> the label its button shows while a write is pending
const bought = ref({})      // item id -> { res, before }: POST response + row as it was, while held
const multiPlaced = ref({}) // item id -> true once the server refused a tap (several placements)
const lastClick = {}        // item id -> when its button was last clicked
let lastTap = 0             // when a tap or Undo last started
let rowsMovedAt = 0         // when a row last changed slot
let writesDone = 0          // purchases and Undos this page has seen land
const { loading, error, reload: load, refresh } = useLoader(async () => {
  const before = writesDone
  const { items } = await api.get('/restock')
  // A list fetched before a write landed shows the old count, which would look like
  // someone else's change. Each write asks for a newer list, so skip this one.
  if (before === writesDone) await placeRows(items)
})

const lowCount = computed(() => rows.value.filter((r) => !bought.value[r.id]).length)
const buttonLabel = (r) => busy.value[r.id] || (bought.value[r.id] ? 'Undo' : `Bought ${r.suggestedQuantity}`)

// The server's list, fitted to the slots on screen: numbers update, newly low items
// join at the end, and a row only leaves if something else took it off the list. A
// held row stays until its count moves in a way this page didn't do.
function fitToSlots(fresh) {
  const latest = new Map(fresh.map((r) => [r.id, r]))
  const shown = new Set(rows.value.map((r) => r.id))
  const kept = rows.value.flatMap((r) => {
    const now = latest.get(r.id)
    const hold = bought.value[r.id]
    if (busy.value[r.id] || (hold && (!now || now.onHand === hold.res.onHand))) return [r]
    if (hold) delete bought.value[r.id]
    return now ? [now] : []
  })
  return [...kept, ...fresh.filter((r) => !shown.has(r.id))]
}

async function placeRows(fresh) {
  let next = fresh
  if (Date.now() - lastTap < HOLD_MS) next = fitToSlots(fresh)
  else bought.value = {}
  if (rows.value.some((r, i) => next[i]?.id !== r.id)) rowsMovedAt = Date.now()

  // A row that leaves takes keyboard focus with it, and moving one can drop it too:
  // hand focus back, to whatever now sits in that slot if the row is gone.
  const focused = document.activeElement
  const row = focused?.closest('.restock-table tbody tr')
  const slot = row ? [...row.parentElement.children].indexOf(row) : -1
  rows.value = next
  if (slot < 0) return
  await nextTick()
  const actions = document.querySelectorAll('.restock-table tbody td:last-child > *')
  const target = focused.isConnected ? focused : actions[slot] ?? actions[actions.length - 1] ?? heading.value
  target?.focus()
}

function tapRow(r) {
  const now = Date.now()
  const sameGesture = now - (lastClick[r.id] ?? 0) < SETTLE_MS
  lastClick[r.id] = now
  if (sameGesture || now - rowsMovedAt < SETTLE_MS || busy.value[r.id]) return
  lastTap = now
  if (bought.value[r.id]) undoBought(r)
  else markBought(r)
}

async function markBought(r) {
  busy.value[r.id] = 'Adding…'
  try {
    // The number on the button, not "whatever you suggest by now": the tap says
    // "I bought this many", and another client may have moved the suggestion.
    const res = await api.post(`/restock/${r.id}/restocked`, { quantity: r.suggestedQuantity })
    writesDone++
    refresh()
    // The response IS the row's new state, and no refresh can move it. So the
    // confirmation doesn't depend on that refresh ever coming back.
    bought.value[r.id] = { res, before: r }
    rows.value = rows.value.map((x) => (x.id === r.id ? res : x))
    // Buying the suggestion clears an item, so this means the number on the button
    // had gone out of date: someone used some since the list loaded.
    const stillLow = res.isLow ? ', still at or below its restock level' : ''
    ui.toast(`Bought ${res.bought} — “${res.name}” now has ${res.onHand} on hand${stillLow}`)
  } catch (e) {
    if (e.status === 409) {
      multiPlaced.value[r.id] = true
      ui.toast(`“${r.name}” is kept in more than one place. Edit its placements to say where the new stock went.`, 'info')
      await nextTick()
      document.getElementById(`placements-${r.id}`)?.focus() // the button it replaced had focus
    } else {
      ui.error(e.status === 404 ? `“${r.name}” is no longer available.` : e.message || `Could not record that for “${r.name}”.`)
      refresh() // a 404 or 422 means this row is out of date
    }
  } finally {
    delete busy.value[r.id]
  }
}

async function undoBought(r) {
  const { res, before } = bought.value[r.id]
  busy.value[r.id] = 'Undoing…'
  try {
    // PUT writes an absolute count, so put it back only if nothing has moved since
    // the tap: otherwise Undo would wipe out someone else's change. And PUT quietly
    // ignores quantity once an item has several placements, so the count it reports
    // decides, not the 200.
    const now = await api.get(`/items/${r.id}`)
    const after = now.quantity === res.onHand
      ? await api.put(`/items/${r.id}`, { quantity: res.previousOnHand })
      : now
    writesDone++
    if (after.quantity === res.previousOnHand) {
      rows.value = rows.value.map((x) => (x.id === r.id ? { ...before, onHand: res.previousOnHand } : x))
      ui.toast(`Undone — “${res.name}” is back to ${res.previousOnHand}`)
    } else {
      ui.error(`Couldn’t undo — “${res.name}” changed since then (now ${after.quantity}). Adjust it on its item page.`)
    }
    delete bought.value[r.id]
  } catch (e) {
    // Deleted, or hidden by a vault that locked meanwhile: the purchase may well
    // stand, so don't claim it is gone. A failure keeps the row, so Undo can be retried.
    if (e.status === 404) {
      delete bought.value[r.id]
      ui.toast(`“${res.name}” is no longer available here, so this can’t be undone.`, 'info')
    } else {
      ui.error(e.message || `Could not undo that for “${res.name}”.`)
    }
  } finally {
    delete busy.value[r.id]
  }
  refresh()
}
</script>

<template>
  <div class="page-head">
    <h1 ref="heading" tabindex="-1">Restock</h1>
    <span v-if="lowCount" class="badge warn">{{ lowCount }} low</span>
    <div class="grow"></div>
  </div>

  <div v-if="loading" class="card"><div class="skeleton" style="height:200px"></div></div>
  <ErrorState v-else-if="error" :message="error" @retry="load" />
  <EmptyState v-else-if="!rows.length" icon="🛒" title="Nothing is running low"
              hint="Give a consumable a Min quantity on its item page — when it drops to that level it shows up here with how much to buy." />

  <div v-else class="card card-flush restock-table">
    <table>
      <thead><tr><th>Item</th><th>On hand</th><th class="roomy-only">Restock at</th><th class="roomy-only">Buy</th><th><span class="visually-hidden">Record purchase</span></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id" class="clickable" :class="{ done: bought[r.id] }"
            @click="router.push('/items/' + r.id)">
          <td><router-link :to="'/items/' + r.id" @click.stop><strong>{{ r.name }}</strong></router-link></td>
          <td>{{ r.onHand }}</td>
          <td class="roomy-only">{{ r.threshold }}</td>
          <td class="roomy-only">
            <span v-if="bought[r.id]" class="badge ok">Added {{ bought[r.id].res.bought }}</span>
            <span v-else class="badge warn">＋{{ r.suggestedQuantity }}</span>
          </td>
          <!-- @click.stop like every action inside a clickable row: without it,
               recording a purchase would ALSO navigate to the item. -->
          <td @click.stop style="text-align:right">
            <router-link v-if="multiPlaced[r.id]" :id="'placements-' + r.id" :to="'/items/' + r.id">Edit placements</router-link>
            <!-- aria-disabled, not disabled: a disabled button drops keyboard focus,
                 and one element for every state keeps it through Bought, Adding, Undo. -->
            <button v-else class="secondary sm" :aria-disabled="!!busy[r.id]"
                    :aria-label="`${buttonLabel(r)}: ${r.name}`" @click="tapRow(r)">
              {{ buttonLabel(r) }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
/* The one-tap button must stay on screen, not behind a sideways scroll: when there
   is no room the table drops to name, count and button (which says how many to
   buy). A container query because the sidebar, not just the screen, sets the width.
   The bottom margin clears the chat button (fixed, 24px up and 56px tall), which
   would otherwise sit on the last row's button at full scroll. */
.restock-table { container-type: inline-size; margin-bottom: 80px; }
.restock-table .badge { white-space: nowrap; }
.restock-table tr.done td { color: var(--muted); }
/* No double-tap zoom on the button: two quick taps must stay two taps on it. */
.restock-table button { touch-action: manipulation; min-width: 5.5em; justify-content: center; }
.restock-table button[aria-disabled="true"] { opacity: 0.5; cursor: not-allowed; }
@container (max-width: 560px) {
  .roomy-only { display: none; }
}
</style>
