<script setup>
defineProps({
  message: { type: String, required: true },
});
</script>

<template>
  <div class="toast-container">
    <div class="toast" :class="message.includes('失败') || message.includes('错误') ? 'error' : 'success'">
      {{ message }}
    </div>
  </div>
</template>
