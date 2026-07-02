<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { money, loadCurrency } from '../format'
import ItemCard from '../components/ItemCard.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const stats = ref(null)
const recent = ref([])
const locations = ref([])
const loading = ref(true)

onMounted(async () => {
  await loadCurrency()
  const [s, r, l] = await Promise.all([
    api.get('/groups/statistics'),
    api.get('/items?orderBy=createdAt&pageSize=6'),
    api.get('/locations'),
  ])
  stats.value = s
  recent.value = r.items
  locations.value = l
  loading.value = false
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

  <template v-else>
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
