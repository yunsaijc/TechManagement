<script setup>
import ActionTabs from '../../components/ActionTabs.vue';
import DynamicForm from '../../components/DynamicForm.vue';
import ResultDisplay from '../../components/ResultDisplay.vue';
import GraphView from '../../components/GraphView.vue';
import { onMounted } from 'vue';
import { useLogiconStore } from '../../stores/logicon';

const store = useLogiconStore();

onMounted(() => {
  if (!store.activeActionId) {
    store.initialize();
  }
});
</script>

<template>
  <div class="content-scroll">
    <div class="workbench-tab-bar">
      <button
        class="workbench-tab-btn"
        :class="{ active: store.activeTab === 'form' }"
        @click="store.setActiveTab('form')"
      >功能操作</button>
      <button
        class="workbench-tab-btn"
        :class="{ active: store.activeTab === 'result' }"
        @click="store.setActiveTab('result')"
      >结果展示</button>
    </div>

    <div v-if="store.activeTab === 'form'" class="workbench-tab-panel">
      <section class="panel-shell panel-shell-stretch">
        <ActionTabs
          v-if="store.moduleConfig && store.moduleConfig.actions && store.moduleConfig.actions.length > 1"
          :actions="store.moduleConfig.actions"
          :active-action-id="store.activeActionId"
          variant="select"
          @select="store.setAction"
        />
        <DynamicForm
          :action="store.activeAction"
          :form-data="store.formData"
          :files="store.files"
          :request-in-progress="store.requestInProgress"
          :last-result="store.lastResult"
          @file-change="store.onFileChange"
          @file-remove="store.onFileRemove"
          @submit="store.submit"
          @stop-request="store.stop"
          @fill-example="store.fillExample"
          @copy-result="store.copyResult"
          @clear-result="store.clearResult"
        />
      </section>
    </div>

    <div v-else class="workbench-tab-panel">
      <section class="panel-shell panel-shell-stretch">
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
        <div v-if="store.hasGraph" class="graph-section">
          <div class="graph-title">文档图谱关系</div>
          <GraphView :nodes="store.graphNodes" :edges="store.graphEdges" />
        </div>
        <div v-if="!store.lastResult && !store.resultText" class="result-empty-state">
          <div class="result-empty-title">暂无结果</div>
          <div class="result-empty-desc">提交核验任务后在这里查看结果与冲突点。</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.graph-section {
  margin-top: 12px;
}
.graph-title {
  font-size: 14px;
  color: #374151;
  margin: 8px 0;
}
</style>
