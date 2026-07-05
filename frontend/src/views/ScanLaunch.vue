<script setup>
// Deep-link target so Home Assistant (or a bookmark) can open the scanner
// directly, optionally in a mode:  /scan?action=checkout
import { useRoute, useRouter } from 'vue-router'
import ScannerModal from '../components/ScannerModal.vue'

const route = useRoute()
const router = useRouter()
</script>

<template>
  <ScannerModal :initial-mode="String(route.query.action || '')" @close="router.push('/')" />
</template>
