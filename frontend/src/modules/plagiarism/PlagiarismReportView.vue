<script setup>
import { computed } from 'vue';

const reportSrc = computed(() => '/debug-plagiarism/by_guide_codes/plagiarism_batch_report.html');
</script>

<template>
  <div class="text-report-wrap">
    <iframe
      class="text-report-frame"
      :src="reportSrc"
      title="文本查重报告"
    />
  </div>
</template>

<style scoped>
.text-report-wrap {
  height: 100%;
  min-height: 0;
}

.text-report-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}
</style>
