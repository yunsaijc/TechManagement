<script setup>
import { computed } from 'vue';

const reportSrc = computed(() => '/debug-accept/index.html');
</script>

<template>
  <div class="accept-report-wrap">
    <iframe
      class="accept-report-frame"
      :src="reportSrc"
      title="验收核查"
    />
  </div>
</template>

<style scoped>
.accept-report-wrap {
  flex: 1;
  height: calc(100vh - 78px);
  min-height: 720px;
  width: 100%;
  padding: 4px 8px 12px;
}

.accept-report-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 10px rgba(31, 58, 95, 0.08);
}

@media (max-width: 900px) {
  .accept-report-wrap {
    height: calc(100vh - 72px);
    min-height: 560px;
    padding: 0;
  }

  .accept-report-frame {
    border-radius: 0;
  }
}
</style>
