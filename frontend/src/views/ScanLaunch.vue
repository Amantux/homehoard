<script setup>
// Deep-link target so Home Assistant (or a bookmark) can open the scanner
// directly, optionally in a mode:  /scan?action=checkout
import { useRoute, useRouter } from 'vue-router'
import ScannerModal from '../components/ScannerModal.vue'

const route = useRoute()
const router = useRouter()
</script>

<template>
  <h1 class="visually-hidden">Scan</h1>
  <ScannerModal :initial-mode="String(route.query.action || '')" @close="router.push('/')" />
</template>
