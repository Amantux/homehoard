<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['close'])
const router = useRouter()

const q = ref('')
const results = ref([])
const loading = ref(false)
const input = ref(null)

let timer
watch(q, () => {
  clearTimeout(timer)
  timer = setTimeout(run, 200)
})

async function run() {
  const query = q.value.trim()
  if (!query) { results.value = []; return }
  loading.value = true
  try {
    results.value = (await api.get('/search?q=' + encodeURIComponent(query))).results
  } finally {
    loading.value = false
  }
}

function open(item) {
  emit('close')
  router.push('/items/' + item.id)
}

onMounted(async () => {
  await nextTick()
  input.value?.focus()
})
</script>

<template>
  <div class="modal-backdrop" style="align-items:flex-start;padding-top:10vh"
       @click.self="emit('close')">
    <div class="card modal" style="width:min(560px,100%);padding:0;overflow:hidden">
      <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center">
        <span>🔍</span>
        <input ref="input" v-model="q" placeholder="Find an item — where is my…?"
               style="border:none;background:none;box-shadow:none;padding:4px 0"
               @keyup.esc="emit('close')" />
        <button class="ghost sm" @click="emit('close')">Esc</button>
      </div>

      <div style="max-height:60vh;overflow:auto">
        <div v-if="loading && !results.length" style="padding:18px">
          <div class="skeleton" style="height:44px;margin-bottom:8px"></div>
          <div class="skeleton" style="height:44px"></div>
        </div>

        <div v-else-if="q && !results.length" class="muted" style="padding:24px;text-align:center">
          No items match “{{ q }}”.
        </div>

        <div v-else-if="!q" class="muted" style="padding:24px;text-align:center">
          Type to search your inventory by name, label, brand, or serial.
        </div>

        <button v-for="r in results" :key="r.id" class="search-row" @click="open(r)">
          <span class="search-icon">📦</span>
          <span class="search-main">
            <span class="search-name">{{ r.name }}</span>
            <span class="search-where">📍 {{ r.where }}</span>
          </span>
          <span v-if="Number(r.quantity) !== 1" class="badge">×{{ r.quantity }}</span>
          <span class="search-go">→</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-row {
  width: 100%; display: flex; align-items: center; gap: 12px;
  padding: 11px 16px; background: none; color: var(--text); border: none;
  border-bottom: 1px solid var(--border); border-radius: 0; text-align: left;
}
.search-row:hover { background: var(--accent-soft); }
.search-icon { font-size: 18px; }
.search-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.search-name { font-weight: 600; }
.search-where { font-size: 0.82rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-go { color: var(--muted); }
</style>
