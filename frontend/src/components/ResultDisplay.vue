<script setup>
import { computed, ref } from 'vue';
import PlagiarismReportView from '../modules/plagiarism/PlagiarismReportView.vue';

const props = defineProps({
  requestMeta: { type: String, required: true },
  summaryItems: { type: Array, required: true },
  isMarkdownReportPayload: { type: Boolean, required: true },
  lastResult: { type: [Object, String, null], default: null },
  resultCards: { type: Array, required: true },
  resultText: { type: String, required: true },
  moduleId: { type: String, default: '' },
  actionId: { type: [String, null], default: null },
  groupingFilter: { type: String, default: '' },
  groupingFilterExact: { type: Boolean, default: false },
});

const normalizedData = computed(() => {
  if (!props.lastResult || typeof props.lastResult !== 'object') return null;
  if (props.lastResult.data !== undefined) return props.lastResult.data;
  return props.lastResult;
});

const reviewData = computed(() => {
  const data = normalizedData.value;
  if (!data || typeof data !== 'object' || !Array.isArray(data.results)) return null;
  return data;
});

const reviewStats = computed(() => {
  if (!reviewData.value) return null;
  const stats = { passed: 0, failed: 0, warning: 0, skipped: 0 };
  reviewData.value.results.forEach((item) => {
    if (stats[item.status] !== undefined) stats[item.status] += 1;
  });
  return stats;
});

const reviewSummaryCards = computed(() => {
  if (!reviewData.value) return [];
  const docType = reviewData.value.document_type_raw || reviewData.value.document_type || '';
  const docTypeMap = {
    retrieval_report: '检索报告',
    patent_certificate: '专利证书',
    acceptance_report: '验收报告',
    award_certificate: '奖励证书',
    award_contributor: '奖励-主要完成人情况表',
    paper: '论文',
    unknown: '其他/未知',
    project_application: '项目申报材料',
    proposal: '项目建议书',
    other: '其他',
  };
  return [
    { label: '审查编号', value: reviewData.value.id || '-' },
    { label: '文档类型', value: docTypeMap[docType] || docType || '-' },
  ];
});

function formatReviewSuggestion(text) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  const s = stripMarkdown(raw).replace(/\s+/g, ' ').trim();

  const m = s.match(/^(注意|提示|警告|建议|请检查|请核查)[:：]\s*([A-Za-z0-9_]+)\s*[-—:：]\s*(.+)$/);
  if (m) {
    const head = m[1];
    const key = m[2];
    const msg = m[3];
    const label = formatLabel(key);
    if (label && label !== key) return `${head}：${label} - ${msg}`;
    return `${head}：${msg}`;
  }

  const m2 = s.match(/^([A-Za-z0-9_]+)\s*[-—:：]\s*(.+)$/);
  if (m2) {
    const key = m2[1];
    const msg = m2[2];
    const label = formatLabel(key);
    if (label && label !== key) return `${label} - ${msg}`;
    return msg;
  }

  return s;
}

const reviewSuggestions = computed(() => {
  if (!reviewData.value || !Array.isArray(reviewData.value.suggestions)) return [];
  return reviewData.value.suggestions.map(formatReviewSuggestion).filter(Boolean);
});

const reviewExtractedEntries = computed(() => {
  if (!reviewData.value || !reviewData.value.extracted_data || typeof reviewData.value.extracted_data !== 'object') return [];
  return Object.entries(reviewData.value.extracted_data)
    .filter(([, value]) => value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length))
    .map(([key, value]) => ({ key, value: plainValue(value, 24) }));
});

function mapDocTypeValue(val) {
  const s = String(val || '').trim();
  const docMap = {
    patent_certificate: '专利证书',
    acceptance_report: '验收报告',
    retrieval_report: '检索报告',
    award_certificate: '奖励证书',
    award_contributor: '奖励-主要完成人情况表',
    paper: '论文',
    unknown: '其他/未知',
  };
  return docMap[s] || s;
}

const reviewLlmEntries = computed(() => {
  if (!reviewData.value || !reviewData.value.llm_analysis || typeof reviewData.value.llm_analysis !== 'object') return [];
  return Object.entries(reviewData.value.llm_analysis)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      const v = String(key || '').toLowerCase().includes('document_type') ? mapDocTypeValue(value) : plainValue(value, 24);
      return { key, value: v };
    });
});

const reviewConclusion = computed(() => {
  if (!reviewData.value) return { label: '未知', status: 'skipped' };
  const state = String(reviewData.value.status || '').toLowerCase();
  if (state === 'processing') return { label: '处理中', status: 'skipped' };
  if (state === 'failed') return { label: '失败', status: 'failed' };
  if (!reviewStats.value) return { label: '未知', status: 'skipped' };
  if (reviewStats.value.failed > 0) return { label: '未通过', status: 'failed' };
  if (reviewStats.value.warning > 0) return { label: '有警告', status: 'warning' };
  return { label: '通过', status: 'passed' };
});

const reviewProcessing = computed(() => {
  const data = reviewData.value;
  if (!data || typeof data !== 'object') return false;
  return String(data.status || '').toLowerCase() === 'processing';
});

const reviewOcrText = computed(() => {
  if (!reviewData.value) return '';
  return reviewData.value.ocr_text || '';
});

function reviewEvidenceRows(item) {
  if (!item || !item.evidence || typeof item.evidence !== 'object') return [];
  const rows = formatEvidence(item.evidence) || [];
  const key = String(item.item || '').toLowerCase().trim();
  const allowMap = {
    work_unit_consistency: ['工作单位', '完成单位', '盖章单位', '来源', '智能发现问题'],
    signature_name_consistency: ['姓名', '签字分析'],
    signature: ['签字分析'],
    stamp: ['印章结果', '印章分析'],
    retrieval_report_completeness: ['论文列表', '缺失论文', '智能发现问题'],
  };
  const allowed = allowMap[key];
  let filtered = allowed
    ? rows.filter((r) => allowed.includes(r.label))
    : rows;
  filtered = filtered
    .filter((r) => r && r.value && String(r.value).trim() && String(r.value).trim() !== '-')
    .slice(0, 8);
  return filtered.map((r) => {
    const label = String(r.label || '').trim();
    if (label === '签字分析' || label === '印章分析') {
      return { ...r, kind: 'analysis', value: normalizeAnalysisText(r.value) };
    }
    return { ...r, kind: 'row' };
  });
}

function normalizeAnalysisText(text) {
  let s = stripMarkdown(String(text || ''));
  s = s.replace(/\r/g, '');
  s = s.replace(/\n{3,}/g, '\n\n');
  s = s.replace(/^\s*1[\.．]\s*页面中的签字\/签名位置如下[:：]\s*$/m, '');
  s = s.replace(/^\s*1[\.．]\s*页面中的印章(?:位置)?如下[:：]\s*$/m, '');
  return s.trim();
}

const groupingData = computed(() => {
  if (props.moduleId !== 'grouping') return null;
  const data = normalizedData.value;
  if (!data || typeof data !== 'object') return null;
  if (!Array.isArray(data.groups)) return null;
  if (!data.statistics || typeof data.statistics !== 'object') return null;
  return data;
});

const openGroupingId = ref(null);

function toggleGrouping(groupId) {
  if (!groupId) return;
  openGroupingId.value = openGroupingId.value === groupId ? null : groupId;
}

function isGroupingOpen(groupId) {
  return Boolean(groupId) && openGroupingId.value === groupId;
}

function groupingProjectCount(g) {
  if (!g || typeof g !== 'object') return 0;
  if (typeof g.count === 'number') return g.count;
  if (Array.isArray(g.projects)) return g.projects.length;
  return 0;
}

function normalizeSearchText(value) {
  return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function groupSearchText(g) {
  if (!g || typeof g !== 'object') return '';
  const parts = [g.group_id, g.subject_name, g.subject_code];
  return normalizeSearchText(parts.join(' '));
}

function groupExactTokens(g) {
  if (!g || typeof g !== 'object') return [];
  return [g.group_id, g.subject_name, g.subject_code]
    .map((x) => normalizeSearchText(x))
    .filter(Boolean);
}

const groupingFilteredGroups = computed(() => {
  const groups = Array.isArray(groupingData.value?.groups) ? groupingData.value.groups : [];
  const keyword = normalizeSearchText(props.groupingFilter);
  if (!keyword) return groups;
  const exact = Boolean(props.groupingFilterExact);

  if (exact) {
    return groups.filter((g) => groupExactTokens(g).some((x) => x === keyword));
  }

  const matched = [];
  groups.forEach((g) => {
    const groupMatched = groupSearchText(g).includes(keyword);
    if (groupMatched) matched.push(g);
  });

  return matched;
});

const groupingOverviewCards = computed(() => {
  if (!groupingData.value) return [];
  const hasFilter = Boolean(normalizeSearchText(props.groupingFilter));
  if (hasFilter) {
    const groups = groupingFilteredGroups.value;
    const totalProjects = groups.reduce((sum, g) => {
      if (Array.isArray(g?.projects)) return sum + g.projects.length;
      return sum + groupingProjectCount(g);
    }, 0);
    const groupCount = groups.length;
    const avg = groupCount > 0 ? (totalProjects / groupCount).toFixed(2) : '0.00';
    return [
      { label: '项目数', value: totalProjects },
      { label: '分组数', value: groupCount },
      { label: '平均每组项目数', value: avg },
    ];
  }

  const stats = groupingData.value.statistics || {};
  const groupCount = stats.total_groups ?? stats.group_count ?? stats.groups ?? '-';
  const rows = [
    { label: '项目数', value: stats.total_projects ?? '-' },
    { label: '分组数', value: groupCount },
    { label: '平均每组项目数', value: typeof stats.avg_projects_per_group === 'number' ? stats.avg_projects_per_group.toFixed(2) : (stats.avg_projects_per_group ?? '-') },
  ];
  return rows.filter((x) => x.value !== undefined);
});

function groupingDistributionRows(g) {
  if (!g || !g.subject_code_2_distribution || typeof g.subject_code_2_distribution !== 'object') return [];
  return Object.entries(g.subject_code_2_distribution)
    .map(([k, v]) => `${k}: ${v}`)
    .slice(0, 16);
}

function translateRiskFlag(flag) {
  const value = String(flag || '').trim();
  if (!value) return '';
  const map = {
    cross_level1: '跨一级学科',
    many_level2: '二级学科过多',
    singleton_subject_code_1: '一级学科单例',
    singleton_subject_code_2: '二级学科单例',
    subject_outlier: '学科异常',
  };
  return map[value] || value;
}

function groupingRiskFlagsRows(flags) {
  if (!Array.isArray(flags) || !flags.length) return [];
  return flags.map((x) => translateRiskFlag(x)).filter(Boolean);
}

function projectKeywordsText(p) {
  if (!p || !Array.isArray(p.keywords) || !p.keywords.length) return '-';
  return p.keywords.join(' / ');
}

function projectRiskFlagsText(p) {
  if (!p || !Array.isArray(p.risk_flags) || !p.risk_flags.length) return '-';
  return p.risk_flags.map((x) => translateRiskFlag(x)).filter(Boolean).join(' / ');
}

function projectOriginalSubjectText(p) {
  if (!p || typeof p !== 'object') return '-';
  const code = p.original_subject_code || '-';
  const name = p.original_subject_name || '-';
  return `${name}（${code}）`;
}

function projectOriginalSubject2Text(p) {
  if (!p || typeof p !== 'object') return '-';
  const code = p.original_subject_code_2 || '-';
  const name = p.original_subject_name_2 || '-';
  return `${name}（${code}）`;
}

function groupingRawJson() {
  if (!groupingData.value) return '{}';
  try {
    return JSON.stringify(groupingData.value, null, 2);
  } catch {
    return '{}';
  }
}

const plagiarismData = computed(() => {
  if (props.moduleId !== 'plagiarism') return null;
  const data = normalizedData.value;
  if (!data || typeof data !== 'object') return null;
  if (!Array.isArray(data.high_similarity) || !Array.isArray(data.medium_similarity) || !Array.isArray(data.low_similarity)) return null;
  return data;
});

const hasCustomView = computed(() => Boolean(
  reviewData.value
  || groupingData.value
  || plagiarismData.value
  || perfcheckTaskData.value
  || perfcheckResultData.value,
));

const evaluationData = computed(() => {
  if (props.moduleId !== 'evaluation') return null;
  const data = normalizedData.value;
  if (!data || typeof data !== 'object') return null;
  if (typeof data.overall_score !== 'number' || !Array.isArray(data.dimension_scores)) return null;
  return data;
});

const perfcheckTaskData = computed(() => {
  if (props.moduleId !== 'perfcheck') return null;
  const data = normalizedData.value;
  if (!data || typeof data !== 'object') return null;
  if (!data.task_id || !data.state) return null;
  return data;
});

const perfcheckResultData = computed(() => {
  if (props.moduleId !== 'perfcheck') return null;
  const data = normalizedData.value;
  if (!data || typeof data !== 'object') return null;
  const direct = (
    data.task_id
    && data.project_id
    && Array.isArray(data.metrics_risks)
    && Array.isArray(data.content_risks)
    && Array.isArray(data.budget_risks)
  ) ? data : null;
  if (direct) return direct;
  const nested = data.result && typeof data.result === 'object' ? data.result : null;
  if (
    nested
    && nested.task_id
    && nested.project_id
    && Array.isArray(nested.metrics_risks)
    && Array.isArray(nested.content_risks)
    && Array.isArray(nested.budget_risks)
  ) return nested;
  return null;
});

function riskBadge(riskLevel) {
  const v = String(riskLevel || '').toUpperCase();
  if (v === 'RED') return '高风险';
  if (v === 'YELLOW') return '中风险';
  if (v === 'GREEN') return '低风险';
  return v || '-';
}

function riskPillClass(riskLevel) {
  const v = String(riskLevel || '').toUpperCase();
  if (v === 'RED') return 'danger';
  if (v === 'YELLOW') return 'warn';
  if (v === 'GREEN') return 'ok';
  return 'muted';
}

function fmtPercent01(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '-';
  return `${Math.round(n * 100)}%`;
}

function zhKey(key) {
  const k = String(key || '');
  const map = {
    id: '编号',
    task_id: '任务编号',
    project_id: '项目编号',
    project_name: '项目名称',
    overall_score: '总分',
    grade: '等级',
    total_pairs: '对比对数',
    processing_time: '耗时',
    status: '状态',
    message: '消息',
    progress: '进度',
    stage: '阶段',
    created_at: '创建时间',
    warnings: '警告',
    report: '报告',
    groups: '分组',
    matches: '匹配结果',
  };
  if (map[k]) return map[k];
  return k.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
}

function zhSeverity(value) {
  const v = String(value || '').toLowerCase();
  if (v === 'high') return '高';
  if (v === 'medium') return '中';
  if (v === 'low') return '低';
  if (v === 'none') return '无';
  return value || '-';
}

function safePreview(text, limit = 120) {
  if (text === null || text === undefined) return '';
  const s = String(text).replace(/\s+/g, ' ').trim();
  if (s.length <= limit) return s;
  return `${s.slice(0, limit)}…`;
}

function zhTaskState(state) {
  const v = String(state || '').toLowerCase();
  if (v === 'running') return '处理中';
  if (v === 'finished') return '已完成';
  if (v === 'failed') return '失败';
  return state || '-';
}

function zhPerfStage(stage) {
  const v = String(stage || '').toLowerCase();
  if (v === 'parse') return '解析';
  if (v === 'extract') return '抽取';
  if (v === 'detect') return '检测';
  if (v === 'summary') return '总结';
  if (v === 'finalize') return '整理';
  if (v === 'done') return '完成';
  if (v === 'error') return '错误';
  return stage || '-';
}

function riskTitle(prefix, idx, x) {
  const type = x?.type ? String(x.type) : '';
  const reason = x?.reason ? safePreview(x.reason, 36) : '';
  const parts = [];
  if (type) parts.push(type);
  if (reason) parts.push(reason);
  if (parts.length) return parts.join(' | ');
  return `${prefix} ${idx + 1}`;
}

const perfMetricsAllItems = computed(() => {
  if (!perfcheckResultData.value) return [];
  const list = perfcheckResultData.value.metrics_risks || [];
  return list.slice(0, 60).map((x, idx) => ({
    key: `m_${idx}`,
    title: riskTitle('指标差异', idx, x),
    riskLevel: x.risk_level,
    rows: [
      { k: '风险等级', v: riskBadge(x.risk_level) },
      { k: '类型', v: x.type || '-' },
      { k: '申报值', v: x.apply_display || x.apply_value || '-' },
      { k: '任务值', v: x.task_display || x.task_value || '-' },
      { k: '单位', v: x.unit || '-' },
      { k: '原因', v: x.reason || '-' },
    ],
  }));
});

const perfMetricsKeyItems = computed(() => perfMetricsAllItems.value.filter((x) => String(x.riskLevel || '').toUpperCase() !== 'GREEN'));

const perfContentAllItems = computed(() => {
  if (!perfcheckResultData.value) return [];
  const list = perfcheckResultData.value.content_risks || [];
  return list.slice(0, 60).map((x, idx) => ({
    key: `c_${idx}`,
    title: x.apply_id ? `条目 ${x.apply_id}` : `内容条目 ${idx + 1}`,
    riskLevel: x.risk_level,
    rows: [
      { k: '风险等级', v: riskBadge(x.risk_level) },
      { k: '覆盖率', v: fmtPercent01(x.coverage_score) },
      { k: '判定', v: x.is_covered ? '已覆盖（内容一致或扩展）' : '未覆盖（内容缺失/不一致）' },
      { k: '说明', v: x.reason || '-' },
    ],
    applyText: x.apply_text || '',
    taskText: x.task_text || '',
  }));
});

const perfContentKeyItems = computed(() => perfContentAllItems.value.filter((x) => String(x.riskLevel || '').toUpperCase() !== 'GREEN'));

const perfBudgetAllItems = computed(() => {
  if (!perfcheckResultData.value) return [];
  const list = perfcheckResultData.value.budget_risks || [];
  return list.slice(0, 60).map((x, idx) => ({
    key: `b_${idx}`,
    title: riskTitle('预算差异', idx, x),
    riskLevel: x.risk_level,
    rows: [
      { k: '风险等级', v: riskBadge(x.risk_level) },
      { k: '类型', v: x.type || '-' },
      { k: '申报占比', v: Number.isFinite(x.apply_ratio) ? `${(x.apply_ratio * 100).toFixed(1)}%` : '-' },
      { k: '任务占比', v: Number.isFinite(x.task_ratio) ? `${(x.task_ratio * 100).toFixed(1)}%` : '-' },
      { k: '差值', v: Number.isFinite(x.ratio_delta) ? `${(x.ratio_delta * 100).toFixed(1)}%` : '-' },
      { k: '原因', v: x.reason || '-' },
    ],
  }));
});

const perfBudgetKeyItems = computed(() => perfBudgetAllItems.value.filter((x) => String(x.riskLevel || '').toUpperCase() !== 'GREEN'));

const perfOtherAllItems = computed(() => {
  if (!perfcheckResultData.value) return [];
  const list = perfcheckResultData.value.other_risks || [];
  if (!Array.isArray(list)) return [];
  return list.slice(0, 60).map((x, idx) => ({
    key: `o_${idx}`,
    title: x.field ? String(x.field) : `其他信息 ${idx + 1}`,
    riskLevel: x.risk_level,
    rows: [
      { k: '风险等级', v: riskBadge(x.risk_level) },
      { k: '字段', v: x.field || '-' },
      { k: '申报值', v: typeof x.apply_value === 'string' ? x.apply_value : JSON.stringify(x.apply_value) },
      { k: '任务值', v: typeof x.task_value === 'string' ? x.task_value : JSON.stringify(x.task_value) },
    ],
  }));
});

const perfOtherKeyItems = computed(() => perfOtherAllItems.value.filter((x) => String(x.riskLevel || '').toUpperCase() !== 'GREEN'));

const perfUnitBudgetAllItems = computed(() => {
  if (!perfcheckResultData.value) return [];
  const list = perfcheckResultData.value.unit_budget_risks || [];
  if (!Array.isArray(list)) return [];
  return list.slice(0, 80).map((x, idx) => ({
    key: `u_${idx}`,
    title: `${x.unit_name || '单位'} | ${x.type || '合计'}`,
    riskLevel: x.risk_level,
    rows: [
      { k: '单位', v: x.unit_name || '-' },
      { k: '类型', v: x.type || '-' },
      { k: '申报金额', v: Number.isFinite(x.apply_amount) ? x.apply_amount : (x.apply_amount ?? '-') },
      { k: '任务金额', v: Number.isFinite(x.task_amount) ? x.task_amount : (x.task_amount ?? '-') },
      { k: '风险等级', v: riskBadge(x.risk_level) },
      { k: '说明', v: x.reason || '-' },
    ],
  }));
});

const perfUnitBudgetKeyItems = computed(() => perfUnitBudgetAllItems.value.filter((x) => String(x.riskLevel || '').toUpperCase() !== 'GREEN'));

function riskLevelKey(level) {
  const v = String(level || '').toUpperCase();
  if (v === 'RED') return 'RED';
  if (v === 'YELLOW') return 'YELLOW';
  return 'GREEN';
}

const perfRiskCounts = computed(() => {
  const out = { RED: 0, YELLOW: 0, GREEN: 0 };
  const src = perfcheckResultData.value;
  if (!src) return out;
  const lists = [
    src.metrics_risks,
    src.content_risks,
    src.budget_risks,
    src.other_risks,
    src.unit_budget_risks,
  ].filter(Array.isArray);

  lists.forEach((arr) => {
    arr.forEach((x) => {
      out[riskLevelKey(x?.risk_level)] += 1;
    });
  });
  return out;
});

const perfOverallBadge = computed(() => {
  const c = perfRiskCounts.value;
  if (c.RED > 0) return { label: '高风险', cls: 'danger' };
  if (c.YELLOW > 0) return { label: '需关注', cls: 'warn' };
  return { label: '整体一致', cls: 'ok' };
});

const perfMetricsRows = computed(() => {
  const src = perfcheckResultData.value;
  if (!src || !Array.isArray(src.metrics_risks)) return [];
  return src.metrics_risks.slice(0, 200).map((x, idx) => ({
    id: `${idx}`,
    level: riskLevelKey(x?.risk_level),
    type: x?.type || '-',
    apply: x?.apply_display || x?.apply_value || '-',
    task: x?.task_display || x?.task_value || '-',
    unit: x?.unit || '-',
    reason: x?.reason || '-',
  }));
});

const perfContentRows = computed(() => {
  const src = perfcheckResultData.value;
  if (!src || !Array.isArray(src.content_risks)) return [];
  return src.content_risks.slice(0, 200).map((x, idx) => ({
    id: `${idx}`,
    level: riskLevelKey(x?.risk_level),
    applyId: x?.apply_id || `条目 ${idx + 1}`,
    coverage: fmtPercent01(x?.coverage_score),
    judgement: x?.is_covered ? '已覆盖（内容一致或扩展）' : '未覆盖（内容缺失/不一致）',
    reason: x?.reason || '-',
    applyText: x?.apply_text || '',
    taskText: x?.task_text || '',
  }));
});

const perfBudgetRows = computed(() => {
  const src = perfcheckResultData.value;
  if (!src || !Array.isArray(src.budget_risks)) return [];
  return src.budget_risks.slice(0, 200).map((x, idx) => ({
    id: `${idx}`,
    level: riskLevelKey(x?.risk_level),
    type: x?.type || '-',
    applyRatio: Number.isFinite(x?.apply_ratio) ? `${(x.apply_ratio * 100).toFixed(1)}%` : '-',
    taskRatio: Number.isFinite(x?.task_ratio) ? `${(x.task_ratio * 100).toFixed(1)}%` : '-',
    delta: Number.isFinite(x?.ratio_delta) ? `${(x.ratio_delta * 100).toFixed(1)}%` : '-',
    reason: x?.reason || '-',
  }));
});

const perfUnitBudgetRows = computed(() => {
  const src = perfcheckResultData.value;
  if (!src || !Array.isArray(src.unit_budget_risks)) return [];
  return src.unit_budget_risks.slice(0, 300).map((x, idx) => ({
    id: `${idx}`,
    level: riskLevelKey(x?.risk_level),
    unit: x?.unit_name || '-',
    type: x?.type || '-',
    applyAmount: Number.isFinite(x?.apply_amount) ? String(x.apply_amount) : (x?.apply_amount ?? '-'),
    taskAmount: Number.isFinite(x?.task_amount) ? String(x.task_amount) : (x?.task_amount ?? '-'),
    reason: x?.reason || '-',
  }));
});

const perfOtherRows = computed(() => {
  const src = perfcheckResultData.value;
  if (!src || !Array.isArray(src.other_risks)) return [];
  return src.other_risks.slice(0, 300).map((x, idx) => ({
    id: `${idx}`,
    level: riskLevelKey(x?.risk_level),
    field: x?.field || '-',
    apply: plainValue(x?.apply_value, 20),
    task: plainValue(x?.task_value, 20),
  }));
});

function formatLabel(key) {
  const map = {
    passed: '通过',
    failed: '未通过',
    warning: '警告',
    skipped: '跳过',
    id: '审查编号',
    document_type: '文档类型',
    document_type_raw: '文档类型（原始）',
    ocr_text: 'OCR 文本',
    processed_at: '处理时间',
    processing_time: '处理耗时',
    summary: '总结',
    suggestions: '修改建议',
    results: '检查结果',
    evidence: '证据',
    extracted_data: '提取信息',
    pages: '页数',
    units: '单位',
    work_units: '完成单位',
    authors: '作者',
    stamps: '印章',
    signatures: '签字',
    retrieval_report_completeness: '检索报告完整性',
    signature: '签字检查',
    stamp: '盖章检查',
    prerequisite: '前置条件',
    consistency: '一致性检查',
    completeness: '完整性检查',
    work_unit_consistency: '单位一致性',
    signature_name_consistency: '签字姓名一致性',
    document_type_llm: '智能识别文档类型',
    extracted_fields: '智能提取字段',
    stamps_description: '印章分析',
    signatures_description: '签字分析',
    tables: '表格识别',
    issues: '智能发现问题',
  };
  const norm = String(key || '').trim().toLowerCase().replace(/\s+/g, '_');
  const extra = {
    work_unit: '工作单位',
    completion_unit: '完成单位',
    stamp_units: '盖章单位',
    stamp_source: '来源',
    stamps_result: '印章结果',
    contributor_name: '姓名',
    fields: '字段',
  };
  return map[key] || extra[norm] || String(key).replace(/_/g, ' ');
}


function formatEvidence(evidence) {
  if (!evidence || typeof evidence !== 'object' || Array.isArray(evidence)) return null;
  // 常见字段映射
  const labelMap = {
    region_count: '区域数量',
    regions: '区域',
    bbox: '位置',
    confidence: '置信度',
    page: '页码',
    text: '内容',
    stamps: '印章',
    signatures: '签字',
    name: '姓名',
    unit: '单位',
    value: '值',
    type: '类型',
    error: '错误',
    // ...可扩展
  };
  const rows = [];
  Object.entries(evidence)
    .filter(([, v]) => v !== null && v !== undefined && v !== '' && (!Array.isArray(v) || v.length))
    .forEach(([k, v]) => {
      const label = labelMap[k] || formatLabel(k) || k;
      if (typeof v === 'string') {
        const parsed = tryParseJsonish(v);
        if (parsed !== null) {
          v = parsed;
        } else {
          v = plainValue(v, 24);
        }
      }
      if (typeof v === 'object' && v && !Array.isArray(v)) {
        const text = v.text || v.content || '';
        const bbox = v.bbox;
        const confidence = v.confidence;
        const lines = [];
        if (text) lines.push(`内容：${stripMarkdown(String(text)).trim()}`);
        if (bbox && typeof bbox === 'object') {
          const x1 = bbox.x1 ?? '-';
          const y1 = bbox.y1 ?? '-';
          const x2 = bbox.x2 ?? '-';
          const y2 = bbox.y2 ?? '-';
          lines.push(`位置：(${x1}, ${y1}) - (${x2}, ${y2})`);
        }
        if (typeof confidence === 'number') lines.push(`置信度：${Math.round(confidence * 100)}%`);
        if (lines.length) {
          rows.push({ label, value: lines.join('\n') });
          return;
        }
      }
      if (Array.isArray(v)) {
        const objs = v.filter((x) => x && typeof x === 'object' && !Array.isArray(x));
        const isTextBBoxList = objs.length === v.length && objs.every((x) => 'text' in x || 'content' in x || 'bbox' in x || 'confidence' in x);
        if (isTextBBoxList) {
          const blocks = objs.slice(0, 20).map((x, idx) => {
            const text = x.text || x.content || '';
            const bbox = x.bbox;
            const confidence = x.confidence;
            const lines = [];
            lines.push(`${idx + 1}. ${text ? stripMarkdown(String(text)).trim() : '（无内容）'}`);
            if (bbox && typeof bbox === 'object') {
              const x1 = bbox.x1 ?? '-';
              const y1 = bbox.y1 ?? '-';
              const x2 = bbox.x2 ?? '-';
              const y2 = bbox.y2 ?? '-';
              lines.push(`   位置：(${x1}, ${y1}) - (${x2}, ${y2})`);
            }
            if (typeof confidence === 'number') lines.push(`   置信度：${Math.round(confidence * 100)}%`);
            return lines.join('\n');
          });
          const more = v.length > 20 ? `\n…（共 ${v.length} 项）` : '';
          rows.push({ label, value: `${blocks.join('\n\n')}${more}` });
          return;
        }
        rows.push({ label, value: plainValue(v, 24) });
        return;
      }
      if (typeof v === 'object') {
        rows.push({ label, value: plainValue(v, 24) });
        return;
      }
      rows.push({ label, value: String(v) });
    });
  return rows;
}

function formatValue(value) {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatPct01(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}

function stripCodeFences(text) {
  const s = String(text || '');
  if (!s.includes('```')) return s;
  return s
    .replace(/```[a-zA-Z0-9_-]*\s*/g, '')
    .replace(/```/g, '');
}

function stripMarkdown(text) {
  let s = String(text || '');
  s = s.replace(/\*\*([^*]+)\*\*/g, '$1');
  s = s.replace(/__([^_]+)__/g, '$1');
  s = s.replace(/`([^`]+)`/g, '$1');
  return s;
}

function tryParseJsonish(text) {
  const raw = stripCodeFences(text).trim();
  if (!raw) return null;

  const candidates = [];
  const looksJson = (raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'));
  if (looksJson) candidates.push(raw);

  const fb = raw.indexOf('{');
  const lb = raw.lastIndexOf('}');
  if (fb >= 0 && lb > fb) candidates.push(raw.slice(fb, lb + 1));

  const fs = raw.indexOf('[');
  const ls = raw.lastIndexOf(']');
  if (fs >= 0 && ls > fs) candidates.push(raw.slice(fs, ls + 1));

  const seen = new Set();
  for (const cand of candidates) {
    const c = cand.trim();
    if (!c || seen.has(c)) continue;
    seen.add(c);
    try {
      return JSON.parse(c);
    } catch {}
    if (/[{[]\s*'/.test(c) || /None|True|False/.test(c)) {
      try {
        const normalized = c
          .replace(/'/g, '"')
          .replace(/\bNone\b/g, 'null')
          .replace(/\bTrue\b/g, 'true')
          .replace(/\bFalse\b/g, 'false');
        return JSON.parse(normalized);
      } catch {}
    }
  }
  return null;
}

function plainValue(value, maxItems = 20) {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') {
    const parsed = tryParseJsonish(value);
    if (parsed !== null) return plainValue(parsed, maxItems);
    let s = stripMarkdown(stripCodeFences(value)).trim();
    if (s === 'structure') return '结构化识别';
    if (s === 'parse') return '解析识别';
    s = s.replace(/^fields\s*[:：]/i, '字段：');
    s = s.replace(/fields\s*[:：]/gi, '字段：');
    return s;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return '-';
    const head = value.slice(0, maxItems).map((item) => {
      if (item === null || item === undefined) return '-';
      if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') return String(item);
      if (typeof item === 'object') {
        const name = item.name || item.xm || item.title || '';
        const duty = item.duty || item.role || item.position || '';
        if (name && duty) return `${name}（${duty}）`;
        if (name) return String(name);
        try {
          const pairs = Object.entries(item).slice(0, 4).map(([k, v]) => `${formatLabel(k)}：${plainValue(v, 6)}`);
          return pairs.join('；') || '-';
        } catch {
          return '-';
        }
      }
      return String(item);
    });
    const lines = head.join('\n');
    return value.length > maxItems ? `${lines}\n…（共 ${value.length} 项）` : lines;
  }
  if (typeof value === 'object') {
    try {
      const obj = value;
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        const signatures = obj.signatures;
        if (Array.isArray(signatures) && signatures.length) {
          const blocks = signatures.slice(0, maxItems).map((x, idx) => {
            if (!x || typeof x !== 'object') return `${idx + 1}. -`;
            const text = stripMarkdown(String(x.text || x.content || '')).trim();
            const bbox = x.bbox && typeof x.bbox === 'object' ? x.bbox : null;
            const conf = typeof x.confidence === 'number' ? x.confidence : null;
            const lines = [];
            lines.push(`${idx + 1}. ${text || '（无内容）'}`);
            if (bbox) {
              const x1 = bbox.x1 ?? '-';
              const y1 = bbox.y1 ?? '-';
              const x2 = bbox.x2 ?? '-';
              const y2 = bbox.y2 ?? '-';
              lines.push(`   位置：(${x1}, ${y1}) - (${x2}, ${y2})`);
            }
            if (conf !== null) lines.push(`   置信度：${Math.round(conf * 100)}%`);
            return lines.join('\n');
          });
          const more = signatures.length > maxItems ? `\n…（共 ${signatures.length} 项）` : '';
          return `${blocks.join('\n\n')}${more}`;
        }
        const stamps = obj.stamps;
        if (Array.isArray(stamps) && stamps.length) {
          const blocks = stamps.slice(0, maxItems).map((x, idx) => {
            if (!x || typeof x !== 'object') return `${idx + 1}. -`;
            const text = stripMarkdown(String(x.text || '')).trim();
            const unit = stripMarkdown(String(x.unit || '')).trim();
            const location = stripMarkdown(String(x.location || '')).trim();
            const bbox = x.bbox && typeof x.bbox === 'object' ? x.bbox : null;
            const conf = typeof x.confidence === 'number' ? x.confidence : null;
            const lines = [];
            lines.push(`${idx + 1}. ${text || '（无内容）'}${unit ? `（单位：${unit}）` : ''}${location ? `（位置：${location}）` : ''}`);
            if (bbox) {
              const x1 = bbox.x1 ?? '-';
              const y1 = bbox.y1 ?? '-';
              const x2 = bbox.x2 ?? '-';
              const y2 = bbox.y2 ?? '-';
              lines.push(`   位置：(${x1}, ${y1}) - (${x2}, ${y2})`);
            }
            if (conf !== null) lines.push(`   置信度：${Math.round(conf * 100)}%`);
            return lines.join('\n');
          });
          const more = stamps.length > maxItems ? `\n…（共 ${stamps.length} 项）` : '';
          return `${blocks.join('\n\n')}${more}`;
        }
      }
      const pairs = Object.entries(value).slice(0, 12).map(([k, v]) => `${formatLabel(k)}：${plainValue(v, 6)}`);
      const lines = pairs.join('\n');
      const more = Object.keys(value).length > 12 ? `\n…（共 ${Object.keys(value).length} 项）` : '';
      return lines ? `${lines}${more}` : '-';
    } catch {
      return '-';
    }
  }
  return String(value);
}
</script>

<template>
  <div v-if="lastResult || resultText" class="result-container">
    <div v-if="moduleId !== 'grouping' && moduleId !== 'perfcheck'" class="result-meta">{{ requestMeta }}</div>

    <template v-if="reviewData">
      <div class="review-top">
        <div class="review-overview-grid">
          <div v-for="card in reviewSummaryCards" :key="card.label" class="review-overview-card">
            <div class="review-overview-label">{{ card.label }}</div>
            <div class="review-overview-value">{{ card.value }}</div>
          </div>
          <div class="review-overview-card review-overview-card-wide">
            <div class="review-overview-label">总体结论</div>
            <div class="review-overview-value">
              <span class="review-pill" :class="reviewConclusion.status">{{ reviewConclusion.label }}</span>
              <span class="review-summary-inline">{{ reviewData.summary || '暂无总结' }}</span>
            </div>
          </div>
        </div>

        <div v-if="reviewStats" class="review-status-grid">
          <div class="review-status-card passed">
            <div class="review-status-label">通过</div>
            <div class="review-status-value">{{ reviewStats.passed }}</div>
          </div>
          <div class="review-status-card warning">
            <div class="review-status-label">警告</div>
            <div class="review-status-value">{{ reviewStats.warning }}</div>
          </div>
          <div class="review-status-card failed">
            <div class="review-status-label">未通过</div>
            <div class="review-status-value">{{ reviewStats.failed }}</div>
          </div>
          <div class="review-status-card skipped">
            <div class="review-status-label">跳过</div>
            <div class="review-status-value">{{ reviewStats.skipped }}</div>
          </div>
        </div>
      </div>

      <div v-if="reviewProcessing" class="progress-section">
        <div class="progress-title">正在审查</div>
        <div class="progress-bar">
          <div class="progress-bar-inner"></div>
        </div>
        <div class="progress-desc">请稍候，结果将自动刷新</div>
      </div>

      <div class="review-items">
        <div
          v-for="(item, idx) in reviewData.results"
          :key="idx"
          class="review-item-card"
          :class="`status-${String(item.status || '').toLowerCase()}`"
        >
          <div class="review-item-head">
            <div class="review-item-head-left">
              <span class="review-item-index">{{ idx + 1 }}</span>
              <span class="review-item-title">{{ formatLabel(item.item) }}</span>
              <span class="review-pill" :class="item.status">{{ formatLabel(item.status) }}</span>
            </div>
          </div>

          <div class="review-item-body">
            <div class="review-item-message">{{ item.message || '暂无详情' }}</div>

            <div v-if="item.evidence && Object.keys(item.evidence).length" class="review-evidence-list">
              <template v-for="(row, ridx) in reviewEvidenceRows(item)" :key="`${idx}_${ridx}`">
                <div v-if="row.kind === 'row'" class="review-evidence-row">
                  <div class="review-evidence-k">{{ row.label }}</div>
                  <div class="review-evidence-v"><div class="review-pre">{{ row.value }}</div></div>
                </div>
                <div v-else class="review-analysis-block">
                  <div class="review-analysis-title">{{ row.label }}</div>
                  <div class="review-analysis-body review-pre">{{ row.value }}</div>
                </div>
              </template>
            </div>

            <div v-else class="review-evidence-empty">无可展示的证据</div>
          </div>
        </div>
      </div>

      <div v-if="reviewSuggestions.length" class="review-section">
        <div class="review-section-title">修改建议</div>
        <ul class="review-bullet-list">
          <li v-for="(suggestion, idx) in reviewSuggestions" :key="idx">{{ suggestion }}</li>
        </ul>
      </div>
    </template>

    <template v-else-if="groupingData">
      <div class="result-summary result-summary-inline-3">
        <div v-for="item in groupingOverviewCards" :key="item.label" class="summary-item">
          <div class="summary-key">{{ item.label }}</div>
          <div class="summary-value">{{ item.value }}</div>
        </div>
      </div>

      <div v-if="groupingData.report" class="result-panels">
        <details class="result-panel">
          <summary class="result-panel-title">
            <span>可读报告</span>
            <span class="result-panel-count">文本</span>
          </summary>
          <div class="result-content">
            <div class="result-json">{{ groupingData.report }}</div>
          </div>
        </details>
      </div>

      <div v-if="groupingFilteredGroups.length" class="grouping-table-wrap">
        <table class="grouping-table">
          <thead>
            <tr>
              <th class="grouping-col-subject">学科名称</th>
              <th class="grouping-col-code">学科编码</th>
              <th class="grouping-col-count">项目数</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="g in groupingFilteredGroups" :key="g.group_id">
              <tr class="grouping-row">
                <td class="grouping-cell grouping-col-subject">
                  <button type="button" class="grouping-toggle" @click="toggleGrouping(g.group_id)">
                    <span class="grouping-toggle-text">{{ g.subject_name || g.subject_code || '未命名学科' }}</span>
                  </button>
                </td>
                <td class="grouping-cell grouping-col-code">
                  <span class="grouping-code">{{ g.subject_code || '-' }}</span>
                </td>
                <td class="grouping-cell grouping-col-count">
                  <span class="risk-pill muted">{{ groupingProjectCount(g) }} 项</span>
                </td>
              </tr>
              <tr v-if="isGroupingOpen(g.group_id)" class="grouping-row-detail">
                <td colspan="3" class="grouping-detail-cell">
                  <div class="grouping-extra-grid">
                    <div class="grouping-extra-card">
                      <div class="grouping-extra-title">风险标记</div>
                      <div v-if="groupingRiskFlagsRows(g.risk_flags).length" class="grouping-flag-list">
                        <span v-for="(f, fidx) in groupingRiskFlagsRows(g.risk_flags)" :key="`rf_${fidx}`" class="risk-pill warn">{{ f }}</span>
                      </div>
                      <div v-else class="grouping-empty-inline">无风险标记</div>
                    </div>

                    <div class="grouping-extra-card">
                      <div class="grouping-extra-title">风险说明</div>
                      <div v-if="Array.isArray(g.risk_details) && g.risk_details.length" class="grouping-chip-list">
                        <span v-for="(d, didx) in g.risk_details" :key="`rd_${didx}`" class="grouping-soft-chip">{{ d }}</span>
                      </div>
                      <div v-else class="grouping-empty-inline">无风险说明</div>
                    </div>

                    <div class="grouping-extra-card">
                      <div class="grouping-extra-title">二级学科分布</div>
                      <div v-if="groupingDistributionRows(g).length" class="grouping-chip-list">
                        <span v-for="(row, ridx) in groupingDistributionRows(g)" :key="`dist_${ridx}`" class="grouping-soft-chip grouping-soft-chip-mono">{{ row }}</span>
                      </div>
                      <div v-else class="grouping-empty-inline">暂无分布信息</div>
                    </div>
                  </div>

                  <div v-if="g.projects && g.projects.length" class="grouping-projects">
                    <div class="grouping-project-card-list">
                      <article v-for="p in g.projects" :key="p.project_id" class="grouping-project-card">
                        <div class="grouping-project-head">
                          <div class="grouping-project-name">{{ p.xmmc || p.project_id || '未命名项目' }}</div>
                          <div class="grouping-project-id">{{ p.project_id || '-' }}</div>
                        </div>
                        <div class="grouping-project-chip-row">
                          <span class="risk-pill muted">原始学科：{{ projectOriginalSubjectText(p) }}</span>
                          <span class="risk-pill muted">原始第二学科：{{ projectOriginalSubject2Text(p) }}</span>
                        </div>
                        <div class="grouping-project-field-grid grouping-project-field-grid-tight">
                          <div class="grouping-project-field">
                            <span class="grouping-project-field-label">关键词</span>
                            <span class="grouping-project-field-value">{{ projectKeywordsText(p) }}</span>
                          </div>
                          <div class="grouping-project-field">
                            <span class="grouping-project-field-label">风险标记</span>
                            <span class="grouping-project-field-value">{{ projectRiskFlagsText(p) }}</span>
                          </div>
                        </div>
                        <div class="grouping-project-snippet-box grouping-project-snippet-box-full">
                          <div class="grouping-project-field-label">完整简介</div>
                          <div class="grouping-project-snippet-text grouping-project-snippet-text-full">{{ p.xmjj || '-' }}</div>
                        </div>
                      </article>
                    </div>
                  </div>
                  <div v-else class="result-content">
                    <div class="grouping-empty-inline">该学科下暂无项目</div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-else class="result-empty-state grouping-filter-empty">
        <div class="result-empty-title">未找到匹配项</div>
        <div class="result-empty-desc">请更换关键词或从下拉菜单重新选择。</div>
      </div>

    </template>

    <template v-else-if="plagiarismData">
      <PlagiarismReportView :report="plagiarismData" />
    </template>

    <template v-else-if="evaluationData">
      <div class="result-summary">
        <div class="summary-item">
          <div class="summary-key">项目编号</div>
          <div class="summary-value">{{ evaluationData.project_id }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-key">项目名称</div>
          <div class="summary-value">{{ evaluationData.project_name || '-' }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-key">总分</div>
          <div class="summary-value">{{ evaluationData.overall_score.toFixed(2) }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-key">等级</div>
          <div class="summary-value">{{ evaluationData.grade }}</div>
        </div>
        <div class="summary-item" v-if="evaluationData.evaluation_id">
          <div class="summary-key">评审编号</div>
          <div class="summary-value">{{ evaluationData.evaluation_id }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-key">可问答</div>
          <div class="summary-value">{{ evaluationData.chat_ready ? '是' : '否' }}</div>
        </div>
      </div>

      <div v-if="evaluationData.summary" class="result-content">
        <div class="result-json">{{ evaluationData.summary }}</div>
      </div>

      <div v-if="evaluationData.recommendations && evaluationData.recommendations.length" class="result-panels">
        <details class="result-panel" open>
          <summary class="result-panel-title">
            <span>修改建议</span>
            <span class="result-panel-count">{{ evaluationData.recommendations.length }} 条</span>
          </summary>
          <div class="result-content">
            <div class="result-json">{{ evaluationData.recommendations.map((x, i) => `${i + 1}. ${x}`).join('\n') }}</div>
          </div>
        </details>
      </div>

      <div v-if="evaluationData.dimension_scores && evaluationData.dimension_scores.length" class="result-panels">
        <details v-for="d in evaluationData.dimension_scores" :key="d.dimension" class="result-panel">
          <summary class="result-panel-title">
            <span>{{ d.dimension_name || d.dimension }}</span>
            <span class="result-panel-count">{{ typeof d.score === 'number' ? d.score.toFixed(1) : '-' }} /10</span>
          </summary>
          <div v-if="d.opinion" class="result-content">
            <div class="result-json">{{ d.opinion }}</div>
          </div>
          <div v-if="d.issues && d.issues.length" class="result-content">
            <div class="result-json">{{ d.issues.map((x, i) => `问题 ${i + 1}：${x}`).join('\n') }}</div>
          </div>
          <div v-if="d.highlights && d.highlights.length" class="result-content">
            <div class="result-json">{{ d.highlights.map((x, i) => `亮点 ${i + 1}：${x}`).join('\n') }}</div>
          </div>
        </details>
      </div>
    </template>

    <template v-else-if="perfcheckTaskData || perfcheckResultData">
      <div v-if="typeof perfcheckTaskData?.progress === 'number'" class="perf-progress">
        <div class="perf-progress-bar">
          <div class="perf-progress-fill" :style="{ width: `${Math.max(0, Math.min(100, Math.round(perfcheckTaskData.progress * 100)))}%` }" />
        </div>
      </div>

      <!-- 移除核验结论概述 -->

      <div v-if="perfcheckTaskData?.state === 'failed'" class="result-content">
        <div class="result-json">{{ perfcheckTaskData.error_code || '核验失败' }}</div>
      </div>

      <div v-if="perfcheckResultData" class="result-panels">
        <div class="perf-risk-kpis-only">
          <div class="perf-kpis">
            <div class="perf-kpi">
              <div class="perf-kpi-v">{{ perfRiskCounts.RED }}</div>
              <div class="perf-kpi-k">高风险数量</div>
            </div>
            <div class="perf-kpi">
              <div class="perf-kpi-v">{{ perfRiskCounts.YELLOW }}</div>
              <div class="perf-kpi-k">中风险数量</div>
            </div>
            <div class="perf-kpi">
              <div class="perf-kpi-v">{{ perfRiskCounts.GREEN }}</div>
              <div class="perf-kpi-k">低风险数量</div>
            </div>
          </div>
        </div>

        <div class="result-panel" >
          <div class="result-panel-title">
            <span>核心考核指标对齐</span>
            <span class="result-panel-count">{{ perfMetricsRows.length }} 条</span>
          </div>
          <div class="perf-table-wrap" v-if="perfMetricsRows.length">
            <table class="perf-table">
              <thead>
                <tr>
                  <th class="perf-col-level">风险</th>
                  <th>指标</th>
                  <th>申报</th>
                  <th>任务</th>
                  <th class="perf-col-unit">单位</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in perfMetricsRows" :key="row.id">
                  <td><span class="perf-tag" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
                  <td>{{ row.type }}</td>
                  <td>{{ row.apply }}</td>
                  <td>{{ row.task }}</td>
                  <td class="perf-col-unit">{{ row.unit }}</td>
                  <td>{{ row.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="result-content"><div class="result-json">暂无数据</div></div>
        </div>

        <div class="result-panel">
          <div class="result-panel-title">
            <span>研究内容防缩水</span>
            <span class="result-panel-count">{{ perfContentRows.length }} 条</span>
          </div>
          <div class="perf-table-wrap" v-if="perfContentRows.length">
            <table class="perf-table">
              <thead>
                <tr>
                  <th class="perf-col-level">风险</th>
                  <th class="perf-col-id">条目</th>
                  <th class="perf-col-small">覆盖率</th>
                  <th class="perf-col-judge">判定</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in perfContentRows" :key="row.id">
                  <td><span class="perf-tag" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
                  <td class="perf-col-id">{{ row.applyId }}</td>
                  <td class="perf-col-small">{{ row.coverage }}</td>
                  <td class="perf-col-judge">{{ row.judgement }}</td>
                  <td>
                    <div class="perf-cell-text">{{ row.reason }}</div>
                    <div v-if="row.applyText || row.taskText" class="perf-cell-details">
                      <div class="perf-cell-summary">对照文本</div>
                      <div class="perf-text-grid">
                        <div v-if="row.applyText" class="perf-text-block">
                          <div class="perf-text-title">申报书</div>
                          <div class="review-pre">{{ row.applyText }}</div>
                        </div>
                        <div v-if="row.taskText" class="perf-text-block">
                          <div class="perf-text-title">任务书</div>
                          <div class="review-pre">{{ row.taskText }}</div>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="result-content"><div class="result-json">暂无数据</div></div>
        </div>

        <div class="result-panel">
          <div class="result-panel-title">
            <span>预算一致性</span>
            <span class="result-panel-count">{{ perfBudgetRows.length }} 条</span>
          </div>
          <div class="perf-table-wrap" v-if="perfBudgetRows.length">
            <table class="perf-table">
              <thead>
                <tr>
                  <th class="perf-col-level">风险</th>
                  <th>科目</th>
                  <th class="perf-col-small">申报占比</th>
                  <th class="perf-col-small">任务占比</th>
                  <th class="perf-col-small">差值</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in perfBudgetRows" :key="row.id">
                  <td><span class="perf-tag" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
                  <td>{{ row.type }}</td>
                  <td class="perf-col-small">{{ row.applyRatio }}</td>
                  <td class="perf-col-small">{{ row.taskRatio }}</td>
                  <td class="perf-col-small">{{ row.delta }}</td>
                  <td>{{ row.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="result-content"><div class="result-json">暂无数据</div></div>
        </div>

        <div class="result-panel">
          <div class="result-panel-title">
            <span>单位预算明细一致性</span>
            <span class="result-panel-count">{{ perfUnitBudgetRows.length }} 条</span>
          </div>
          <div class="perf-table-wrap" v-if="perfUnitBudgetRows.length">
            <table class="perf-table">
              <thead>
                <tr>
                  <th class="perf-col-level">风险</th>
                  <th>单位</th>
                  <th>科目</th>
                  <th class="perf-col-small">申报金额</th>
                  <th class="perf-col-small">任务金额</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in perfUnitBudgetRows" :key="row.id">
                  <td><span class="perf-tag" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
                  <td>{{ row.unit }}</td>
                  <td>{{ row.type }}</td>
                  <td class="perf-col-small">{{ row.applyAmount }}</td>
                  <td class="perf-col-small">{{ row.taskAmount }}</td>
                  <td>{{ row.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="result-content"><div class="result-json">暂无数据</div></div>
        </div>

        <div class="result-panel">
          <div class="result-panel-title">
            <span>其他关键信息</span>
            <span class="result-panel-count">{{ perfOtherRows.length }} 条</span>
          </div>
          <div class="perf-table-wrap" v-if="perfOtherRows.length">
            <table class="perf-table">
              <thead>
                <tr>
                  <th class="perf-col-level">风险</th>
                  <th>字段</th>
                  <th>申报书</th>
                  <th>任务书</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in perfOtherRows" :key="row.id">
                  <td><span class="perf-tag" :class="row.level.toLowerCase()">{{ row.level }}</span></td>
                  <td>{{ row.field }}</td>
                  <td><div class="review-pre">{{ row.apply }}</div></td>
                  <td><div class="review-pre">{{ row.task }}</div></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="result-content"><div class="result-json">暂无数据</div></div>
        </div>

        <div v-if="perfcheckResultData.warnings && perfcheckResultData.warnings.length" class="result-panel">
          <div class="result-panel-title">
            <span>警告</span>
            <span class="result-panel-count">{{ perfcheckResultData.warnings.length }} 条</span>
          </div>
          <div class="result-content">
            <div class="result-json">{{ perfcheckResultData.warnings.slice(0, 80).map((x, i) => `${i + 1}. ${x}`).join('\n') }}</div>
          </div>
        </div>
      </div>
    </template>

    <template v-if="!hasCustomView">
      <div v-if="summaryItems.length" class="result-summary">
        <div v-for="item in summaryItems" :key="item.k" class="summary-item">
          <div class="summary-key">{{ zhKey(item.k) }}</div>
          <div class="summary-value">{{ item.v }}</div>
        </div>
      </div>

      <div v-if="isMarkdownReportPayload" class="result-content report-markdown">
        <div class="result-markdown-title">核验报告（Markdown）</div>
        <div class="result-json">{{ lastResult.data }}</div>
      </div>

      <div v-if="!isMarkdownReportPayload && resultCards.length" class="result-panels">
        <details v-for="(card, idx) in resultCards" :key="idx" class="result-panel" :open="idx === 0">
          <summary class="result-panel-title">
            <span>{{ card.title }}</span>
            <span class="result-panel-count">{{ card.rows.length }} 项</span>
          </summary>
          <div class="result-panel-grid">
            <div v-for="(row, rowIdx) in card.rows" :key="rowIdx" class="result-row">
              <div class="result-row-key">{{ row.label }}</div>
              <div class="result-row-value">{{ row.value }}</div>
            </div>
          </div>
        </details>
      </div>

      <div v-if="!isMarkdownReportPayload && !resultCards.length && resultText" class="result-content">
        <div class="result-json">{{ resultText }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.progress-section {
  margin: 12px 0 18px;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafafa;
}
.progress-title {
  font-size: 14px;
  color: #374151;
  margin-bottom: 8px;
}
.progress-bar {
  position: relative;
  height: 6px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
}
.progress-bar-inner {
  position: absolute;
  left: -40%;
  top: 0;
  height: 100%;
  width: 40%;
  border-radius: 999px;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  animation: indeterminate 1.2s infinite;
}
@keyframes indeterminate {
  0% { left: -40%; width: 40%; }
  50% { left: 30%; width: 40%; }
  100% { left: 100%; width: 40%; }
}
.progress-desc {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}
</style>
