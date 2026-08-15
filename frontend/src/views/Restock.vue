<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { useLoader } from '../components/useLoader'

const router = useRouter()
const rows = ref([])
const { loading, error, reload: load } = useLoader(async () => {
  rows.value = (await api.get('/restock')).items
})
</script>

<template>
  <div class="page-head">
    <h1>Restock</h1>
    <span v-if="rows.length" class="badge warn">{{ rows.length }} low</span>
    <div class="grow"></div>
  </div>

  <div v-if="loading" class="card"><div class="skeleton" style="height:200px"></div></div>
  <ErrorState v-else-if="error" :message="error" @retry="load" />
  <EmptyState v-else-if="!rows.length" icon="🛒" title="Nothing is running low"
              hint="Give a consumable a Min quantity on its item page — when it drops to that level it shows up here with how much to buy." />

  <div v-else class="card card-flush">
    <table>
      <thead><tr><th>Item</th><th>On hand</th><th>Restock at</th><th>Buy</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id" class="clickable"
            @click="router.push('/items/' + r.id)">
          <td><strong>{{ r.name }}</strong></td>
          <td>{{ r.onHand }}</td>
          <td>{{ r.threshold }}</td>
          <td><span class="badge warn">＋{{ r.suggestedQuantity }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
