<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { money, loadCurrency } from '../format'
import ItemCard from '../components/ItemCard.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

const router = useRouter()
const stats = ref(null)
const recent = ref([])
const locations = ref([])
// useLoader gives this view the standard skeleton -> error+retry -> content flow.
// The dashboard is the landing page, so a silent failure here reads as "the app
// is broken" rather than "one request failed".
const attention = ref(null)
const { loading, error, reload: load } = useLoader(async () => {
  await loadCurrency()
  const [s, r, l, ha] = await Promise.all([
    api.get('/groups/statistics'),
    api.get('/items?orderBy=createdAt&pageSize=6'),
    api.get('/locations'),
    // The HA summary already computes the "needs attention" set (overdue
    // checkouts, warranties expiring, overdue maintenance) for the HA sensors —
    // one endpoint, one policy, so the dashboard can never disagree with HA.
    api.get('/ha/summary'),
  ])
  stats.value = s
  recent.value = r.items
  locations.value = l
  const overdueLends = (ha.checkedOutItems || []).filter((i) => i.overdue)
  attention.value = {
    overdueLends,
    warranty30: ha.warrantiesExpiring?.days30 || 0,
    maintOverdue: ha.maintenance?.overdue || 0,
    restock: ha.restock?.count || 0,
    any: overdueLends.length || (ha.warrantiesExpiring?.days30 || 0)
      || (ha.maintenance?.overdue || 0) || (ha.restock?.count || 0),
  }
})

const tiles = () => [
  { icon: '📦', label: 'Items', value: stats.value.totalItems, to: '/items' },
  { icon: '📍', label: 'Locations', value: stats.value.totalLocations, to: '/locations' },
  { icon: '🏷️', label: 'Labels', value: stats.value.totalLabels, to: '/labels' },
  { icon: '🛡️', label: 'Under warranty', value: stats.value.totalWithWarranty },
  { icon: '💰', label: 'Total value', value: money(stats.value.totalItemPrice) },
]
</script>

<template>
  <div class="page-head">
    <h1>Dashboard</h1>
  </div>

  <div v-if="loading" class="stat-grid">
    <div v-for="i in 5" :key="i" class="skeleton" style="height:110px"></div>
  </div>

  <ErrorState v-else-if="error" :message="error" @retry="load" />

  <template v-else>
    <!-- The briefing: only rendered when something needs attention, so a calm
         household gets a calm dashboard. Each line goes to where you act on it. -->
    <div v-if="attention?.any" class="card" style="margin-bottom:16px;border-left:3px solid var(--danger)">
      <h2 style="margin:0 0 8px">Needs attention</h2>
      <div class="stack" style="gap:6px">
        <router-link v-if="attention.overdueLends.length" to="/checkouts" class="row" style="gap:8px;align-items:center">
          <span class="badge danger">{{ attention.overdueLends.length }} overdue</span>
          <span>{{ attention.overdueLends.map((i) => i.to ? `${i.name} (${i.to})` : i.name).slice(0, 3).join(', ') }}{{ attention.overdueLends.length > 3 ? '…' : '' }} still out</span>
        </router-link>
        <router-link v-if="attention.maintOverdue" to="/maintenance" class="row" style="gap:8px;align-items:center">
          <span class="badge danger">{{ attention.maintOverdue }}</span>
          <span>maintenance job{{ attention.maintOverdue === 1 ? '' : 's' }} overdue</span>
        </router-link>
        <router-link v-if="attention.restock" to="/restock" class="row" style="gap:8px;align-items:center">
          <span class="badge warn">{{ attention.restock }}</span>
          <span>consumable{{ attention.restock === 1 ? '' : 's' }} running low</span>
        </router-link>
        <router-link v-if="attention.warranty30" to="/report" class="row" style="gap:8px;align-items:center">
          <span class="badge warn">{{ attention.warranty30 }}</span>
          <span>warrant{{ attention.warranty30 === 1 ? 'y expires' : 'ies expire' }} within 30 days</span>
        </router-link>
      </div>
    </div>

    <div class="stat-grid">
      <div v-for="t in tiles()" :key="t.label" class="stat"
           :style="t.to ? 'cursor:pointer' : ''" @click="t.to && router.push(t.to)">
        <div class="stat-ico">{{ t.icon }}</div>
        <div class="value">{{ t.value }}</div>
        <div class="label">{{ t.label }}</div>
      </div>
    </div>

    <div class="page-head" style="margin:30px 0 16px">
      <h2 style="margin:0">Recently added</h2>
      <div class="grow"></div>
      <router-link to="/items">View all →</router-link>
    </div>
    <div v-if="recent.length" class="card-grid">
      <ItemCard v-for="i in recent" :key="i.id" :item="i" />
    </div>
    <div v-else class="card">
      <EmptyState icon="📦" title="No items yet"
                  hint="Create your first item to start tracking your inventory.">
        <button @click="router.push('/items')">Go to items</button>
      </EmptyState>
    </div>

    <div v-if="locations.length" class="page-head" style="margin:30px 0 16px">
      <h2 style="margin:0">Locations</h2>
      <div class="grow"></div>
      <router-link to="/locations">Manage →</router-link>
    </div>
    <div v-if="locations.length" class="card-grid">
      <div v-for="l in locations.slice(0, 8)" :key="l.id" class="item-card"
           @click="router.push('/locations/' + l.id)">
        <div class="body">
          <div class="title">📍 {{ l.name }}</div>
          <div class="sub">{{ (l.bins?.length || 0) }} bins</div>
        </div>
      </div>
    </div>
  </template>
</template>
