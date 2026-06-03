<script setup>
import { useWorkbenchStore } from '../stores/workbench';
import AcceptPanel from '../modules/accept/AcceptPanel.vue';
import PerfcheckPanel from '../modules/perfcheck/PerfcheckPanel.vue';
import ReviewPanel from '../modules/review/ReviewPanel.vue';
import GroupingPanel from '../modules/grouping/GroupingPanel.vue';
import ExpertMatchPanel from '../modules/expert/ExpertMatchPanel.vue';
import PlagiarismPanel from '../modules/plagiarism/PlagiarismPanel.vue';
import EvaluationPanel from '../modules/evaluation/EvaluationPanel.vue';
import KnowledgeGraphPanel from '../modules/knowledge/KnowledgeGraphPanel.vue';
import LogiconPanel from '../modules/logicon/LogiconPanel.vue';
import LogiconReportsPanel from '../modules/logicon/LogiconReportsPanel.vue';
import SandboxPanel from '../modules/sandbox/SandboxPanel.vue';

const store = useWorkbenchStore();
</script>

<template>
  <div class="main-content" v-if="store.currentModuleMeta">
    <div v-if="store.selectedModuleId === 'accept'" class="module-stage module-stage-accept">
      <AcceptPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'perfcheck'" class="module-stage">
      <PerfcheckPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'logicon_reports'" class="module-stage">
      <LogiconReportsPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'review'" class="module-stage">
      <ReviewPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'grouping'" class="module-stage">
      <GroupingPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'expert_match'" class="module-stage">
      <ExpertMatchPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'plagiarism'" class="module-stage">
      <PlagiarismPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'evaluation'" class="module-stage">
      <EvaluationPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'knowledge_graph'" class="module-stage">
      <KnowledgeGraphPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'logicon'" class="module-stage">
      <LogiconPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'sandbox'" class="module-stage">
      <SandboxPanel />
    </div>
    <div v-else class="content-scroll module-stage" />
  </div>
</template>

<style scoped>
.module-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  min-width: 0;
  overflow: auto;
}

.module-stage-accept {
  overflow: hidden;
}
</style>
