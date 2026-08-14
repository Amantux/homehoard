<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { shortDate } from '../format'
import { useUI } from '../stores/ui'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

const router = useRouter()
const ui = useUI()
const rows = ref([])
const checkingIn = ref('') // item id with a pending check-in, so its button shows state

const { loading, error, reload: load } = useLoader(async () => {
  rows.value = (await api.get('/checkouts')).items
})

// Overdue first — that is what someone opens this page to see.
const sorted = computed(() =>
  [...rows.value].sort((a, b) => (b.overdue ? 1 : 0) - (a.overdue ? 1 : 0)))
const overdueCount = computed(() => rows.value.filter((r) => r.overdue).length)

async function checkIn(row) {
  checkingIn.value = row.id
  try {
    await api.post(`/items/${row.id}/checkin`, {})
    ui.toast(`${row.name} is back`)
    await load()
  } catch (e) {
    ui.error(e.message || `Could not check ${row.name} in.`)
  } finally {
    checkingIn.value = ''
  }
}
</script>

<template>
  <div class="page-head">
    <h1>Checked out</h1>
    <span v-if="overdueCount" class="badge danger">{{ overdueCount }} overdue</span>
    <div class="grow"></div>
  </div>

  <div v-if="loading" class="card"><div class="skeleton" style="height:200px"></div></div>
  <ErrorState v-else-if="error" :message="error" @retry="load" />
  <EmptyState v-else-if="!rows.length" icon="📤" title="Nothing is checked out"
              hint="Lend something out from its item page — who has it and a due date are optional. It shows up here until it comes back." />

  <div v-else class="card card-flush">
    <table>
      <thead>
        <tr><th>Item</th><th>Who</th><th>Since</th><th>Due</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="r in sorted" :key="r.id" class="clickable"
            @click="router.push('/items/' + r.id)">
          <td><strong>{{ r.name }}</strong></td>
          <td>{{ r.checkedOutTo || '—' }}</td>
          <td>{{ shortDate(r.checkedOutAt) }}</td>
          <td>
            <span v-if="r.overdue" class="badge danger">Overdue · {{ shortDate(r.checkoutDue) }}</span>
            <template v-else>{{ r.checkoutDue ? shortDate(r.checkoutDue) : '—' }}</template>
          </td>
          <!-- @click.stop like every action inside a clickable row: without it,
               checking in would ALSO navigate to the item. -->
          <td @click.stop style="text-align:right">
            <button class="secondary sm" :disabled="checkingIn === r.id" @click="checkIn(r)">
              {{ checkingIn === r.id ? 'Checking in…' : '📥 Check in' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
