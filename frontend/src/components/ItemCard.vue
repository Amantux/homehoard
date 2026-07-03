<script setup>
import { useRouter } from 'vue-router'
import { apiUrl, getToken } from '../api'

const props = defineProps({ item: { type: Object, required: true } })
const router = useRouter()

function thumb() {
  if (!props.item.imageId) return null
  const t = getToken()
  return apiUrl(`/documents/${props.item.imageId}`) + (t ? '' : '')
}
</script>

<template>
  <div class="item-card" @click="router.push('/items/' + item.id)">
    <div class="thumb" style="position:relative">
      <img v-if="item.imageId" :src="thumb()" alt="" @error="$event.target.style.display='none'" />
      <span v-else>📦</span>
      <span v-if="item.checkedOut" class="badge danger"
            style="position:absolute;top:6px;right:6px;background:var(--surface)">📤 Out</span>
    </div>
    <div class="body">
      <div class="title">{{ item.name }}</div>
      <div class="sub" v-if="item.location || item.bin">
        {{ item.bin ? '🗃️ ' + item.bin.name : '📍 ' + item.location.name }}
      </div>
      <div class="sub" v-if="Number(item.quantity) !== 1">Qty: {{ item.quantity }}</div>
      <div class="labels">
        <span v-for="l in item.labels" :key="l.id" class="chip"
              :style="l.color ? { background: l.color + '22', color: l.color } : {}">
          {{ l.name }}
        </span>
      </div>
    </div>
  </div>
</template>
