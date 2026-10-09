<script setup>
// Form field wrapper: label above, the input (default slot), and an inline
// error below in the danger colour when `error` is set.
defineProps({ label: String, error: String })
</script>

<template>
  <label class="field"><span>{{ label }}</span>
    <slot />
    <span v-if="error" class="field-error" role="alert">{{ error }}</span>
  </label>
</template>
