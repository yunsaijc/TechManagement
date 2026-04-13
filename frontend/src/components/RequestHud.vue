<script setup>
defineProps({
  title: { type: String, required: true },
});
</script>

<template>
  <div class="request-hud" role="status" aria-live="polite">
    <div class="request-hud-spinner"></div>
    <div class="request-hud-content">
      <div class="request-hud-title">{{ title }}</div>
      <div class="request-hud-subtitle">处理中，你可以继续查看页面</div>
    </div>
  </div>
</template>
