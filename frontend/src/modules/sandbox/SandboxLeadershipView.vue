<script setup>
import * as echarts from 'echarts';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps({
  report: { type: [Object, String, null], default: null },
  requestMeta: { type: String, default: '' },
});

const sankeyEl = ref(null);
const heatmapEl = ref(null);
let sankeyChart = null;
let heatmapChart = null;

const normalizedReport = computed(() => {
  const raw = props.report;
  if (!raw || typeof raw !== 'object') return null;
  if (raw.report && typeof raw.report === 'object') return raw.report;
  if (raw.data && typeof raw.data === 'object') return raw.data;
  return raw;
});

const leadershipBrief = computed(() => normalizedReport.value?.leadershipBrief || {});
const reportMeta = computed(() => normalizedReport.value?.meta || {});
const futureJudgement = computed(() => normalizedReport.value?.futureJudgement || {});
const summary = computed(() => futureJudgement.value?.summary || {});
const groupCounts = computed(() => summary.value?.groupCounts || {});
const priorityTopics = computed(() => Array.isArray(futureJudgement.value?.priorityTopics) ? futureJudgement.value.priorityTopics : []);
const migrationTopLinks = computed(() => Array.isArray(futureJudgement.value?.migrationTopLinks) ? futureJudgement.value.migrationTopLinks : []);
const graphProfile = computed(() => normalizedReport.value?.meta?.graphProfile || normalizedReport.value?.raw?.step2?.meta?.graphProfile || {});
const graphProfileNotes = computed(() => Array.isArray(graphProfile.value?.reliabilityNotes) ? graphProfile.value.reliabilityNotes : []);
const futureEvidenceLayers = computed(() => futureJudgement.value?.evidenceLayers || {});

const futureManagementSignals = computed(() => {
  const arr = futureEvidenceLayers.value?.management?.signals;
  return Array.isArray(arr) ? arr : [];
});

const futureKnowledgeSignals = computed(() => {
  const arr = futureEvidenceLayers.value?.knowledge?.signals;
  return Array.isArray(arr) ? arr : [];
});

const futureBridgeSignals = computed(() => {
  const arr = futureEvidenceLayers.value?.bridge?.signals;
  return Array.isArray(arr) ? arr : [];
});

const GROUP_LABEL_MAP = {
  risk: '风险',
  opportunity: '机会',
  talent: '人才',
  conversion: '转化',
};

const MODE_LABEL_MAP = {
  quick: '快速推演',
  standard: '标准推演',
  deep: '深度推演',
};

function formatWindowLabel(windowInfo, fallbackName) {
  const start = Number(windowInfo?.start);
  const end = Number(windowInfo?.end);
  if (Number.isFinite(start) && Number.isFinite(end)) {
    if (start === end) return `${start}年`;
    return `${start}-${end}年`;
  }
  return fallbackName;
}

function extractQuestionYears(text) {
  const raw = String(text || '');
  const matches = raw.match(/20\d{2}/g) || [];
  const years = [];
  const seen = new Set();
  for (const item of matches) {
    const y = Number(item);
    if (!Number.isFinite(y) || seen.has(y)) continue;
    seen.add(y);
    years.push(y);
  }
  return years;
}

const windowLabels = computed(() => {
  const step2Meta = normalizedReport.value?.raw?.step2?.meta || {};
  const labelA = formatWindowLabel(step2Meta.windowA, '窗口A');
  const labelB = formatWindowLabel(step2Meta.windowB, '窗口B');

  if (labelA !== '窗口A' || labelB !== '窗口B') {
    return { a: labelA, b: labelB };
  }

  const years = extractQuestionYears(reportMeta.value?.question || '');
  if (years.length >= 2) {
    return { a: `${years[0]}年`, b: `${years[1]}年` };
  }

  return { a: '上一窗口', b: '当前窗口' };
});

function localizeGroupKey(key) {
  return GROUP_LABEL_MAP[key] || key || '未知';
}

function localizeRiskLevel(level) {
  const mapping = { high: '高', medium: '中', low: '低' };
  return mapping[level] || (level || '-');
}

function localizeType(type) {
  const mapping = {
    low_conversion_after_growth: '高增低转',
    application_growth_spike: '申报激增',
    application_shrink_alert: '申报收缩',
    zero_output_high_heat: '高热零产出',
    conversion_drop_alert: '转化下滑',
    conversion_efficiency_gap: '转化效率差距',
    output_decline_with_growth: '产出下滑',
    persistent_low_conversion: '持续低转化',
    high_growth_high_conversion: '高增高转化',
    emerging_topic_opportunity: '新兴机会',
    high_conversion_stable_scale: '高转化稳定规模',
    conversion_recovery_signal: '转化恢复',
    talent_structure_gap: '人才结构缺口',
    senior_talent_shortage: '高层次人才不足',
    backbone_absent_risk: '骨干缺失风险',
    collaboration_network_weak: '协作网络偏弱',
    senior_backbone_imbalance: '高层次与骨干失衡',
  };
  if (!type || type === 'unknown') return '未知';
  return mapping[type] || type;
}

const modeLabel = computed(() => {
  const mode = reportMeta.value?.mode;
  return MODE_LABEL_MAP[mode] || mode || '-';
});

const SANKEY_MAX_SOURCES = 10;
const SANKEY_TARGETS_PER_SOURCE = 4;
const SANKEY_MAX_LINKS = 48;

function localizeSankeyLabel(label) {
  const text = String(label || '');
  const aMatch = text.match(/^A-C(\d+)$/);
  if (aMatch) return `${windowLabels.value.a}主题簇${aMatch[1]}`;
  const bMatch = text.match(/^B-C(\d+)$/);
  if (bMatch) return `${windowLabels.value.b}主题簇${bMatch[1]}`;
  return text;
}

function localizeCommunityRef(ref) {
  const text = String(ref || '');
  const a = text.match(/^A-(\d+)$/);
  if (a) return `${windowLabels.value.a}主题簇${a[1]}`;
  const b = text.match(/^B-(\d+)$/);
  if (b) return `${windowLabels.value.b}主题簇${b[1]}`;
  return text;
}

function percentText(value, total) {
  const a = Number(value || 0);
  const b = Number(total || 0);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= 0) return '-';
  return `${Math.round((a / b) * 100)}%`;
}

function countMapSize(map) {
  if (!map || typeof map !== 'object') return 0;
  return Object.values(map).filter((value) => Number(value || 0) > 0).length;
}

const graphProfileCards = computed(() => {
  const scientific = graphProfile.value?.scientificLayer || {};
  const management = graphProfile.value?.managementLayer || {};
  const bridge = graphProfile.value?.bridgeLayer || {};
  const sciLabels = scientific.labels || {};
  const mgmtLabels = management.labels || {};
  const mgmtRelations = graphProfile.value?.relations?.managementCore || {};
  const sciRelations = graphProfile.value?.relations?.scientificCore || {};
  const bridgeRelations = graphProfile.value?.relations?.bridge || {};

  return [
    {
      title: '知识层完整度',
      value: `${countMapSize(sciLabels)}/${Object.keys(sciLabels).length || 0}`,
      desc: `已覆盖 ${countMapSize(sciLabels)} 类知识实体，核心科学语义可用。`,
    },
    {
      title: '管理层完整度',
      value: `${countMapSize(mgmtLabels)}/${Object.keys(mgmtLabels).length || 0}`,
      desc: `已覆盖 ${countMapSize(mgmtLabels)} 类管理实体，人员/项目/成果链条可用。`,
    },
    {
      title: '桥接层完整度',
      value: bridge?.ready ? '已连接' : '缺失',
      desc: bridge?.ready ? '知识层与管理层已建立语义桥接。' : '暂未建成 involves_concept，跨层语义连接仍需补齐。',
    },
    {
      title: '关键关系覆盖',
      value: `${countMapSize(mgmtRelations) + countMapSize(sciRelations) + countMapSize(bridgeRelations)}/${Object.keys(mgmtRelations).length + Object.keys(sciRelations).length + Object.keys(bridgeRelations).length || 0}`,
      desc: '用于判断研判是否依赖关系链而非属性近似。',
    },
  ];
});

const migrationFlowData = computed(() => {
  const links = Array.isArray(migrationTopLinks.value) ? migrationTopLinks.value : [];
  return links.slice(0, 8).map((item) => ({
    label: `${localizeCommunityRef(item.source)} → ${localizeCommunityRef(item.target)}`,
    value: Number(item.value || 0),
    jaccard: Number(item.jaccard || 0),
  }));
});

const sankeyData = computed(() => {
  const sankey = normalizedReport.value?.raw?.step2?.sankey;
  if (!sankey || !Array.isArray(sankey.nodes) || !Array.isArray(sankey.links)) {
    return { nodes: [], links: [] };
  }

  const linksRaw = sankey.links.map((x) => ({
    source: x.source,
    target: x.target,
    value: Number(x.value || 0),
    jaccard: Number(x.jaccard || 0),
  }));

  const sourceWeight = new Map();
  for (const link of linksRaw) {
    sourceWeight.set(link.source, Number(sourceWeight.get(link.source) || 0) + link.value);
  }

  const topSources = [...sourceWeight.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, SANKEY_MAX_SOURCES)
    .map(([source]) => source);

  const selected = [];
  for (const source of topSources) {
    const topTargets = linksRaw
      .filter((l) => l.source === source)
      .sort((a, b) => (b.value - a.value) || (b.jaccard - a.jaccard))
      .slice(0, SANKEY_TARGETS_PER_SOURCE);
    selected.push(...topTargets);
  }

  const links = selected
    .sort((a, b) => (b.value - a.value) || (b.jaccard - a.jaccard))
    .slice(0, SANKEY_MAX_LINKS);

  const nodeSet = new Set();
  links.forEach((link) => {
    nodeSet.add(link.source);
    nodeSet.add(link.target);
  });

  const nodes = sankey.nodes
    .filter((n) => nodeSet.has(n.id))
    .map((n) => ({
      name: n.id,
      rawLabel: localizeSankeyLabel(n.label || n.id),
      value: Number(n.size || 0),
      itemStyle: {
        color: String(n.id || '').startsWith('A-') ? '#3b82f6' : '#22c55e',
      },
      label: {
        color: '#0f172a',
      },
    }));

  return { nodes, links };
});

const riskBubbleData = computed(() => {
  const entries = Object.entries(groupCounts.value || {});
  const xAxis = entries.map(([k]) => localizeGroupKey(k));
  const values = entries.map(([, v]) => Number(v || 0));
  const points = values.map((v, idx) => [xAxis[idx], v]);
  return { xAxis, points, max: Math.max(1, ...values) };
});

function buildSankeyOption() {
  const data = migrationFlowData.value.map((item) => ({
    name: item.label,
    value: item.value,
    jaccard: item.jaccard,
  }));
  if (!data.length) return null;

  const maxValue = Math.max(1, ...data.map((item) => item.value));

  return {
    title: {
      text: `迁移主路径条形图（${windowLabels.value.a}到${windowLabels.value.b}）`,
      subtext: '仅展示前 8 条主迁移路径，避免信息过载',
      left: 16,
      top: 10,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#0f172a' },
      subtextStyle: { fontSize: 11, color: '#64748b' },
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params) => `${params.name}<br/>迁移量：${params.value}<br/>相似度：${Number(params.data?.jaccard || 0).toFixed(3)}`,
    },
    series: [
      {
        type: 'bar',
        data: data,
        barWidth: 18,
        itemStyle: {
          borderRadius: [0, 8, 8, 0],
          color: '#4f76e8',
          shadowBlur: 6,
          shadowColor: 'rgba(79, 118, 232, 0.18)',
        },
        emphasis: { focus: 'series' },
      },
    ],
    grid: { top: 72, left: 260, right: 42, bottom: 18 },
    xAxis: {
      type: 'value',
      name: '迁移量',
      min: 0,
      max: Math.ceil(maxValue * 1.15),
      axisLabel: { color: '#334155', fontSize: 11 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'category',
      data: data.map((item) => item.name),
      axisLabel: {
        color: '#0f172a',
        fontSize: 11,
        width: 200,
        overflow: 'truncate',
      },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    label: {
      show: true,
      position: 'right',
      color: '#0f172a',
      fontSize: 11,
      formatter: (item) => item.value,
    },
  };
}

function buildHeatmapOption() {
  const data = riskBubbleData.value;
  if (!data.xAxis.length) return null;
  return {
    title: {
      text: '风险分组气泡图',
      left: 16,
      top: 10,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#0f172a' },
    },
    tooltip: {
      position: 'top',
      formatter: (params) => `${params.value[0]}：${params.value[1]}`,
    },
    grid: { top: 58, left: 48, right: 24, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.xAxis,
      axisLabel: { color: '#334155', fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: {
      type: 'value',
      name: '风险数量',
      min: 0,
      max: Math.ceil(data.max * 1.2),
      axisLabel: { color: '#334155', fontSize: 11 },
      nameTextStyle: { color: '#475569', fontSize: 11, padding: [0, 0, 0, -4] },
      splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
      axisLine: { show: false },
    },
    visualMap: {
      min: 0,
      max: data.max,
      dimension: 1,
      show: false,
      inRange: { color: ['#eff6ff', '#60a5fa', '#1e3a8a'] },
    },
    series: [
      {
        type: 'scatter',
        data: data.points,
        symbolSize: (val) => {
          const v = Number(val[1] || 0);
          return 18 + Math.round((v / Math.max(1, data.max)) * 42);
        },
        label: {
          show: true,
          color: '#111827',
          fontWeight: 600,
          formatter: (p) => p.value[1],
        },
        itemStyle: {
          shadowBlur: 8,
          shadowColor: 'rgba(37, 99, 235, 0.18)',
        },
      },
    ],
  };
}

async function renderCharts() {
  await nextTick();

  if (sankeyEl.value) {
    if (!sankeyChart) sankeyChart = echarts.init(sankeyEl.value);
    const option = buildSankeyOption();
    if (option) {
      sankeyChart.setOption(option, true);
    } else {
      sankeyChart.clear();
      sankeyChart.setOption({ title: { text: '热点迁移图暂无可视数据', left: 'center', top: 'middle', textStyle: { color: '#64748b', fontSize: 13 } } });
    }
  }

  if (heatmapEl.value) {
    if (!heatmapChart) heatmapChart = echarts.init(heatmapEl.value);
    const option = buildHeatmapOption();
    if (option) {
      heatmapChart.setOption(option, true);
    } else {
      heatmapChart.clear();
      heatmapChart.setOption({ title: { text: '风险热力图暂无可视数据', left: 'center', top: 'middle', textStyle: { color: '#64748b', fontSize: 13 } } });
    }
  }
}

watch(
  () => normalizedReport.value,
  () => {
    renderCharts();
  },
  { deep: true },
);

onMounted(() => {
  renderCharts();
  window.addEventListener('resize', resizeCharts);
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts);
  if (sankeyChart) {
    sankeyChart.dispose();
    sankeyChart = null;
  }
  if (heatmapChart) {
    heatmapChart.dispose();
    heatmapChart = null;
  }
});

function resizeCharts() {
  if (sankeyChart) sankeyChart.resize();
  if (heatmapChart) heatmapChart.resize();
}
</script>

<template>
  <div class="leadership-view" v-if="normalizedReport">
    <div class="view-meta">{{ requestMeta }}</div>

    <div class="brief-hero">
      <div class="hero-title">{{ leadershipBrief.headline || '暂无领导结论' }}</div>
      <div class="hero-sub">基于图谱迁移、转化效率与人才结构的协同推演输出</div>
      <div class="hero-meta" v-if="reportMeta.mode || reportMeta.generatedAt">
        <span v-if="reportMeta.mode">模式：{{ modeLabel }}</span>
        <span v-if="reportMeta.generatedAt">生成时间：{{ reportMeta.generatedAt }}</span>
      </div>
    </div>

    <div class="top-grid">
      <div class="metric-card">
        <div class="metric-label">研判等级</div>
        <div class="metric-value">{{ localizeRiskLevel(futureJudgement.riskLevel) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">风险指数</div>
        <div class="metric-value">{{ Number.isFinite(Number(futureJudgement.riskIndex)) ? `${Math.round(Number(futureJudgement.riskIndex) * 100)}%` : '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">高风险主题</div>
        <div class="metric-value">{{ summary.highRisk ?? '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">总发现项</div>
        <div class="metric-value">{{ summary.totalFindings ?? '-' }}</div>
      </div>
    </div>

    <div class="profile-grid" v-if="graphProfileCards.length">
      <div class="profile-card" v-for="card in graphProfileCards" :key="card.title">
        <div class="profile-title">{{ card.title }}</div>
        <div class="profile-value">{{ card.value }}</div>
        <div class="profile-desc">{{ card.desc }}</div>
      </div>
    </div>

    <section class="text-panel" v-if="graphProfileNotes.length">
      <h4>结论可靠性提示</h4>
      <ul>
        <li v-for="(note, idx) in graphProfileNotes.slice(0, 6)" :key="`g_${idx}`">{{ note }}</li>
      </ul>
    </section>

    <div class="text-grid" v-if="futureManagementSignals.length || futureKnowledgeSignals.length || futureBridgeSignals.length">
      <section class="text-panel" v-if="futureManagementSignals.length">
        <h4>管理层证据结论</h4>
        <ul>
          <li v-for="(item, idx) in futureManagementSignals" :key="`mg_${idx}`">{{ item }}</li>
        </ul>
      </section>
      <section class="text-panel" v-if="futureKnowledgeSignals.length">
        <h4>知识层语义结论</h4>
        <ul>
          <li v-for="(item, idx) in futureKnowledgeSignals" :key="`kg_${idx}`">{{ item }}</li>
        </ul>
      </section>
      <section class="text-panel" v-if="futureBridgeSignals.length">
        <h4>桥接层一致性</h4>
        <ul>
          <li v-for="(item, idx) in futureBridgeSignals" :key="`br_${idx}`">{{ item }}</li>
        </ul>
      </section>
    </div>

    <div class="chart-grid">
      <div class="chart-shell"><div ref="sankeyEl" class="chart-canvas" /></div>
      <div class="chart-shell"><div ref="heatmapEl" class="chart-canvas" /></div>
    </div>

    <div class="text-grid">
      <section class="text-panel">
        <h4>关键趋势信号</h4>
        <ul>
          <li v-for="(item, idx) in (futureJudgement.signals || []).slice(0, 6)" :key="`s_${idx}`">{{ item }}</li>
        </ul>
      </section>
      <section class="text-panel">
        <h4>下一年度治理建议</h4>
        <ul>
          <li v-for="(item, idx) in (futureJudgement.recommendations || []).slice(0, 6)" :key="`r_${idx}`">{{ item }}</li>
        </ul>
      </section>
    </div>

    <section class="text-panel">
      <h4>重点关注主题</h4>
      <div class="topic-list">
        <div class="topic-item" v-for="(item, idx) in priorityTopics.slice(0, 8)" :key="`p_${idx}`">
          <div class="topic-name">{{ idx + 1 }}. {{ item.topic || '<未知主题>' }}</div>
          <div class="topic-desc">{{ localizeType(item.type) }} | {{ item.suggestion || '-' }}</div>
        </div>
      </div>
    </section>

    <section class="text-panel" v-if="migrationTopLinks.length">
      <h4>迁移关键流</h4>
      <ul>
        <li v-for="(link, idx) in migrationTopLinks" :key="`m_${idx}`">
          从 {{ localizeCommunityRef(link.source) }} 到 {{ localizeCommunityRef(link.target) }} | 迁移量 {{ link.value }} | 相似度 {{ Number(link.jaccard || 0).toFixed(3) }}
        </li>
      </ul>
    </section>
  </div>
  <div v-else class="result-empty-state">
    <div class="result-empty-title">暂无推演结果</div>
    <div class="result-empty-desc">请先在功能操作中发起一次推演。</div>
  </div>
</template>

<style scoped>
.leadership-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.view-meta {
  color: #475569;
  font-size: 12px;
}

.brief-hero {
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 12px;
  background: linear-gradient(135deg, #eef2ff 0%, #f8fafc 100%);
}

.hero-title {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
}

.hero-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #475569;
}

.hero-meta {
  margin-top: 6px;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 11px;
  color: #64748b;
}

.top-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.profile-card {
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  padding: 12px;
}

.profile-title {
  color: #475569;
  font-size: 12px;
}

.profile-value {
  margin-top: 6px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
}

.profile-desc {
  margin-top: 6px;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.metric-card {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #ffffff;
  padding: 10px;
}

.metric-label {
  color: #64748b;
  font-size: 12px;
}

.metric-value {
  margin-top: 6px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
}

.chart-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 12px;
}

.chart-shell {
  border: 1px solid #d1d5db;
  border-radius: 12px;
  background: #ffffff;
  min-height: 340px;
}

.chart-canvas {
  width: 100%;
  height: 340px;
}

.text-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.text-panel {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 12px;
}

.text-panel h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: #0f172a;
}

.text-panel ul {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.6;
}

.topic-list {
  display: grid;
  gap: 8px;
}

.topic-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px;
  background: #f8fafc;
}

.topic-name {
  font-size: 13px;
  color: #0f172a;
  font-weight: 600;
}

.topic-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }

  .text-grid {
    grid-template-columns: 1fr;
  }
}
</style>
