<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

const ui = useUI()
const items = ref([])
const merging = ref('')

const { loading, error, reload: load } = useLoader(async () => {
  items.value = (await api.get('/items?pageSize=1000')).items
})

// Group by normalised name; only groups with 2+ members are duplicates.
const groups = computed(() => {
  const by = new Map()
  for (const i of items.value) {
    const key = i.name.trim().toLowerCase()
    if (!by.has(key)) by.set(key, [])
    by.get(key).push(i)
  }
  return [...by.values()]
    .filter((g) => g.length > 1)
    .map((g) => [...g].sort((a, b) => (a.createdAt || '').localeCompare(b.createdAt || '')))
    .sort((a, b) => b.length - a.length)
})

function where(i) {
  return i.bin?.name || i.location?.name || 'no location'
}

async function mergeInto(keep, source) {
  // Destructive: the confirm names both objects and says what merging means —
  // this is the ONE place a dialog belongs, not on every create.
  if (!confirm(
    `Merge the “${source.name}” in ${where(source)} (qty ${source.quantity}) into ` +
    `the one in ${where(keep)}? Quantities and placements combine, labels and ` +
    `photos carry over, and the ${where(source)} entry is removed.`)) return
  merging.value = source.id
  try {
    const merged = await api.post(`/items/${keep.id}/merge`, { sourceId: source.id })
    // The server's undo payload is the road back for a destructive action:
    // it recreates the source and moves the same holdings/photos/history rows
    // back, so Undo restores — it does not duplicate.
    ui.toast(`Merged — “${keep.name}” now has both placements`, 'success', {
      action: { label: 'Undo', run: () => undoMerge(merged.undo, keep.name) },
    })
    await load()
  } catch (e) {
    ui.error(e.message || 'Could not merge those.')
  } finally {
    merging.value = ''
  }
}

async function undoMerge(undo, name) {
  try {
    await api.post('/items/undo-merge', undo)
    ui.toast(`Merge undone — “${name}” is split back out`)
    await load()
  } catch (e) {
    // Errors persist until dismissed (house rule) — ui.error does that.
    ui.error(e.message || 'Could not undo that merge.')
  }
}
</script>

<template>
  <div class="page-head">
    <h1>Duplicates</h1>
    <span v-if="groups.length" class="badge warn">{{ groups.length }} name{{ groups.length === 1 ? '' : 's' }}</span>
    <div class="grow"></div>
  </div>

  <div v-if="loading" class="card"><div class="skeleton" style="height:200px"></div></div>
  <ErrorState v-else-if="error" :message="error" @retry="load" />
  <EmptyState v-else-if="!groups.length" icon="✨" title="No duplicate names"
              hint="When two items share a name, they show up here with a one-click merge — quantities and placements combine instead of splitting your counts." />

  <div v-else class="stack">
    <div v-for="g in groups" :key="g[0].id" class="card">
      <h2 class="m-0" style="margin-bottom:8px">{{ g[0].name }} <span class="muted txt-sm">× {{ g.length }}</span></h2>
      <div v-for="(i, idx) in g" :key="i.id" class="row" style="padding:6px 0;border-top:1px solid var(--border)">
        <router-link :to="'/items/' + i.id" class="fill">
          {{ where(i) }} · qty {{ i.quantity }}
          <span v-if="idx === 0" class="muted txt-sm">· oldest</span>
        </router-link>
        <!-- Merge INTO the oldest (first) — it keeps history and identity. -->
        <button v-if="idx > 0" class="secondary sm" :disabled="merging === i.id"
                @click="mergeInto(g[0], i)">
          {{ merging === i.id ? 'Merging…' : '⇤ Merge into oldest' }}
        </button>
      </div>
    </div>
  </div>
</template>
