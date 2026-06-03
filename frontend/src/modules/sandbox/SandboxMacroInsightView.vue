<script setup>
import { computed, ref } from 'vue';
import macroInsightData from './macroInsight2023to2024Lite.json';

const data = macroInsightData || {};
const summary = computed(() => data.summary || {});
const briefing = computed(() => data.briefing || {});
const cards = computed(() => summary.value.cards || []);
const actions = computed(() => briefing.value.actions || []);
const findings = computed(() => data.topFindings || []);
const charts = computed(() => data.charts || {});
const riskTypeBars = computed(() => (charts.value.riskTypeBars || []).slice(0, 8));
const applicationBars = computed(() => (charts.value.topicApplicationBars || []).slice(0, 8));

const topicOptions = computed(() => Array.from(new Set(findings.value.map((item) => shortTopicName(item.topic)))));
const selectedTopic = ref('');
const topicFindings = computed(() => findings.value.filter((item) => (
  selectedTopic.value ? shortTopicName(item.topic) === selectedTopic.value : false
)));

function shortTopicName(topic) {
  const text = String(topic || '');
  return text.includes('｜') ? text.split('｜').slice(-1)[0] : text;
}

function riskPercent(value) {
  return ((Number(value || 0) / (totalRisk.value || 1)) * 100).toFixed(1);
}

function statValueClass(label) {
  const text = String(label || '');
  if (text.includes('高风险')) return 'stat-value-high';
  if (text.includes('中风险')) return 'stat-value-medium';
  return '';
}

function toPercent(value) {
  const num = Number(value || 0);
  return `${(num * 100).toFixed(num >= 0.1 ? 1 : 2)}%`;
}

function metricByKey(evidence, key) {
  const value = Number(evidence?.[key] || 0);
  return Number.isFinite(value) ? value : 0;
}

function metricPack(item) {
  const evidence = item?.evidence || {};
  const applications = Math.max(metricByKey(evidence, 'applicationsB'), metricByKey(evidence, 'people'));
  const outputs = Math.max(metricByKey(evidence, 'outputsB'), metricByKey(evidence, 'backbone'));
  const growth = Math.max(0, metricByKey(evidence, 'growthRate'));
  const conversion = Math.max(metricByKey(evidence, 'conversionB'), metricByKey(evidence, 'conversionA'));
  return {
    applications,
    outputs,
    growth,
    conversion,
    applicationsBar: Math.min(100, applications / 1.6),
    outputsBar: Math.min(100, outputs / 1.2),
    growthBar: Math.min(100, growth * 100),
    conversionBar: Math.min(100, conversion * 100),
  };
}

const severityClassMap = {
  high: 'severity-high',
  medium: 'severity-medium',
  opportunity: 'severity-opportunity',
};

function findingClass(item) {
  return severityClassMap[String(item?.severity || '').toLowerCase()] || 'severity-medium';
}

function statusText(item) {
  const severity = String(item?.severity || '').toLowerCase();
  if (severity === 'high') return '状态：高风险预警';
  if (severity === 'opportunity') return '状态：机会信号';
  return '状态：中风险观察';
}

const donutColors = ['#c85f51', '#d88a4c', '#d9b55b', '#8fbccf', '#7a93d1', '#8f78c8', '#89b9a4', '#9ccae1'];
const donutSegments = computed(() => {
  const rows = riskTypeBars.value;
  const total = rows.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
  const circumference = 2 * Math.PI * 110;
  let offset = 0;
  return rows.map((item, index) => {
    const value = Number(item.value || 0);
    const dash = (value / total) * circumference;
    const segment = {
      label: item.label,
      value,
      color: donutColors[index % donutColors.length],
      dasharray: `${dash.toFixed(2)} ${Math.max(0, circumference - dash).toFixed(2)}`,
      dashoffset: (-offset).toFixed(2),
    };
    offset += dash;
    return segment;
  });
});

const maxTopicValue = computed(() => Math.max(1, ...applicationBars.value.map((item) => Number(item.value || 0))));
const totalRisk = computed(() => riskTypeBars.value.reduce((sum, item) => sum + Number(item.value || 0), 0));
</script>

<template>
  <div class="macro-view">
    <div class="shell">
      <header class="topbar">
        <div class="brand">
          <span class="brand-badge">▲</span>
          <span>全省科技治理政策研判系统</span>
        </div>
        <div class="topbar-meta">
          <span>宏观治理研判</span>
          <span>{{ data.generatedAt || '' }}</span>
        </div>
      </header>

      <div class="page">
        <section class="hero">
          <div class="hero-grid">
            <div class="hero-left">
              <div class="hero-main-title">宏观治理研判简报</div>
              <div class="headline">{{ briefing.headline }}</div>
              <div class="summary-strip">当前结论：{{ briefing.headline }} 当前重点发现展示 {{ findings.length }} 条，已按风险与机会优先级排序。</div>
              <div class="hero-subtitle">统计数据</div>
              <div class="stats">
                <div v-for="card in cards" :key="card.label" class="stat">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value" :class="statValueClass(card.label)">{{ card.value }}</div>
                </div>
              </div>
            </div>
            <div class="hero-right">
              <div class="hero-actions">
                <div class="hero-actions-title">治理动作</div>
                <div class="hero-action-list">
                  <div v-for="(item, index) in actions" :key="`${index}-${item}`" class="hero-action-item">{{ item }}</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="bottom-grid">
          <section class="panel">
            <div class="panel-head">潜在发现分析</div>
            <div class="panel-body left-panel-body">
              <div class="bars">
                <div class="bar-box">
                  <div class="box-title">发现分布</div>
                  <div class="bars-chart-wrap">
                    <svg class="chart-svg bars-svg" viewBox="0 0 820 560" preserveAspectRatio="xMidYMid meet">
                      <line x1="36" y1="452" x2="804" y2="452" stroke="#cbd5e1" stroke-width="2.2" />
                      <line x1="36" y1="26" x2="36" y2="452" stroke="#cbd5e1" stroke-width="1.8" />
                      <line v-for="index in 4" :key="`grid-${index}`" x1="36" :y1="452 - (index * 426 / 4)" x2="804" :y2="452 - (index * 426 / 4)" stroke="#dbe4ee" stroke-width="1.6" stroke-dasharray="5 5" />
                      <g v-for="(item, index) in applicationBars" :key="item.label">
                        <rect
                          :x="52 + index * 94"
                          :y="452 - (Number(item.value || 0) / maxTopicValue) * 392"
                          width="62"
                          rx="4"
                          :height="(Number(item.value || 0) / maxTopicValue) * 392"
                          :fill="donutColors[index % donutColors.length]"
                        />
                        <text :x="83 + index * 94" :y="430 - (Number(item.value || 0) / maxTopicValue) * 392" text-anchor="middle" font-size="20" font-weight="900" fill="#0f172a">{{ item.value }}</text>
                        <text :x="83 + index * 94" y="508" text-anchor="middle" font-size="12" fill="#334155">{{ shortTopicName(item.label) }}</text>
                      </g>
                    </svg>
                  </div>
                </div>
                <div class="bar-box">
                  <div class="box-title">风险类型</div>
                  <div class="donut-layout">
                    <svg class="chart-svg donut-svg" viewBox="0 0 420 420" preserveAspectRatio="xMidYMid meet">
                      <circle cx="210" cy="210" r="128" fill="none" stroke="#e2e8f0" stroke-width="42" />
                      <circle
                        v-for="segment in donutSegments"
                        :key="segment.label"
                        cx="210"
                        cy="210"
                        r="128"
                        fill="none"
                        :stroke="segment.color"
                        stroke-width="42"
                        :stroke-dasharray="segment.dasharray"
                        :stroke-dashoffset="segment.dashoffset"
                        transform="rotate(-90 210 210)"
                      />
                      <text x="210" y="198" text-anchor="middle" font-size="46" font-weight="900" fill="#0f172a">{{ totalRisk }}</text>
                      <text x="210" y="236" text-anchor="middle" font-size="20" fill="#64748b">风险类型命中</text>
                    </svg>
                    <div class="donut-legend">
                      <div v-for="segment in donutSegments" :key="`legend-${segment.label}`" class="donut-legend-item">
                        <span class="donut-legend-dot" :style="{ background: segment.color }" />
                        <div class="donut-legend-text">
                          <div class="donut-legend-label">{{ segment.label }}</div>
                          <div class="donut-legend-value">{{ riskPercent(segment.value) }}%</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section class="panel" :class="{ 'focus-panel-empty': !selectedTopic }">
            <div class="panel-head panel-head-with-filter">
              <div class="panel-head-title">重点主题发现</div>
              <div class="focus-filter">
                <div class="focus-filter-label">选择主题</div>
                <select v-model="selectedTopic" class="topic-select">
                  <option value="">请选择主题</option>
                  <option v-for="topic in topicOptions" :key="topic" :value="topic">{{ topic }}</option>
                </select>
              </div>
              <div v-if="!selectedTopic" class="empty panel-head-empty">请选择一个主题查看对应的重点发现卡片</div>
            </div>
            <div v-if="selectedTopic" class="panel-body right-panel-body">
              <div class="finding-list">
                <div v-for="item in topicFindings" :key="`${item.topic}-${item.type}`" class="finding-item">
                  <div class="focus-card-top">
                    <div class="focus-kpi-label">{{ item.typeName }}</div>
                    <div class="focus-kpi-value">{{ metricPack(item).applications || metricPack(item).outputs }}</div>
                  </div>
                  <div class="finding-title">{{ shortTopicName(item.topic) }}</div>
                  <div class="finding-meta">{{ item.typeDescription }}</div>
                  <div class="focus-metric-strip">
                    <div class="focus-metric-grid">
                      <div class="focus-metric-item"><div class="focus-metric-track"><span class="focus-metric-fill focus-metric-fill-app" :style="{ width: `${metricPack(item).applicationsBar}%` }" /></div></div>
                      <div class="focus-metric-item"><div class="focus-metric-track"><span class="focus-metric-fill focus-metric-fill-out" :style="{ width: `${metricPack(item).outputsBar}%` }" /></div></div>
                      <div class="focus-metric-item"><div class="focus-metric-track"><span class="focus-metric-fill focus-metric-fill-growth" :style="{ width: `${metricPack(item).growthBar}%` }" /></div></div>
                      <div class="focus-metric-item"><div class="focus-metric-track"><span class="focus-metric-fill focus-metric-fill-conv" :style="{ width: `${metricPack(item).conversionBar}%` }" /></div></div>
                    </div>
                    <div class="focus-legend">
                      <div class="focus-legend-item"><div class="focus-legend-top">申报</div><div class="focus-legend-value">{{ metricPack(item).applications }}</div></div>
                      <div class="focus-legend-item"><div class="focus-legend-top">产出</div><div class="focus-legend-value">{{ metricPack(item).outputs }}</div></div>
                      <div class="focus-legend-item"><div class="focus-legend-top">增速</div><div class="focus-legend-value">{{ toPercent(metricPack(item).growth) }}</div></div>
                      <div class="focus-legend-item"><div class="focus-legend-top">转化率</div><div class="focus-legend-value">{{ toPercent(metricPack(item).conversion) }}</div></div>
                    </div>
                    <div class="focus-status-note" :class="findingClass(item)">{{ statusText(item) }}</div>
                  </div>
                  <div class="finding-suggestion">{{ item.suggestion }}</div>
                </div>
                <div v-if="!topicFindings.length" class="empty">该主题暂无重点发现</div>
              </div>
            </div>
          </section>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.macro-view { flex: 1; min-height: 0; overflow: hidden; background: linear-gradient(180deg, #dfeaf7 0%, #edf3fa 12%, #f4f7fb 100%); }
.shell { height: 100%; display: grid; grid-template-rows: 52px 1fr; overflow: hidden; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid #d5dfeb; background: linear-gradient(180deg, #edf4fb 0%, #dfeaf7 100%); box-shadow: inset 0 -1px 0 rgba(255,255,255,0.7); }
.brand { display: flex; align-items: center; gap: 12px; font-size: 18px; font-weight: 900; }
.brand-badge { width: 28px; height: 28px; border-radius: 8px; background: linear-gradient(135deg, #5aa0ff, #2f69d9); display: inline-flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; }
.topbar-meta { display: flex; align-items: center; gap: 14px; font-size: 13px; color: #475569; }
.page { width: min(100%, 1980px); height: calc(100vh - 52px); margin: 0 auto; padding: 12px 14px; display: grid; grid-template-rows: auto auto; gap: 12px; overflow: auto; align-content: start; }
.hero, .panel { border: 2px solid #b2764a; border-radius: 18px; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.98)); box-shadow: 0 10px 24px rgba(15,23,42,0.06); overflow: hidden; }
.focus-panel-empty { background: #f8fafc; }
.focus-panel-empty .panel-head {
  background: #f8fafc;
  border-bottom-color: transparent;
}
.focus-panel-empty .empty {
  background: #f8fafc;
}
.hero { padding: 14px 16px; position: relative; }
.hero::before { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 50% 0%, rgba(124, 45, 18, 0.08), transparent 32%), radial-gradient(circle at 50% 100%, rgba(90, 160, 255, 0.08), transparent 34%); pointer-events: none; }
.hero-grid { position: relative; z-index: 1; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(430px, 1fr); gap: 18px; align-items: stretch; }
.hero-main-title { font-size: 24px; font-weight: 900; color: #111827; }
.headline { margin: 6px 0 0; font-size: 18px; line-height: 1.45; color: #9a5831; font-weight: 900; }
.summary-strip { margin-top: 4px; color: #334155; font-size: 13px; line-height: 1.65; }
.hero-subtitle { margin-top: 6px; font-size: 12px; color: #475569; }
.stats { margin-top: 10px; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.stat { padding: 10px 12px; border-radius: 12px; background: #fff; border: 1px solid #eadfce; box-shadow: 0 8px 18px rgba(56,38,17,0.06); min-height: 78px; }
.stat-label { font-size: 12px; color: #64748b; }
.stat-value { margin-top: 6px; font-size: 38px; font-weight: 900; }
.stat-value-high { color: #b42318; }
.stat-value-medium { color: #b7791f; }
.hero-actions { background: rgba(255,255,255,0.78); border: 1px solid #dfe7f1; border-radius: 14px; padding: 10px; box-shadow: 0 8px 18px rgba(15,23,42,0.06); height: 100%; display: grid; grid-template-rows: auto 1fr; }
.hero-actions-title { font-size: 20px; font-weight: 900; margin-bottom: 10px; color: #1f2937; }
.hero-action-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-content: start; }
.hero-action-item { padding: 10px 12px; background: rgba(255,255,255,0.96); border: 1px solid #eadfce; border-radius: 10px; box-shadow: 0 6px 12px rgba(56,38,17,0.05); font-size: 13px; line-height: 1.65; }
.bottom-grid { min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: stretch; }
.bottom-grid > .panel { min-height: 420px; height: auto; display: grid; grid-template-rows: auto auto; }
.panel-head { padding: 8px 12px; font-size: 15px; font-weight: 900; border-bottom: 1px solid #e4e9f0; background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,248,252,0.95)); }
.panel-head-with-filter { display: grid; gap: 10px; align-content: start; }
.panel-head-title { font-size: 15px; font-weight: 900; color: #111827; }
.panel-head-empty { margin-top: 0; }
.panel-body { padding: 10px 12px 16px; min-height: 0; overflow: visible; }
.left-panel-body, .right-panel-body { min-height: 0; display: grid; gap: 10px; overflow: visible; align-content: start; }
.right-panel-body { display: flex; flex-direction: column; justify-content: flex-start; align-items: stretch; padding-right: 6px; overflow: auto; }
.bars { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; align-items: stretch; }
.bar-box { border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px; background: #f8fafc; display: grid; grid-template-rows: auto auto; align-content: start; }
.left-panel-body .bar-box { padding: 14px 16px; }
.box-title { font-size: 16px; font-weight: 900; margin-bottom: 8px; }
.left-panel-body .box-title { font-size: 19px; margin-bottom: 8px; }
.chart-svg { width: 100%; display: block; }
.bars-chart-wrap { display: grid; grid-template-rows: auto auto; gap: 8px; height: auto; align-content: start; }
.bars-svg { height: 300px; }
.donut-layout { height: 100%; display: grid; grid-template-columns: minmax(160px, 0.9fr) minmax(140px, 1.1fr); align-items: center; gap: 10px; }
.donut-svg { height: 250px; }
.donut-legend { display: grid; gap: 8px; align-content: center; }
.donut-legend-item { display: grid; grid-template-columns: 12px minmax(0, 1fr); gap: 8px; align-items: start; }
.donut-legend-dot { width: 12px; height: 12px; border-radius: 999px; margin-top: 4px; }
.donut-legend-text { min-width: 0; }
.donut-legend-label { font-size: 12px; font-weight: 800; color: #334155; line-height: 1.25; word-break: break-word; }
.donut-legend-value { margin-top: 2px; font-size: 11px; font-weight: 700; color: #64748b; }
.focus-filter { display: flex; align-items: center; gap: 10px; }
.focus-filter-label { font-size: 12px; font-weight: 800; color: #7c2d12; white-space: nowrap; }
.topic-select { width: 100%; height: 34px; border-radius: 10px; border: 1px solid #e4d4c0; padding: 0 12px; font-size: 12px; color: #334155; background: #fff; }
.finding-list { margin-top: 2px; min-height: 0; padding-right: 0; display: grid; gap: 8px; align-content: start; overflow: auto; flex: 1 1 auto; }
.finding-item { border: 1px solid #e7dccf; border-radius: 12px; background: linear-gradient(180deg, #ffffff, #fbfcfe); padding: 10px; box-shadow: 0 8px 16px rgba(56,38,17,0.07); min-height: 148px; }
.focus-card-top { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.focus-kpi-label { font-size: 12px; font-weight: 800; color: #7c2d12; }
.focus-kpi-value { font-size: 20px; font-weight: 900; color: #1f2937; line-height: 1; }
.finding-title { margin-top: 4px; font-size: 13px; font-weight: 800; color: #0f172a; }
.finding-meta { margin-top: 1px; font-size: 11px; color: #64748b; }
.focus-metric-strip { margin-top: 8px; display: grid; gap: 8px; }
.focus-metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.focus-metric-track { width: 100%; height: 12px; border-radius: 999px; background: #e8edf4; overflow: hidden; }
.focus-metric-fill { height: 100%; display: block; border-radius: 999px; }
.focus-metric-fill-app { background: linear-gradient(90deg, #b75c2c, #c97a43); }
.focus-metric-fill-out { background: linear-gradient(90deg, #d58a4d, #e4a96d); }
.focus-metric-fill-growth { background: linear-gradient(90deg, #e3b85a, #edd180); }
.focus-metric-fill-conv { background: linear-gradient(90deg, #9cc5df, #b6d8eb); }
.focus-legend { margin-top: 4px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.focus-legend-item { text-align: center; }
.focus-legend-top { font-size: 10px; font-weight: 800; color: #7c2d12; line-height: 1.2; }
.focus-legend-value { margin-top: 2px; font-size: 12px; font-weight: 800; color: #334155; line-height: 1.1; }
.focus-status-note { margin-top: 1px; font-size: 11px; font-weight: 700; color: #64748b; text-align: right; }
.finding-suggestion { margin-top: 4px; font-size: 11px; line-height: 1.55; color: #334155; }
.empty { margin-top: 6px; border: 1px dashed #d7dfeb; border-radius: 10px; background: #f8fafc; padding: 14px; text-align: center; color: #64748b; font-size: 12px; }
.severity-high { color: #b91c1c; font-weight: 800; }
.severity-medium { color: #b45309; font-weight: 800; }
.severity-opportunity { color: #15803d; font-weight: 800; }
@media (max-width: 1080px) {
  .hero-grid, .bottom-grid, .bars { grid-template-columns: 1fr; }
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .hero-action-list { grid-template-columns: 1fr; }
  .donut-layout { grid-template-columns: 1fr; }
  .donut-svg { height: 280px; }
}
@media (max-width: 720px) {
  .page { padding: 8px; }
  .stats { grid-template-columns: 1fr; }
}
</style>
