<script setup>
import { ref } from 'vue';
import PlagiarismReportView from './PlagiarismReportView.vue';
import PlagiarismImageReportView from './PlagiarismImageReportView.vue';

const activeMode = ref('text');
</script>

<template>
  <div class="content-scroll" :class="{ 'content-scroll-image': activeMode === 'image' }">
    <div class="plagiarism-mode-tabs">
      <button
        class="mode-tab"
        :class="{ active: activeMode === 'text' }"
        @click="activeMode = 'text'"
      >
        文本查重
      </button>
      <button
        class="mode-tab"
        :class="{ active: activeMode === 'image' }"
        @click="activeMode = 'image'"
      >
        图片查重
      </button>
    </div>
    <section v-if="activeMode === 'text'" class="panel-shell panel-shell-stretch">
      <PlagiarismReportView />
    </section>
    <div v-else class="image-mode-stage">
      <PlagiarismImageReportView />
    </div>
  </div>
</template>

<style scoped>
.content-scroll-image {
  padding: 0;
  overflow: hidden;
}

.plagiarism-mode-tabs {
  display: flex;
  gap: 8px;
  padding: 8px 0 12px;
}

.content-scroll-image .plagiarism-mode-tabs {
  padding: 14px 14px 8px;
}

.image-mode-stage {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.mode-tab {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #334155;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}

.mode-tab.active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1e40af;
}
</style>
