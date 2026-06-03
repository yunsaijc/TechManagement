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
const leadershipNarrative = computed(() => normalizedReport.value?.leadershipNarrative || {});
const causalChainHints = computed(() => (Array.isArray(normalizedReport.value?.causalChainHints)
  ? normalizedReport.value.causalChainHints
  : []));
const policySimulationPresets = computed(() => (Array.isArray(normalizedReport.value?.policySimulationPresets)
  ? normalizedReport.value.policySimulationPresets
  : []));
const policyParameterModels = computed(() => (Array.isArray(normalizedReport.value?.policyParameterModels)
  ? normalizedReport.value.policyParameterModels
  : []));
const policyScenarioComparison = computed(() => (Array.isArray(normalizedReport.value?.policyScenarioComparison)
  ? normalizedReport.value.policyScenarioComparison
  : []));
const counterfactualCards = computed(() => (Array.isArray(normalizedReport.value?.counterfactualCards)
  ? normalizedReport.value.counterfactualCards
  : []));
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

const step5Generation = computed(() => normalizedReport.value?.raw?.step5?.generation || {});
const step5Answer = computed(() => String(step5Generation.value?.answer || '').trim());
const step5KeyFindings = computed(() => {
  const arr = step5Generation.value?.keyFindings;
  return Array.isArray(arr) ? arr.filter((item) => String(item || '').trim()) : [];
});
const step5AnswerPreview = computed(() => {
  const txt = step5Answer.value;
  if (!txt) return '';
  return txt.length > 160 ? `${txt.slice(0, 160)}...` : txt;
});
const step5AnswerLong = computed(() => step5Answer.value.length > 160);
const step2Meta = computed(() => normalizedReport.value?.raw?.step2?.meta || {});
const step2Communities = computed(() => normalizedReport.value?.raw?.step2?.communities || {});
const step2WindowACommunities = computed(() => Array.isArray(step2Communities.value?.windowA) ? step2Communities.value.windowA : []);
const step2WindowBCommunities = computed(() => Array.isArray(step2Communities.value?.windowB) ? step2Communities.value.windowB : []);

function pickCommunityKeyword(item) {
  if (!item || typeof item !== 'object') return '';
  if (Array.isArray(item.keywordSet) && item.keywordSet.length) return String(item.keywordSet[0] || '');
  if (Array.isArray(item.topKeywords) && item.topKeywords.length) return String(item.topKeywords[0] || '');
  return '';
}

const communityKeywordMap = computed(() => {
  const map = new Map();
  step2WindowACommunities.value.forEach((item) => {
    const id = Number(item?.communityId);
    if (!Number.isFinite(id)) return;
    map.set(`A-${id}`, pickCommunityKeyword(item));
    map.set(`A-C${id}`, pickCommunityKeyword(item));
  });
  step2WindowBCommunities.value.forEach((item) => {
    const id = Number(item?.communityId);
    if (!Number.isFinite(id)) return;
    map.set(`B-${id}`, pickCommunityKeyword(item));
    map.set(`B-C${id}`, pickCommunityKeyword(item));
  });
  return map;
});

const GROUP_LABEL_MAP = {
  risk: '风险',
  opportunity: '机会',
  talent: '人才',
  conversion: '转化',
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

const SANKEY_MAX_SOURCES = 10;
const SANKEY_TARGETS_PER_SOURCE = 4;
const SANKEY_MAX_LINKS = 48;

function localizeSankeyLabel(label) {
  const text = String(label || '');
  const aMatch = text.match(/^A-C(\d+)$/);
  if (aMatch) {
    const keyword = String(communityKeywordMap.value.get(text) || communityKeywordMap.value.get(`A-${aMatch[1]}`) || '').trim();
    const meta = `${windowLabels.value.a}主题簇${aMatch[1]}`;
    return keyword ? `${keyword}（${meta}）` : meta;
  }
  const bMatch = text.match(/^B-C(\d+)$/);
  if (bMatch) {
    const keyword = String(communityKeywordMap.value.get(text) || communityKeywordMap.value.get(`B-${bMatch[1]}`) || '').trim();
    const meta = `${windowLabels.value.b}主题簇${bMatch[1]}`;
    return keyword ? `${keyword}（${meta}）` : meta;
  }
  return text;
}

function extractCommunityId(ref) {
  const text = String(ref || '');
  const a = text.match(/^A-(\d+)$/);
  if (a) return a[1];
  const b = text.match(/^B-(\d+)$/);
  if (b) return b[1];
  const ac = text.match(/^A-C(\d+)$/);
  if (ac) return ac[1];
  const bc = text.match(/^B-C(\d+)$/);
  if (bc) return bc[1];
  return text;
}

function localizeCommunityRef(ref) {
  const text = String(ref || '');
  const a = text.match(/^A-(\d+)$/);
  if (a) {
    const keyword = String(communityKeywordMap.value.get(text) || communityKeywordMap.value.get(`A-C${a[1]}`) || '').trim();
    const meta = `${windowLabels.value.a}主题簇${a[1]}`;
    return keyword ? `${keyword}（${meta}）` : meta;
  }
  const b = text.match(/^B-(\d+)$/);
  if (b) {
    const keyword = String(communityKeywordMap.value.get(text) || communityKeywordMap.value.get(`B-C${b[1]}`) || '').trim();
    const meta = `${windowLabels.value.b}主题簇${b[1]}`;
    return keyword ? `${keyword}（${meta}）` : meta;
  }
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
  const baseRows = links.slice(0, 8).map((item) => {
    const v = Number(item.value || 0);
    const raw = Number(item.rawOverlap ?? item.raw_overlap ?? 0);
    const displayValue = v > 0 ? v : raw;
    return {
      base: `${localizeCommunityRef(item.source)} → ${localizeCommunityRef(item.target)}`,
      pairKey: `${item.source ?? ''}|${item.target ?? ''}`,
      value: displayValue,
      rawOverlap: raw,
      jaccard: Number(item.jaccard || 0),
    };
  });
  const baseCount = {};
  baseRows.forEach((r) => {
    baseCount[r.base] = (baseCount[r.base] || 0) + 1;
  });
  const seen = {};
  return baseRows.map((r) => {
    seen[r.base] = (seen[r.base] || 0) + 1;
    const dup = baseCount[r.base] > 1;
    const label = dup ? `${r.base} ·路径${seen[r.base]}` : r.base;
    return {
      label,
      value: r.value,
      rawOverlap: r.rawOverlap,
      jaccard: r.jaccard,
    };
  });
});

const activeFocusKeywords = computed(() => {
  const fromFuture = Array.isArray(futureJudgement.value?.focusKeywords) ? futureJudgement.value.focusKeywords : [];
  const fromNarr = Array.isArray(leadershipNarrative.value?.focusKeywords) ? leadershipNarrative.value.focusKeywords : [];
  const merged = [...fromFuture, ...fromNarr]
    .map((x) => String(x || '').trim())
    .filter(Boolean);
  return [...new Set(merged)].slice(0, 8);
});

const TYPE_BUCKET_MAP = {
  low_conversion_after_growth: '高增低转',
  conversion_efficiency_gap: '高增低转',
  persistent_low_conversion: '高增低转',
  output_decline_with_growth: '高增低转',
  application_growth_spike: '热点激增',
  emerging_topic_opportunity: '新兴机会',
  talent_structure_gap: '人才断层',
  senior_talent_shortage: '人才断层',
  backbone_absent_risk: '人才断层',
  collaboration_network_weak: '协同薄弱',
  senior_backbone_imbalance: '协同薄弱',
};

const TYPE_SCORE_MAP = {
  low_conversion_after_growth: 9,
  conversion_efficiency_gap: 8,
  persistent_low_conversion: 7,
  output_decline_with_growth: 7,
  application_growth_spike: 6,
  talent_structure_gap: 8,
  senior_talent_shortage: 7,
  backbone_absent_risk: 7,
  collaboration_network_weak: 6,
  senior_backbone_imbalance: 6,
  emerging_topic_opportunity: 5,
};

function keywordHitCount(text, keywords) {
  const t = String(text || '').toLowerCase();
  if (!t || !keywords.length) return 0;
  let hit = 0;
  keywords.forEach((kw) => {
    const k = String(kw || '').toLowerCase();
    if (k && t.includes(k)) hit += 1;
  });
  return hit;
}

const questionAnchoredMigrationData = computed(() => {
  const keywords = activeFocusKeywords.value;
  const links = migrationFlowData.value || [];
  const ranked = links.map((item) => {
    const hit = keywordHitCount(item.label, keywords);
    const base = Number(item.value || 0);
    const sim = Number(item.jaccard || 0);
    return {
      ...item,
      hit,
      score: base * (1 + sim) + hit * 2,
    };
  });

  const matched = ranked.filter((x) => x.hit > 0).sort((a, b) => b.score - a.score);
  const fallback = ranked.sort((a, b) => b.score - a.score);
  const picked = (matched.length ? matched : fallback).slice(0, 8);

  return picked.map((item) => ({
    label: item.label,
    value: Number(item.score.toFixed(2)),
    rawValue: item.value,
    jaccard: item.jaccard,
    keywordHits: item.hit,
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
  const topics = Array.isArray(priorityTopics.value) ? priorityTopics.value : [];
  const bucketCount = new Map();

  topics.forEach((item) => {
    const type = String(item?.type || 'unknown');
    const bucket = TYPE_BUCKET_MAP[type] || '其他风险';
    const weight = Number(TYPE_SCORE_MAP[type] || 4);
    bucketCount.set(bucket, Number(bucketCount.get(bucket) || 0) + weight);
  });

  if (!bucketCount.size) {
    const entries = Object.entries(groupCounts.value || {});
    const xAxis = entries.map(([k]) => localizeGroupKey(k));
    const values = entries.map(([, v]) => Number(v || 0));
    const points = values.map((v, idx) => [xAxis[idx], v]);
    return { xAxis, points, max: Math.max(1, ...values), source: 'fallback' };
  }

  const entries = [...bucketCount.entries()].sort((a, b) => b[1] - a[1]);
  const xAxis = entries.map(([label]) => label);
  const values = entries.map(([, score]) => Number(score || 0));
  const points = values.map((v, idx) => [xAxis[idx], v]);
  return { xAxis, points, max: Math.max(1, ...values), source: 'anchored' };
});

const realDataOverview = computed(() => {
  const probe = Array.isArray(step2Meta.value?.probeWindows) ? step2Meta.value.probeWindows : [];
  const a = probe[0] || {};
  const b = probe[1] || {};
  const aWindow = a.window || {};
  const bWindow = b.window || {};
  return {
    analysisMode: String(step2Meta.value?.analysisDescription || step2Meta.value?.analysisMode || '-'),
    aLabel: Number.isFinite(Number(aWindow.start)) && Number.isFinite(Number(aWindow.end))
      ? `${aWindow.start}-${aWindow.end}`
      : '-',
    bLabel: Number.isFinite(Number(bWindow.start)) && Number.isFinite(Number(bWindow.end))
      ? `${bWindow.start}-${bWindow.end}`
      : '-',
    aNodes: Number(a.nodeCount || 0),
    aRels: Number(a.relationshipCount || 0),
    bNodes: Number(b.nodeCount || 0),
    bRels: Number(b.relationshipCount || 0),
  };
});

const migrationRawRows = computed(() => {
  const links = Array.isArray(migrationTopLinks.value) ? migrationTopLinks.value : [];
  return links.slice(0, 8).map((item) => ({
    source: String(item.source || '-'),
    target: String(item.target || '-'),
    sourceId: extractCommunityId(item.source),
    targetId: extractCommunityId(item.target),
    sourceLabel: localizeCommunityRef(item.source),
    targetLabel: localizeCommunityRef(item.target),
    value: Number(item.value || 0),
    jaccard: Number(item.jaccard || 0),
  }));
});

const riskRawRows = computed(() => {
  const entries = Object.entries(groupCounts.value || {});
  return entries.map(([key, value]) => ({
    key,
    label: localizeGroupKey(key),
    value: Number(value || 0),
  }));
});

const keySignals = computed(() => Array.isArray(futureJudgement.value?.signals) ? futureJudgement.value.signals : []);
const governanceRecommendations = computed(() => Array.isArray(futureJudgement.value?.recommendations) ? futureJudgement.value.recommendations : []);
const topKeySignals = computed(() => keySignals.value.slice(0, 3));
const topRecommendations = computed(() => governanceRecommendations.value.slice(0, 3));
const moreKeySignals = computed(() => keySignals.value.slice(3));
const moreRecommendations = computed(() => governanceRecommendations.value.slice(3));

const capabilityCards = computed(() => {
  const riskPct = Number.isFinite(Number(futureJudgement.value?.riskIndex))
    ? `${Math.round(Number(futureJudgement.value.riskIndex) * 100)}%`
    : '-';
  return [
    {
      title: '热点迁移图谱',
      desc: '帮助您快速看清：哪些方向在升温、哪些方向出现高增低转风险。',
      value: `${migrationTopLinks.value.length}`,
      unit: '条迁移流',
    },
    {
      title: '趋势预判预警',
      desc: '帮助您判断下一年度风险级别，并提前锁定需干预方向。',
      value: `${localizeRiskLevel(futureJudgement.value?.riskLevel)}`,
      unit: `风险 ${riskPct}`,
    },
    {
      title: '因果链推断',
      desc: '把“为什么会这样”讲清楚，便于您在会上解释决策依据。',
      value: `${futureManagementSignals.value.length + futureKnowledgeSignals.value.length + futureBridgeSignals.value.length}`,
      unit: '条因果证据',
    },
    {
      title: '政策仿真优化',
      desc: '给出可执行的政策组合建议，辅助您做年度指南取舍。',
      value: `${governanceRecommendations.value.length}`,
      unit: '条治理建议',
    },
  ];
});

const focusHeadline = computed(() => {
  const first = topKeySignals.value[0];
  if (first && String(first).trim()) return String(first).trim();
  return leadershipBrief.value?.headline || '暂无重点趋势结论';
});

const leadershipFutureSummary = computed(() => (
  step5AnswerPreview.value || focusHeadline.value || '暂无将来时研判摘要'
));

function buildSankeyOption() {
  const flow = questionAnchoredMigrationData.value;
  const data = flow.map((item) => ({
    name: item.label,
    value: item.value,
    rawOverlap: item.rawValue,
    jaccard: item.jaccard,
    keywordHits: item.keywordHits || 0,
  }));
  if (!data.length) return null;

  const maxValue = Math.max(1, ...data.map((item) => item.value));
  const kws = activeFocusKeywords.value;
  const kwText = kws.length ? `问题关切词：${kws.slice(0, 4).join('、')}` : '未识别到明确关切词，按迁移强度展示';
  const subHint = flow.length >= 8
    ? `${kwText}；已筛选最相关的 8 条迁移路径`
    : `${kwText}；已筛选 ${flow.length} 条迁移路径`;

  return {
    title: {
      text: `问题相关热点迁移图（${windowLabels.value.a}到${windowLabels.value.b}）`,
      subtext: subHint,
      left: 16,
      top: 10,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#0f172a' },
      subtextStyle: { fontSize: 11, color: '#64748b' },
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params) => {
        const raw = params.data?.rawOverlap;
        const rawLine = raw != null && Number(raw) > 0 && Number(raw) !== Number(params.value || 0)
          ? `<br/>关键词重合：${raw}`
          : '';
        const hitLine = Number(params.data?.keywordHits || 0) > 0 ? `<br/>关键词命中：${params.data?.keywordHits}` : '';
        return `${params.name}<br/>综合优先级：${params.value}${rawLine}<br/>相似度：${Number(params.data?.jaccard || 0).toFixed(3)}${hitLine}`;
      },
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
      name: '优先级',
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
  const title = data.source === 'anchored' ? '问题相关风险结构图' : '风险分组气泡图';
  const subtext = data.source === 'anchored'
    ? '基于当前问题命中的重点主题，展示需优先治理的风险结构'
    : '用于快速对比各类风险的集中程度，帮助您明确先后治理顺序';
  return {
    title: {
      text: title,
      subtext,
      left: 16,
      top: 6,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#0f172a' },
      subtextStyle: { fontSize: 11, color: '#64748b' },
    },
    tooltip: {
      position: 'top',
      formatter: (params) => `${params.value[0]}：${params.value[1]}`,
    },
    grid: { top: 72, left: 48, right: 24, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.xAxis,
      axisLabel: { color: '#334155', fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: {
      type: 'value',
      name: '发现条数',
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

    <section class="panel-block report-hero">
      <div class="section-header">
        <h3 class="panel-title">领导沙盘推演与趋势预判</h3>
        <p class="panel-copy">围绕您的问题，直接给出“下一步先做什么、风险在哪里、为什么这样判断”。</p>
      </div>
      <div class="hero-main">{{ leadershipFutureSummary }}</div>
      <div class="hero-meta-grid">
        <div class="hero-meta-card">
          <div class="hero-meta-label">当前风险等级</div>
          <div class="hero-meta-value" :class="'risk-' + (futureJudgement.riskLevel || 'low')">{{ localizeRiskLevel(futureJudgement.riskLevel) }}</div>
        </div>
        <div class="hero-meta-card">
          <div class="hero-meta-label">风险指数</div>
          <div class="hero-meta-value">{{ Number.isFinite(Number(futureJudgement.riskIndex)) ? `${Math.round(Number(futureJudgement.riskIndex) * 100)}%` : '-' }}</div>
        </div>
        <div class="hero-meta-card">
          <div class="hero-meta-label">重点主题</div>
          <div class="hero-meta-value">{{ priorityTopics.length || 0 }} 个</div>
        </div>
        <div class="hero-meta-card">
          <div class="hero-meta-label">治理建议</div>
          <div class="hero-meta-value">{{ governanceRecommendations.length || 0 }} 条</div>
        </div>
      </div>
    </section>

    <section class="panel-block panel-block--focus">
      <div class="section-header">
        <h3 class="panel-title">一、决策结论（先看这个）</h3>
        <p class="panel-copy">您可先确认三件事：先管什么、先做什么、关注什么指标。</p>
      </div>
      <div class="decision-grid">
        <article class="decision-card">
          <h4 class="decision-title">先做的三项行动</h4>
          <ul class="decision-list" v-if="topRecommendations.length">
            <li v-for="(item, idx) in topRecommendations.slice(0, 3)" :key="`top_act_${idx}`">{{ item }}</li>
          </ul>
          <p v-else class="decision-empty">暂无行动建议</p>
        </article>
        <article class="decision-card">
          <h4 class="decision-title">重点风险信号</h4>
          <ul class="decision-list" v-if="topKeySignals.length">
            <li v-for="(signal, idx) in topKeySignals.slice(0, 3)" :key="`top_risk_${idx}`">{{ signal }}</li>
          </ul>
          <p v-else class="decision-empty">暂无风险信号</p>
        </article>
      </div>
    </section>

    <section class="panel-block">
      <div class="section-header">
        <h3 class="panel-title">二、趋势证据（为什么这样判断）</h3>
        <div class="panel-copy">通过热点迁移与风险分布，判断哪些方向需要收紧、哪些方向可以加力。</div>
      </div>

      <div class="alert-list" v-if="keySignals.length > 3">
        <div class="alert-item" v-for="(signal, idx) in keySignals.slice(3, 6)" :key="'sig_'+idx">
          <div class="alert-icon">⚠️</div>
          <div class="alert-text">{{ signal }}</div>
        </div>
      </div>

      <div class="chart-grid">
        <div class="chart-shell">
          <div class="chart-title">全省科研热点迁移图</div>
          <div ref="sankeyEl" class="chart-canvas" />
        </div>
        <div class="chart-shell">
          <div class="chart-title">主题风险分布</div>
          <div ref="heatmapEl" class="chart-canvas" />
        </div>
      </div>
    </section>

    <section class="panel-block" v-if="causalChainHints.length || policySimulationPresets.length">
      <div class="section-header">
        <h3 class="panel-title">三、因果推断与政策仿真（怎么调）</h3>
        <div class="panel-copy">先看可执行政策，再看因果链支撑，阅读更顺畅。</div>
      </div>
      <div class="policy-strip" v-if="policySimulationPresets.length">
        <h4 class="hint-col-title">政策仿真建议</h4>
        <div class="policy-grid">
          <article v-for="(p, i) in policySimulationPresets" :key="'ps_'+i" class="hint-card hint-card--preset">
            <div class="hint-topic">{{ p.title }}</div>
            <div class="hint-chain"><strong>建议动作：</strong>{{ p.intervention }}</div>
            <div class="hint-chain"><strong>预期变化：</strong>{{ p.expectedDirection }}</div>
            <div class="hint-disclaimer">{{ p.caveats }}</div>
          </article>
        </div>
      </div>
      <div class="causal-board" v-if="causalChainHints.length">
        <h4 class="hint-col-title">关键因果链</h4>
        <div class="causal-grid">
          <article v-for="(h, i) in causalChainHints" :key="'ch_'+i" class="hint-card hint-card--causal">
            <div class="hint-topic">{{ h.topic }}</div>
            <div class="hint-chain">{{ h.chainHypothesis }}</div>
            <div class="hint-disclaimer">{{ h.disclaimer }}</div>
          </article>
        </div>
      </div>
      <div class="evidence-box" v-if="futureManagementSignals.length || futureKnowledgeSignals.length || futureBridgeSignals.length">
        <div class="evidence-title">证据要点</div>
        <ul class="custom-list evidence-list">
          <li v-for="(item, idx) in [...futureManagementSignals, ...futureKnowledgeSignals, ...futureBridgeSignals].slice(0, 5)" :key="'evidence_'+idx">
            {{ item }}
          </li>
        </ul>
      </div>
    </section>

    <section class="panel-block" v-if="policyParameterModels.length || policyScenarioComparison.length || counterfactualCards.length">
      <div class="section-header">
        <h3 class="panel-title">三点五、政策参数与反事实对比</h3>
        <div class="panel-copy">把政策方案转成可计算参数，并给出三档组合对比，支撑“怎么调、调多少”的量化讨论。</div>
      </div>

      <div class="param-grid" v-if="policyParameterModels.length">
        <article class="param-card" v-for="(m, idx) in policyParameterModels" :key="'pm_'+idx">
          <div class="param-title">{{ m.title || `参数模型${idx + 1}` }}</div>
          <div class="param-row"><span class="param-k">主体</span><span class="param-v">{{ m.subject || '-' }}</span></div>
          <div class="param-row"><span class="param-k">客体</span><span class="param-v">{{ m.object || '-' }}</span></div>
          <div class="param-row"><span class="param-k">工具</span><span class="param-v">{{ m.tool || '-' }}</span></div>
          <div class="param-row"><span class="param-k">目标</span><span class="param-v">{{ m.target || '-' }}</span></div>
        </article>
      </div>

      <div class="scenario-table-wrap" v-if="policyScenarioComparison.length">
        <table class="scenario-table">
          <thead>
            <tr>
              <th>方案</th>
              <th>风险变化</th>
              <th>转化变化</th>
              <th>人才断层变化</th>
              <th>实施后风险指数</th>
              <th>可信度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, idx) in policyScenarioComparison" :key="'sc_'+idx">
              <td>{{ s.name || s.id || '-' }}</td>
              <td>{{ s.riskDeltaPct }}%</td>
              <td>+{{ s.conversionDeltaPct }}%</td>
              <td>{{ s.talentGapDeltaPct }}%</td>
              <td>{{ s.postRiskIndex }}</td>
              <td>{{ Math.round(Number(s.confidence || 0) * 100) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="counter-grid" v-if="counterfactualCards.length">
        <article class="counter-card" v-for="(c, idx) in counterfactualCards" :key="'cf_'+idx">
          <div class="counter-title">{{ c.title || `反事实结果${idx + 1}` }}</div>
          <div class="counter-beforeafter">{{ c.beforeAfter }}</div>
          <ul class="counter-effects">
            <li v-for="(e, i) in (c.effects || []).slice(0, 3)" :key="'cfe_'+idx+'_'+i">{{ e }}</li>
          </ul>
          <div class="counter-confidence">可信度：{{ Math.round(Number(c.confidence || 0) * 100) }}%</div>
        </article>
      </div>
    </section>

    <section class="panel-block narrative-block" v-if="leadershipNarrative.mergedBullets?.length || leadershipNarrative.focusKeywords?.length">
      <div class="section-header">
        <h3 class="panel-title">四、问题锚定说明</h3>
        <p class="panel-intro">用于汇报材料引用，展示问题解释逻辑和下一年度动作清单。</p>
      </div>
      <div class="narrative-content">
        <div v-if="leadershipNarrative.focusKeywords?.length" class="kw-row">
          <span class="kw-label">关切词</span>
          <span v-for="(k, i) in leadershipNarrative.focusKeywords" :key="'kw_'+i" class="kw-pill">{{ k }}</span>
        </div>
        <div v-if="leadershipNarrative.headline" class="narr-headline-card">
          <div class="narr-headline-label">本段结论</div>
          <div class="narr-headline">{{ leadershipNarrative.headline }}</div>
        </div>
        <div class="narrative-split">
          <div class="narrative-panel" v-if="leadershipNarrative.mergedBullets?.length">
            <div class="narrative-panel-title">研判要点</div>
            <ul class="narr-list narr-list--insight">
              <li v-for="(b, i) in leadershipNarrative.mergedBullets" :key="'nb_'+i">{{ b }}</li>
            </ul>
          </div>
          <div class="narrative-panel next-actions" v-if="leadershipNarrative.nextYearActions?.length">
            <div class="na-title">下一年度动作建议</div>
            <ul class="narr-list narr-list--action">
              <li v-for="(a, i) in leadershipNarrative.nextYearActions" :key="'na_'+i">{{ a }}</li>
            </ul>
          </div>
        </div>
        <p v-if="leadershipNarrative.maturityNote" class="maturity-note">{{ leadershipNarrative.maturityNote }}</p>
      </div>
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
  gap: 22px;
  width: 100%;
  max-width: 1260px;
  margin: 0 auto;
  padding: 4px 14px 28px;
  font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #0f172a;
}

.view-meta {
  display: none;
}

.future-capability-block {
  border-color: #bfdbfe;
  box-shadow: 0 6px 24px rgba(37, 99, 235, 0.1);
}

.report-hero {
  border-color: #bfdbfe;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.hero-main {
  font-size: 18px;
  line-height: 1.75;
  font-weight: 700;
  color: #0f172a;
  background: #ffffff;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  padding: 14px 16px;
}

.hero-meta-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.hero-meta-card {
  border: 1px solid #dbe5f0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 12px 12px 10px;
}

.hero-meta-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 700;
}

.hero-meta-value {
  margin-top: 6px;
  font-size: 21px;
  line-height: 1.2;
  color: #0f172a;
  font-weight: 850;
}

.future-summary-shell {
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: linear-gradient(180deg, #f0f9ff 0%, #f8fafc 100%);
  padding: 16px 18px;
}

.future-summary-label {
  font-size: 12px;
  font-weight: 700;
  color: #1d4ed8;
  margin-bottom: 6px;
}

.future-summary-text {
  font-size: 16px;
  line-height: 1.72;
  color: #0f172a;
  font-weight: 650;
}

.capability-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.capability-card {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  background: #ffffff;
  min-height: 124px;
}

.capability-title {
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
}

.capability-desc {
  margin: 8px 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
  min-height: 42px;
}

.capability-kpi {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.capability-value {
  font-size: 20px;
  font-weight: 850;
  color: #1d4ed8;
}

.capability-unit {
  font-size: 12px;
  color: #475569;
}

/* 卡片基础样式 */
.panel-block {
  background: #ffffff;
  border-radius: 14px;
  padding: 24px 28px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
  border: 1px solid #e8eef4;
}

.panel-block--focus {
  border-color: #bfdbfe;
  box-shadow: 0 4px 20px rgba(37, 99, 235, 0.07);
}

.section-header {
  margin-bottom: 18px;
}

.panel-title {
  margin: 0;
  color: #0f172a;
  font-size: 19px;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title::before {
  content: "";
  display: block;
  width: 4px;
  height: 16px;
  background: #3b82f6;
  border-radius: 4px;
}

.panel-copy {
  margin-top: 8px;
  font-size: 14px;
  color: #64748b;
  line-height: 1.65;
}

.panel-copy--tight {
  max-width: 52rem;
}

.panel-intro {
  margin: 8px 0 0;
  max-width: 52rem;
  font-size: 14px;
  line-height: 1.65;
  color: #64748b;
}

/* 结论速览模块 */
.core-conclusion {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 18px 22px;
  margin-bottom: 18px;
  border-left: 3px solid #3b82f6;
}

.focus-grid {
  margin: 0 0 16px;
  display: grid;
  grid-template-columns: 1.2fr 1.2fr 0.9fr;
  gap: 12px;
}

.focus-card {
  border: 1px solid #dbe5f0;
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 14px 12px;
}

.focus-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 700;
}

.focus-text {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.6;
  color: #0f172a;
  font-weight: 600;
}

.focus-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 850;
  color: #0f172a;
}

.decision-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.decision-card {
  border: 1px solid #dbe5f0;
  border-radius: 12px;
  background: #f8fafc;
  padding: 14px 16px;
}

.decision-title {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
}

.decision-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.decision-list li {
  font-size: 14px;
  line-height: 1.6;
  color: #334155;
}

.decision-empty {
  margin: 0;
  font-size: 14px;
  color: #94a3b8;
}

.cc-label {
  font-size: 15px;
  font-weight: 700;
  color: #1e40af;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.cc-text {
  font-size: 17px;
  line-height: 1.75;
  color: #1e293b;
  white-space: pre-wrap;
  font-weight: 500;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  border-top: 1px solid #e2e8f0;
  padding-top: 20px;
}

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e8eef4;
}

.kpi-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 600;
}

.kpi-value {
  font-size: 26px;
  font-weight: 800;
  color: #0f172a;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.kpi-value.risk-high { color: #dc2626; }
.kpi-value.risk-medium { color: #f59e0b; }
.kpi-value.risk-low { color: #10b981; }

.kpi-unit {
  font-size: 13px;
  color: #94a3b8;
  font-weight: 500;
}

/* 预警与趋势模块 */
.alert-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.alert-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: #fef2f2;
  border-left: 4px solid #ef4444;
  padding: 12px 14px;
  border-radius: 0 6px 6px 0;
}

.alert-icon {
  font-size: 14px;
  margin-top: 1px;
}

.alert-text {
  font-size: 14px;
  color: #7f1d1d;
  line-height: 1.6;
  font-weight: 500;
}

.chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 18px;
}

.chart-shell {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.02);
}

.chart-title {
  font-size: 14px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 14px;
  text-align: center;
}

.chart-canvas {
  width: 100%;
  height: 320px;
}

.evidence-box {
  margin-top: 14px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 12px;
  padding: 12px 14px;
}

.evidence-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
}

/* 建议与理由模块 */
.recommendation-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rec-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.rec-col {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 10px;
  padding: 16px;
}

.rec-col-title {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 700;
  color: #334155;
}

.custom-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.custom-list li {
  position: relative;
  padding-left: 16px;
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
}

.custom-list li::before {
  content: "•";
  color: #3b82f6;
  font-weight: bold;
  position: absolute;
  left: 0;
  top: -1px;
  font-size: 16px;
  line-height: 1.2;
}

.evidence-list li::before {
  content: "↳";
  color: #8b5cf6;
  font-size: 13px;
  top: 1px;
}

.param-grid {
  margin-top: 4px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.param-card {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
  padding: 12px;
}

.param-title {
  font-size: 14px;
  font-weight: 800;
  color: #1e3a8a;
  margin-bottom: 8px;
}

.param-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  margin-bottom: 6px;
}

.param-k {
  font-size: 12px;
  color: #64748b;
  font-weight: 700;
}

.param-v {
  font-size: 13px;
  color: #1e293b;
  line-height: 1.55;
}

.scenario-table-wrap {
  margin-top: 12px;
  overflow-x: auto;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
}

.scenario-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.scenario-table th,
.scenario-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
  white-space: nowrap;
}

.scenario-table th {
  font-size: 12px;
  color: #64748b;
  font-weight: 800;
  background: #f8fafc;
}

.counter-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.counter-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #ffffff;
  padding: 12px;
}

.counter-title {
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
}

.counter-beforeafter {
  margin-top: 8px;
  font-size: 13px;
  color: #1e3a8a;
  font-weight: 700;
}

.counter-effects {
  margin: 8px 0 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.counter-effects li {
  font-size: 13px;
  line-height: 1.5;
  color: #334155;
}

.counter-confidence {
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
}

.narrative-block {
  border-left: 4px solid #6366f1;
  background: linear-gradient(180deg, #fbfcff 0%, #ffffff 100%);
}

.narrative-block .kw-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.kw-label {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}
.kw-pill {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}
.next-actions {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}
.na-title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 8px;
}
.maturity-note {
  margin: 12px 0 0;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.45;
}

.policy-strip {
  margin-bottom: 12px;
}

.policy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px;
}

.causal-board {
  margin-top: 6px;
}

.causal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.hint-col-title {
  margin: 0 0 12px 0;
  padding-bottom: 10px;
  font-size: 14px;
  font-weight: 750;
  color: #0f172a;
  border-bottom: 1px solid #e2e8f0;
}

.hint-card {
  border-radius: 10px;
  padding: 12px 12px;
  font-size: 13px;
  color: #475569;
  line-height: 1.55;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.hint-card--causal {
  border-left: 4px solid #6366f1;
  background: linear-gradient(180deg, #fcfcff 0%, #ffffff 100%);
}

.hint-card--preset {
  border-left: 4px solid #0284c7;
  background: linear-gradient(180deg, #f6fbff 0%, #ffffff 100%);
  border-color: #cfe8ff;
}
.hint-topic {
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
  font-size: 14px;
}
.hint-chain {
  margin-bottom: 6px;
}
.hint-disclaimer {
  margin-top: 8px;
  font-size: 11px;
  color: #94a3b8;
}

.narrative-content {
  padding: 16px;
  border: 1px solid #dbe3ea;
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #ffffff 100%);
  box-shadow: inset 0 1px 0 rgba(59, 130, 246, 0.08);
}

.kw-row {
  margin-bottom: 10px;
}

.narr-headline-card {
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
  padding: 10px 12px;
}

.narr-headline-label {
  font-size: 12px;
  font-weight: 700;
  color: #1e3a8a;
  margin-bottom: 4px;
}

.narr-headline {
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
  color: #0f172a;
  font-weight: 700;
}

.narrative-split {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 14px;
  margin-top: 12px;
}

.narrative-panel {
  border: 1px solid #e5edf5;
  border-radius: 10px;
  background: #ffffff;
  padding: 14px 14px 12px;
}

.narrative-panel-title {
  margin: 0 0 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #edf2f7;
  font-size: 14px;
  font-weight: 750;
  color: #1e3a8a;
}

.narr-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.narr-list li {
  position: relative;
  border: 1px solid #e6edf5;
  border-radius: 8px;
  background: #f8fafc;
  padding: 9px 10px 9px 30px;
  font-size: 13px;
  line-height: 1.62;
  color: #334155;
}

.narr-list--insight li::before,
.narr-list--action li::before {
  position: absolute;
  left: 10px;
  top: 9px;
  width: 14px;
  text-align: center;
  font-size: 12px;
  font-weight: 800;
}

.narr-list--insight {
  counter-reset: insight;
}

.narr-list--insight li::before {
  counter-increment: insight;
  content: counter(insight);
  color: #2563eb;
}

.narr-list--action li {
  background: #f7faff;
  border-color: #dbeafe;
}

.narr-list--action li::before {
  content: "•";
  color: #2563eb;
}

/* 响应式调整 */
@media (max-width: 1100px) {
  .leadership-view {
    padding-left: 2px;
    padding-right: 2px;
  }

  .hero-meta-grid,
  .capability-grid {
    grid-template-columns: 1fr;
  }

  .decision-grid,
  .focus-grid {
    grid-template-columns: 1fr;
  }

  .kpi-grid {
    grid-template-columns: 1fr;
  }

  .chart-grid {
    grid-template-columns: 1fr;
  }
  .param-grid {
    grid-template-columns: 1fr;
  }
  .counter-grid {
    grid-template-columns: 1fr;
  }
  .rec-columns {
    grid-template-columns: 1fr;
  }

  .narrative-split {
    grid-template-columns: 1fr;
  }
}
</style>
