<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { money, shortDate, loadCurrency } from '../format'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

const router = useRouter()
const data = ref({ entries: [], costTotal: 0 })
const filter = ref('both')

// useLoader: a failed load previously left `loading` true forever (the
// permanent-skeleton failure), and a thrown filter change did the same.
const { loading, error, reload: load } = useLoader(async () => {
  await loadCurrency()
  const p = filter.value === 'both' ? '' : '?status=' + filter.value
  data.value = await api.get('/maintenance' + p)
})

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
  <ErrorState v-else-if="error" :message="error" @retry="load" />
  <template v-else-if="data.entries.length">
    <div v-if="scheduled.length" class="card" style="margin-bottom:16px">
      <h2>Upcoming</h2>
      <table><tbody>
        <tr v-for="m in scheduled" :key="m.id" class="clickable" @click="router.push('/items/'+m.itemId)">
          <td><strong>{{ m.name }}</strong> <span v-if="m.recurMonths" class="badge" :title="`Repeats every ${m.recurMonths} months`">↻ {{ m.recurMonths }}mo</span></td>
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
            <td><strong>{{ m.name }}</strong> <span v-if="m.recurMonths" class="badge" :title="`Repeats every ${m.recurMonths} months`">↻ {{ m.recurMonths }}mo</span><div class="muted" style="font-size:0.8rem">{{ m.description }}</div></td>
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
