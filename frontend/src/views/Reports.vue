<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'

// The reports index: the backend registry (GET /api/v1/reports) is the source of
// truth for what reports exist, so this screen just lists what it says. Choosing
// a report hands off to the single-report route, which loads it the same way this
// surface loads the inventory report (api.get + loading/error/retry).
const router = useRouter()
const reports = ref([])

const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true; error.value = ''
  try { reports.value = (await api.getReports()) || [] }
  catch (e) { error.value = e.message || 'Could not load the reports.'; reports.value = [] }
  finally { loading.value = false }
}
onMounted(load)

function open(r) { router.push('/reports/' + r.id) }
</script>

<template>
  <div class="page-head">
    <h1>Reports</h1>
    <div class="grow"></div>
    <span class="badge" v-if="!loading && !error">{{ reports.length }}</span>
  </div>

  <div v-if="loading" class="card muted">Loading your reports…</div>

  <ErrorState v-else-if="error" :message="error" @retry="load" />

  <template v-else>
    <div v-if="reports.length" class="grid">
      <div v-for="r in reports" :key="r.id" class="card" style="display:flex;flex-direction:column;gap:10px">
        <div class="row">
          <strong style="flex:1">{{ r.title }}</strong>
        </div>
        <div class="muted txt-sm">Report ID: <code>{{ r.id }}</code></div>
        <div class="row" style="gap:6px">
          <button class="secondary sm" @click="open(r)">Open report</button>
        </div>
      </div>
    </div>

    <div v-else class="card">
      <EmptyState icon="📄" title="No reports registered" hint="The backend registry has no reports to list yet." />
    </div>
  </template>
</template>
