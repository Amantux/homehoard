<script setup>
defineProps({ icon: { type: String, default: '📭' }, title: String, hint: String })
</script>

<template>
  <div class="empty-state">
    <div class="ico">{{ icon }}</div>
    <h3 v-if="title">{{ title }}</h3>
    <p v-if="hint">{{ hint }}</p>
    <div style="margin-top:14px"><slot /></div>
  </div>
</template>
