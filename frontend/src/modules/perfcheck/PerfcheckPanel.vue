<script setup>
import ResultDisplay from '../../components/ResultDisplay.vue';
import { onMounted } from 'vue';
import { usePerfcheckStore } from '../../stores/perfcheck';

const store = usePerfcheckStore();

onMounted(() => {
  if (!store.activeActionId) {
    store.initialize();
  }
});
</script>

<template>
  <div class="content-scroll">
    <section class="panel-shell panel-shell-stretch">
      <div class="workbench-tab-bar" style="margin-bottom: 16px; align-items: center; justify-content: space-between; gap: 12px;">
        <div style="font-weight: 600; color: var(--text-primary, #1f2937);">核验结果</div>
        <select
          class="workbench-tab-btn"
          :disabled="store.fixedResultsLoading || !store.fixedResults.length"
          :value="store.selectedFixedResultId"
          @change="store.selectFixedResult($event.target.value)"
          style="min-width: 360px; text-align: left; padding-right: 28px;"
        >
          <option v-for="item in store.fixedResults" :key="item.project_id" :value="item.project_id">
            {{ store.buildFixedResultLabel(item) }}
          </option>
        </select>
      </div>
      <ResultDisplay
        v-if="store.lastResult || store.resultText"
        :request-meta="store.requestMeta"
        :summary-items="store.summaryItems"
        :is-markdown-report-payload="store.isMarkdownReportPayload"
        :last-result="store.lastResult"
        :result-cards="store.resultCards"
        :result-text="store.resultText"
        :module-id="store.moduleId"
        :action-id="store.activeActionId"
      />
      <div v-else class="result-empty-state">
        <div class="result-empty-title">暂无结果</div>
        <div class="result-empty-desc">正在加载固定批次核验结果...</div>
      </div>
    </section>
  </div>
</template>
