<script setup>
defineProps({ message: String })
defineEmits(['retry'])
</script>

<template>
  <div class="empty-state" role="alert">
    <div class="ico">⚠️</div>
    <h3>Couldn't load this</h3>
    <p>{{ message || 'Something went wrong. Check your connection and try again.' }}</p>
    <div style="margin-top:14px">
      <button class="secondary" @click="$emit('retry')">Try again</button>
    </div>
  </div>
</template>
