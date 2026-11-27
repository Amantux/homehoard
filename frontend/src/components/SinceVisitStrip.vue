<script setup>
import { computed } from 'vue'

const props = defineProps({
  // The "what changed since my last visit" delta. Null/undefined -> render
  // nothing (first visit, or a failed delta fetch): no strip, no noise.
  digest: { type: Object, default: null },
})

// Local calendar date of the since watermark, e.g. "Nov 20".
const sinceLabel = computed(() => {
  const since = props.digest?.since
  if (!since) return ''
  const d = new Date(since)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
})

// One entry per non-zero category; zero-count categories are omitted entirely.
const segments = computed(() => {
  const d = props.digest
  if (!d) return []
  const out = []
  if (d.newItems) {
    out.push({ to: '/items', label: `${d.newItems} new item${d.newItems === 1 ? '' : 's'}` })
  }
  if (d.checkoutsReturned) {
    out.push({ to: '/checkouts', label: `${d.checkoutsReturned} returned` })
  }
  if (d.warrantiesExpiring7) {
    out.push({
      to: '/report',
      label: `${d.warrantiesExpiring7} warrant${d.warrantiesExpiring7 === 1 ? 'y' : 'ies'} expiring within 7 days`,
    })
  }
  if (d.maintenanceCompleted) {
    out.push({ to: '/maintenance', label: `${d.maintenanceCompleted} maintenance completed` })
  }
  return out
})

const hasChanges = computed(() => segments.value.length > 0)
</script>

<template>
  <div v-if="digest" class="card" style="margin-bottom:16px">
    <div v-if="hasChanges" class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
      <span>Since {{ sinceLabel }}: </span>
      <span v-for="(s, i) in segments" :key="s.to" class="row" style="gap:8px;align-items:center">
        <span v-if="i > 0">,</span>
        <router-link :to="s.to">{{ s.label }}</router-link>
      </span>
    </div>
    <div v-else class="row">No changes since {{ sinceLabel }}</div>
  </div>
</template>
