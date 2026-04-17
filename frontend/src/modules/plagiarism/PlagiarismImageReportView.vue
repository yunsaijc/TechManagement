<script setup>
import { computed } from 'vue';

const reportSrc = computed(() => {
  const path = '/debug-plagiarism/image/by_guide_codes/plagiarism_image_batch_report.html';
  const { protocol, hostname, port } = window.location;
  const p = String(port || '').trim();

  if (!p || p === '8000' || p === '8005') {
    return path;
  }

  if (p === '8006' || p === '5173' || p === '5174' || p === '4173' || p === '3000') {
    return `${protocol}//${hostname}:8000${path}`;
  }

  return path;
});
</script>

<template>
  <div class="image-report-wrap">
    <iframe
      class="image-report-frame"
      :src="reportSrc"
      title="图片查重报告"
    />
  </div>
</template>

<style scoped>
.image-report-wrap {
  height: 100%;
  min-height: 0;
}

.image-report-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}
</style>
