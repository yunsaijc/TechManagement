<script setup>
import { computed } from 'vue';

const reportSrc = computed(() => '/debug-plagiarism/image/by_guide_codes/plagiarism_image_batch_report.html');
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
