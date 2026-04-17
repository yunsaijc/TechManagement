<script setup>
import { computed } from 'vue';

const evaluationSrc = computed(() => {
  const path = '/debug-eval/index.html';
  const { protocol, hostname, port } = window.location;
  const currentPort = String(port || '').trim();

  if (!currentPort || currentPort === '8000' || currentPort === '8005') {
    return path;
  }

  if (currentPort === '8006' || currentPort === '5173' || currentPort === '5174' || currentPort === '4173' || currentPort === '3000') {
    return `${protocol}//${hostname}:8000${path}`;
  }

  return path;
});
</script>

<template>
  <div class="eval-frame-shell">
    <iframe
      class="eval-frame"
      :src="evaluationSrc"
      title="项目评审工作台"
    />
  </div>
</template>

<style scoped>
.eval-frame-shell {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.eval-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}
</style>
