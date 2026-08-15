<script setup>
import { useRouter } from 'vue-router'
import { apiUrl } from '../api'

const props = defineProps({ item: { type: Object, required: true } })
const router = useRouter()

function thumb() {
  if (!props.item.imageId) return null
  // ?thumb=1 serves the 400px JPEG; the server falls back to the original
  // for photos that predate the thumbnail pipeline.
  return apiUrl(`/documents/${props.item.imageId}?thumb=1`)
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
      <!-- The whole card navigates to the item, so the place needs @click.stop
           or clicking it would open the item instead of the place. -->
      <div class="sub" v-if="item.location || item.bin" @click.stop>
        <router-link v-if="item.bin" :to="'/bins/' + item.bin.id">🗃️ {{ item.bin.name }}</router-link>
        <router-link v-else :to="'/locations/' + item.location.id">📍 {{ item.location.name }}</router-link>
      </div>
      <div class="sub" v-if="item.quantityHere !== undefined">
        Qty here: {{ item.quantityHere }}
        <span v-if="item.placementCount > 1" class="muted">· of {{ item.quantity }} in {{ item.placementCount }} places</span>
      </div>
      <div class="sub" v-else-if="Number(item.quantity) !== 1 || item.placementCount > 1">
        Qty: {{ item.quantity }}
        <span v-if="item.placementCount > 1" class="muted">· in {{ item.placementCount }} places</span>
      </div>
      <div class="labels">
        <span v-for="l in item.labels" :key="l.id" class="chip"
              :style="l.color ? { background: l.color + '22', color: l.color } : {}">
          {{ l.name }}
        </span>
      </div>
    </div>
  </div>
</template>
