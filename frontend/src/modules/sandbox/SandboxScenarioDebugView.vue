<script setup>
import { computed, ref, watch } from 'vue';
import { getScenarioTopicOptions, useScenarioYearRuns } from './scenario_embedded/useScenarioYearRuns';
import { getScenarioMetricCards } from './scenario_embedded/useScenarioMetrics';
import { getScenarioImpactRows } from './scenario_embedded/useScenarioImpactTable';
import { getScenarioChartPayload } from './scenario_embedded/useScenarioCharts';
import ScenarioTopBar from './scenario_embedded/ScenarioTopBar.vue';
import ScenarioSidebar from './scenario_embedded/ScenarioSidebar.vue';
import ScenarioGraphPanel from './scenario_embedded/ScenarioGraphPanel.vue';
import ScenarioYearTabs from './scenario_embedded/ScenarioYearTabs.vue';
import ScenarioMetricCards from './scenario_embedded/ScenarioMetricCards.vue';
import ScenarioImpactTable from './scenario_embedded/ScenarioImpactTable.vue';
import ScenarioCharts from './scenario_embedded/ScenarioCharts.vue';
import ScenarioPropagationGraph from './scenario_embedded/ScenarioPropagationGraph.vue';
import './scenario_embedded/scenarioStyle.css';

const pageRootEl = ref(null);
const searchKeyword = ref('');
const selectedTopicIds = ref([]);
const graphFilterMode = ref('all');
const graphShowSpill = ref(true);
const { activeYear: initialYear, yearOptions } = useScenarioYearRuns();
const selectedYear = ref(initialYear);
const topicOptions = computed(() => getScenarioTopicOptions(selectedYear.value));
const metricCards = computed(() => getScenarioMetricCards(selectedYear.value, selectedTopicIds.value, searchKeyword.value));
const impactRows = computed(() => getScenarioImpactRows(selectedYear.value, selectedTopicIds.value, searchKeyword.value));
const chartPayload = computed(() => getScenarioChartPayload(selectedYear.value, selectedTopicIds.value, searchKeyword.value));
const hasActiveFilters = computed(() => (
  Boolean(String(searchKeyword.value || '').trim())
  || selectedTopicIds.value.length < topicOptions.value.length
  || graphFilterMode.value !== 'all'
  || !graphShowSpill.value
));

watch(topicOptions, (nextOptions) => {
  const nextIds = new Set((nextOptions || []).map((item) => String(item.id)));
  if (!nextIds.size) {
    selectedTopicIds.value = [];
    return;
  }
  const kept = selectedTopicIds.value.filter((id) => nextIds.has(String(id)));
  selectedTopicIds.value = kept.length ? kept : Array.from(nextIds);
}, { immediate: true });

function scrollInsideRuntime(id) {
  if (!pageRootEl.value) return;
  const target = pageRootEl.value.querySelector(`#${id}`);
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function exportRuntimeReport() {
  if (!pageRootEl.value) return;
  const content = '<!doctype html>\n' + pageRootEl.value.innerHTML;
  const blob = new Blob([content], { type: 'text/html;charset=utf-8' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = 'scenario_report_export.html';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function resetGraphFilters() {
  graphFilterMode.value = 'all';
  graphShowSpill.value = true;
}

function resetAllFilters() {
  searchKeyword.value = '';
  selectedTopicIds.value = topicOptions.value.map((item) => String(item.id));
  resetGraphFilters();
}
</script>

<template>
  <div ref="pageRootEl" class="scenario-runtime-host">
    <ScenarioTopBar
      title="政策沙盘推演"
      subtitle="对 7 个研究方向增加支持，新增经费 28.7 万元，新增项目 9 个"
      @guide="scrollInsideRuntime('instructions')"
      @examples="scrollInsideRuntime('examples')"
      @export="exportRuntimeReport"
    />
    <div v-if="hasActiveFilters" class="filter-summary">
      <span>已应用筛选：关键词「{{ searchKeyword || '无' }}」｜方向 {{ selectedTopicIds.length }}/{{ topicOptions.length }} ｜图谱 {{ graphFilterMode === 'all' ? '全部连接' : '只看直接' }}{{ graphShowSpill ? ' + 外溢' : '' }}</span>
      <button type="button" class="filter-reset-btn" @click="resetAllFilters">清空全部筛选</button>
    </div>
    <div class="scenario-main">
      <ScenarioSidebar
        :keyword="searchKeyword"
        :topic-options="topicOptions"
        :selected-topic-ids="selectedTopicIds"
        @apply-search="searchKeyword = $event"
        @update:keyword="searchKeyword = $event"
        @update:selected-topic-ids="selectedTopicIds = $event"
      />
      <ScenarioGraphPanel>
        <ScenarioYearTabs v-model="selectedYear" :options="yearOptions" />
        <ScenarioMetricCards :cards="metricCards" />
        <ScenarioCharts :payload="chartPayload" />
        <ScenarioImpactTable :rows="impactRows" />
        <ScenarioPropagationGraph
          :year="selectedYear"
          :search-keyword="searchKeyword"
          :filter-mode="graphFilterMode"
          :show-spill="graphShowSpill"
          :selected-topic-ids="selectedTopicIds"
          @update:filter-mode="graphFilterMode = $event"
          @update:show-spill="graphShowSpill = $event"
          @reset-filters="resetGraphFilters"
        />
      </ScenarioGraphPanel>
    </div>
  </div>
</template>

<style scoped>
.scenario-runtime-host {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  background: #f3f5f9;
}

.scenario-main {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(286px, 320px) minmax(0, 1fr);
  gap: 10px;
  padding: 10px;
}

.filter-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid #e5eaf2;
  background: #f7f9fc;
  font-size: 12px;
  color: #5d6f86;
}

.filter-reset-btn {
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #d6e0ef;
  background: #fff;
  color: #3563dc;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

@media (max-width: 1200px) {
  .scenario-main {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }
}
</style>
