<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { money, shortDate, loadCurrency } from '../format'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const data = ref({ entries: [], costTotal: 0 })
const filter = ref('both')
const loading = ref(true)

async function load() {
  loading.value = true
  const p = filter.value === 'both' ? '' : '?status=' + filter.value
  data.value = await api.get('/maintenance' + p)
  loading.value = false
}
onMounted(async () => { await loadCurrency(); await load() })

const scheduled = computed(() => data.value.entries.filter((e) => e.status === 'scheduled'))
</script>

<template>
  <div class="page-head">
    <h1>Maintenance</h1>
    <div class="grow"></div>
    <span class="badge">Total spent: {{ money(data.costTotal) }}</span>
    <select v-model="filter" style="width:auto" @change="load">
      <option value="both">All</option>
      <option value="scheduled">Scheduled</option>
      <option value="completed">Completed</option>
    </select>
  </div>

  <div v-if="loading" class="card"><div class="skeleton" style="height:200px"></div></div>
  <template v-else-if="data.entries.length">
    <div v-if="scheduled.length" class="card" style="margin-bottom:16px">
      <h2>Upcoming</h2>
      <table><tbody>
        <tr v-for="m in scheduled" :key="m.id" class="clickable" @click="router.push('/items/'+m.itemId)">
          <td><strong>{{ m.name }}</strong></td>
          <td>{{ m.itemName }}</td>
          <td><span v-if="m.overdue" class="badge danger">Overdue</span> {{ shortDate(m.scheduledDate) }}</td>
          <td>{{ money(m.cost) }}</td>
        </tr>
      </tbody></table>
    </div>

    <div class="card card-flush">
      <table>
        <thead><tr><th>Task</th><th>Item</th><th>Status</th><th>Date</th><th>Cost</th></tr></thead>
        <tbody>
          <tr v-for="m in data.entries" :key="m.id" class="clickable" @click="router.push('/items/'+m.itemId)">
            <td><strong>{{ m.name }}</strong><div class="muted" style="font-size:0.8rem">{{ m.description }}</div></td>
            <td>{{ m.itemName }}</td>
            <td><span class="badge" :class="m.status==='completed'?'ok':(m.overdue?'danger':'')">{{ m.status }}</span></td>
            <td>{{ shortDate(m.completedDate || m.scheduledDate) }}</td>
            <td>{{ money(m.cost) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
  <div v-else class="card">
    <EmptyState icon="🔧" title="No maintenance records"
                hint="Log maintenance from any item's Maintenance tab." />
  </div>
</template>
