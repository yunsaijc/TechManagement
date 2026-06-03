<script setup>
import { computed, ref, watch } from 'vue';
import { getScenarioGraphData } from './useScenarioGraphData';

const props = defineProps({
  year: {
    type: String,
    default: '',
  },
  searchKeyword: {
    type: String,
    default: '',
  },
  filterMode: {
    type: String,
    default: 'all',
  },
  showSpill: {
    type: Boolean,
    default: true,
  },
  selectedTopicIds: {
    type: Array,
    default: () => [],
  },
});
const emit = defineEmits(['update:filterMode', 'update:showSpill', 'reset-filters']);

const selectedTopicId = ref('');

const model = computed(() => {
  const base = getScenarioGraphData(props.year, props.filterMode, props.showSpill, props.selectedTopicIds);
  const keyword = String(props.searchKeyword || '').trim().toLowerCase();
  if (!keyword) return base;
  const visibleTopics = base.visibleTopics.filter((item) => {
    const text = `${item.shortLabel || ''} ${item.label || ''}`.toLowerCase();
    return text.includes(keyword);
  });
  const set = new Set(visibleTopics.map((item) => item.id));
  const visibleEdges = base.visibleEdges.filter((edge) => set.has(edge.sourceId) && set.has(edge.targetId));
  return {
    ...base,
    visibleTopics,
    visibleEdges,
    focusId: visibleTopics[0]?.id || '',
  };
});

watch(model, (next) => {
  if (!selectedTopicId.value || !next.topicMap.has(selectedTopicId.value)) {
    selectedTopicId.value = next.focusId || '';
  }
}, { immediate: true });

const selectedTopic = computed(() => model.value.topicMap.get(selectedTopicId.value) || null);
const detailProfile = computed(() => selectedTopic.value?.detailProfile || {});
const historyRows = computed(() => (detailProfile.value.history || []).slice(0, 8));
const guideRows = computed(() => ([...(detailProfile.value.guides || []), ...(detailProfile.value.industries || [])]).slice(0, 8));
const institutionRows = computed(() => (detailProfile.value.institutions || []).slice(0, 8));
const projectRows = computed(() => (detailProfile.value.sampleProjects || []).slice(0, 6));

function resetView() {
  emit('reset-filters');
  selectedTopicId.value = model.value.focusId || '';
}
</script>

<template>
  <section class="scenario-graph-wrap">
    <div class="graph-toolbar">
      <div class="graph-heading">
        <h2>影响传导路径</h2>
        <p>单场景关系图</p>
      </div>
      <div class="graph-controls">
        <button type="button" class="view-chip" :class="{ active: filterMode === 'all' }" @click="emit('update:filterMode', 'all')">全部连接</button>
        <button type="button" class="view-chip" :class="{ active: filterMode === 'direct' }" @click="emit('update:filterMode', 'direct')">只看直接影响</button>
        <button type="button" class="view-chip" :class="{ active: showSpill }" @click="emit('update:showSpill', !showSpill)">外溢影响</button>
        <button type="button" class="mini-btn" @click="resetView">重置视图</button>
      </div>
    </div>
    <div class="graph-status">当前焦点：{{ selectedTopic?.shortLabel || selectedTopic?.label || '未选择' }}</div>
    <div class="graph-shell">
      <svg class="graph-svg" viewBox="0 0 720 520">
        <g>
          <path
            v-for="edge in model.visibleEdges"
            :key="edge.edgeId"
            :d="`M ${model.positions.get(edge.sourceId)?.x || 0} ${model.positions.get(edge.sourceId)?.y || 0} Q ${(model.positions.get(edge.sourceId)?.x + model.positions.get(edge.targetId)?.x) / 2 || 0} ${((model.positions.get(edge.sourceId)?.y + model.positions.get(edge.targetId)?.y) / 2) + (edge.kind === 'spill' ? 28 : -22)} ${model.positions.get(edge.targetId)?.x || 0} ${model.positions.get(edge.targetId)?.y || 0}`"
            :class="['edge-line', edge.kind]"
          />
        </g>
        <g>
          <g
            v-for="topic in model.visibleTopics"
            :key="topic.id"
            class="graph-node"
            :class="{ selected: selectedTopicId === topic.id }"
            @click="selectedTopicId = topic.id"
          >
            <circle :cx="model.positions.get(topic.id)?.x" :cy="model.positions.get(topic.id)?.y" :r="(model.positions.get(topic.id)?.r || 12) + 6" class="halo" />
            <circle :cx="model.positions.get(topic.id)?.x" :cy="model.positions.get(topic.id)?.y" :r="model.positions.get(topic.id)?.r || 12" class="core" :class="{ direct: topic.direct }" />
            <text :x="model.positions.get(topic.id)?.x" :y="(model.positions.get(topic.id)?.y || 0) + 4" class="node-value">
              {{ Number(topic.maxAbs || 0).toFixed(0) }}
            </text>
            <text :x="model.positions.get(topic.id)?.x" :y="(model.positions.get(topic.id)?.y || 0) + (model.positions.get(topic.id)?.r || 12) + 16" class="node-label">
              {{ topic.shortLabel || topic.label }}
            </text>
          </g>
        </g>
      </svg>
    </div>
    <div class="topic-detail" v-if="selectedTopic">
      <strong>{{ selectedTopic.label }}</strong>
      <div>影响类型：{{ selectedTopic.direct ? '直接影响' : '外溢影响' }}</div>
      <div>基线申报：{{ selectedTopic.baselineApplication || 0 }}，基线立项：{{ selectedTopic.baselineFunded || 0 }}</div>
      <div>基线经费：{{ selectedTopic.baselineFunding || 0 }} 万元</div>
    </div>
    <div v-if="selectedTopic" class="topic-rich-detail">
      <article class="detail-card">
        <h4>年度走势</h4>
        <div v-if="historyRows.length" class="detail-list">
          <div v-for="item in historyRows" :key="`${item.year}-${item.projects}`" class="detail-item">
            <span>{{ item.year }}</span>
            <strong>{{ item.projects || 0 }} 项</strong>
          </div>
        </div>
        <div v-else class="detail-empty">暂无年度走势数据</div>
      </article>
      <article class="detail-card">
        <h4>指南与行业拆分</h4>
        <div v-if="guideRows.length" class="chips">
          <span v-for="item in guideRows" :key="item.label || item.name || item" class="chip">{{ item.label || item.name || item }}</span>
        </div>
        <div v-else class="detail-empty">暂无指南拆分数据</div>
      </article>
      <article class="detail-card">
        <h4>主要承担单位</h4>
        <div v-if="institutionRows.length" class="detail-list">
          <div v-for="item in institutionRows" :key="item.label || item.name || item" class="detail-item">
            <span>{{ item.label || item.name || item }}</span>
            <strong>{{ item.count || item.projects || '-' }}</strong>
          </div>
        </div>
        <div v-else class="detail-empty">暂无承担单位数据</div>
      </article>
      <article id="examples" class="detail-card">
        <h4>项目样本</h4>
        <div v-if="projectRows.length" class="project-list">
          <div v-for="item in projectRows" :key="item.projectName || item.name || JSON.stringify(item)" class="project-item">
            <strong>{{ item.projectName || item.name || '未命名项目' }}</strong>
            <div>{{ [item.institution, item.program, item.guide].filter(Boolean).join('｜') || '无补充信息' }}</div>
          </div>
        </div>
        <div v-else class="detail-empty">暂无项目样本</div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.scenario-graph-wrap { margin: 8px 8px 0; border: 1px solid #e6ebf3; border-radius: 8px; background: #fff; padding: 8px; }
.graph-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.graph-heading h2 { margin: 0; font-size: 13px; color: #2b3f57; }
.graph-heading p { margin: 2px 0 0; color: #7a8699; font-size: 11px; }
.graph-controls { display: flex; gap: 6px; flex-wrap: wrap; }
.view-chip,.mini-btn { height: 24px; padding: 0 9px; border: 1px solid #d5dfef; border-radius: 999px; background: #fff; font-size: 11px; cursor: pointer; }
.view-chip.active { background: #eaf1ff; border-color: #8bb0ff; color: #2b63df; }
.graph-status { margin-top: 6px; font-size: 11px; color: #64748b; }
.graph-shell { margin-top: 6px; border: 1px solid #edf2f8; border-radius: 8px; overflow: auto; }
.graph-svg { width: 100%; min-width: 720px; height: 360px; display: block; background: linear-gradient(180deg,#fbfdff,#f7faff); }
.edge-line { fill: none; stroke-width: 1.8; opacity: 0.72; }
.edge-line.direct { stroke: #3f7cff; }
.edge-line.spill { stroke: #32b67a; }
.edge-line.ghost { stroke: #94a3b8; stroke-dasharray: 3 3; }
.graph-node { cursor: pointer; }
.halo { fill: rgba(63,124,255,0.08); }
.core { fill: #7aa5ff; stroke: #3f7cff; stroke-width: 2; }
.core.direct { fill: #3f7cff; }
.graph-node.selected .core { stroke: #ef4444; stroke-width: 3; }
.node-value { text-anchor: middle; fill: #fff; font-size: 12px; font-weight: 700; }
.node-label { text-anchor: middle; fill: #334155; font-size: 11px; }
.topic-detail { margin-top: 6px; padding: 7px 8px; border-radius: 8px; background: #f8fbff; border: 1px solid #e5ebf4; font-size: 11px; color: #334155; display: grid; gap: 2px; }
.topic-rich-detail {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.detail-card {
  border: 1px solid #e5ebf4;
  border-radius: 8px;
  padding: 7px;
  background: #fbfdff;
}
.detail-card h4 {
  margin: 0 0 6px;
  font-size: 12px;
}
.detail-list { display: grid; gap: 6px; }
.detail-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid #edf2f8;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
}
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #d9e3f2;
  background: #eef4ff;
  color: #2b63df;
  font-size: 11px;
}
.project-list { display: grid; gap: 6px; }
.project-item {
  border: 1px solid #edf2f8;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
  color: #334155;
}
.project-item strong { display: block; margin-bottom: 3px; color: #1f2937; }
.detail-empty {
  font-size: 12px;
  color: #7a8699;
  padding: 6px 4px;
}
@media (max-width: 1100px) {
  .topic-rich-detail { grid-template-columns: 1fr; }
}
</style>
