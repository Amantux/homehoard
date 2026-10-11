<script setup>
import EmptyState from '../components/EmptyState.vue'
</script>

<template>
  <div class="card">
    <h1 class="visually-hidden">Page not found</h1>
    <EmptyState icon="🧭" title="Page not found" hint="That link doesn't go anywhere.">
      <router-link to="/" class="btn">Go to dashboard</router-link>
    </EmptyState>
  </div>
</template>
