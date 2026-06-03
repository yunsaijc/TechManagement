<script setup>
import { ref } from 'vue';
import SandboxMacroInsightView from './SandboxMacroInsightView.vue';

const activeTab = ref('policy');
</script>

<template>
  <div class="sandbox-panel">
    <div class="sandbox-tabs">
      <button type="button" class="tab-btn" :class="{ active: activeTab === 'policy' }" @click="activeTab = 'policy'">热点迁移</button>
      <button type="button" class="tab-btn" :class="{ active: activeTab === 'risk' }" @click="activeTab = 'risk'">风险研判</button>
      <button type="button" class="tab-btn" :class="{ active: activeTab === 'policy_simulation' }" @click="activeTab = 'policy_simulation'">沙盘推演</button>
      <button type="button" class="tab-btn" :class="{ active: activeTab === 'llm_expert' }" @click="activeTab = 'llm_expert'">LLM辅助专家研判</button>
    </div>
    <div class="sandbox-tab-content">
      <div v-if="activeTab === 'policy'" class="sandbox-embed-wrap sandbox-embed-wrap--scaled">
        <iframe
          class="sandbox-embed-frame sandbox-embed-frame--scaled"
          src="/debug-sandbox/hotspot_migration_real_schema_2023_to_2024.cluster_nodes.html"
          title="热点迁移"
          loading="lazy"
        />
      </div>
      <SandboxMacroInsightView v-else-if="activeTab === 'risk'" />
      <div v-else-if="activeTab === 'policy_simulation'" class="sandbox-embed-wrap">
        <iframe
          class="sandbox-embed-frame"
          src="/debug-sandbox/simulation/scenario_latest.debug.html"
          title="沙盘推演"
          loading="lazy"
        />
      </div>
      <div v-else-if="activeTab === 'llm_expert'" class="sandbox-embed-wrap">
        <iframe
          class="sandbox-embed-frame"
          src="/debug-sandbox/graph_rag_answer.html"
          title="LLM辅助专家研判"
          loading="lazy"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.sandbox-panel { display: grid; grid-template-rows: auto minmax(0, 1fr); width: 100%; min-height: 0; }
.sandbox-tabs { display: flex; gap: 8px; padding: 8px 10px 0; background: #f8fbff; border-bottom: 1px solid #d6e1ee; }
.tab-btn { height: 34px; padding: 0 14px; border-radius: 10px 10px 0 0; border: 1px solid #d6e1ee; border-bottom: none; background: #eef4fa; color: #3d5875; font-size: 13px; font-weight: 700; cursor: pointer; }
.tab-btn.active { background: #fff; color: #1f3a5f; }
.sandbox-tab-content { min-height: 0; height: 100%; overflow: hidden; display: flex; flex-direction: column; }
.sandbox-embed-wrap { width: 100%; height: 100%; min-height: 0; background: #fff; }
.sandbox-embed-wrap--scaled { overflow: auto; }
.sandbox-embed-frame { width: 100%; height: 100%; border: none; display: block; }
.sandbox-embed-frame--scaled { width: max(100%, 1280px); min-width: 1280px; }
</style>
