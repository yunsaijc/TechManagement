<script setup>
import { useWorkbenchStore } from '../stores/workbench';
import PerfcheckPanel from '../modules/perfcheck/PerfcheckPanel.vue';
import ReviewPanel from '../modules/review/ReviewPanel.vue';
import GroupingPanel from '../modules/grouping/GroupingPanel.vue';
import PlagiarismPanel from '../modules/plagiarism/PlagiarismPanel.vue';
import EvaluationPanel from '../modules/evaluation/EvaluationPanel.vue';
import LogiconPanel from '../modules/logicon/LogiconPanel.vue';
import SandboxPanel from '../modules/sandbox/SandboxPanel.vue';

const store = useWorkbenchStore();
</script>

<template>
  <div class="main-content" v-if="store.currentModuleMeta">
    <div v-if="store.selectedModuleId === 'perfcheck'">
      <PerfcheckPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'review'">
      <ReviewPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'grouping'">
      <GroupingPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'plagiarism'">
      <PlagiarismPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'evaluation'">
      <EvaluationPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'logicon'">
      <LogiconPanel />
    </div>
    <div v-else-if="store.selectedModuleId === 'sandbox'">
      <SandboxPanel />
    </div>
    <div v-else class="content-scroll" />
  </div>
</template>
