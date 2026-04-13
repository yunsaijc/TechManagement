import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

const SANDBOX_ACTIONS = [
  { id: 'leadership_forecast', title: '沙盘推演', method: 'POST', path: '/pipeline/leadership-forecast', timeout: 900000 },
];

const LEADERSHIP_SCENARIOS = [
  {
    id: 'overview',
    title: '全省趋势总览',
    description: '看整体风险等级与下一年度政策调控方向。',
    question: '请从领导视角研判我省近两年科研热点迁移、人才结构与转化效率风险，并给出下一年度指南调控建议。',
  },
  {
    id: 'conversion',
    title: '高增低转专题',
    description: '聚焦申报增长快但转化偏低的方向。',
    question: '请找出最近两年高增长低转化的重点主题，按紧急程度给出明年指南收紧建议。',
  },
  {
    id: 'talent',
    title: '人才断层专题',
    description: '识别人才梯队薄弱的关键学科方向。',
    question: '请识别我省重点科研主题的人才断层风险，给出骨干人才补强与联合攻关建议。',
  },
];

const FORECAST_MODES = [
  { value: 'quick', label: '快速推演（推荐）', description: '优先复用近期结果，速度快。' },
  { value: 'standard', label: '标准推演', description: '平衡速度与完整性。' },
  { value: 'deep', label: '深度推演', description: '全量重算，耗时更长。' },
];

export const useSandboxStore = defineStore('sandbox', () => {
  const moduleId = 'sandbox';
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  const lastResult = ref(null);
  const resultText = ref('');
  const requestMeta = ref('等待开始沙盘推演...');
  const latestActionId = ref('');
  const runs = ref([]);
  const selectedScenarioId = ref('overview');
  const forecastQuestion = ref(
    '请从领导视角研判我省近两年科研热点迁移、人才结构与转化效率风险，并给出下一年度指南调控建议。',
  );
  const forecastRunPreflight = ref(false);
  const forecastMode = ref('quick');
  const forecastForceRefresh = ref(false);

  const requestInProgress = computed(() => req.inProgressFor(moduleId));
  const progressText = computed(() => req.progressTextFor(moduleId));
  const requestStartedAt = computed(() => req.startedAtFor(moduleId));
  const activeTab = computed(() => ui.getTab(moduleId));
  const actions = SANDBOX_ACTIONS;
  const leadershipScenarios = LEADERSHIP_SCENARIOS;
  const forecastModes = FORECAST_MODES;

  function setActiveTab(tab) {
    ui.setTab(moduleId, tab);
  }

  function endpoint(path) {
    return `${req.apiBase()}/sandbox${path}`;
  }

  function findAction(actionId) {
    return actions.find((item) => item.id === actionId) || null;
  }

  async function fetchLatestLeadershipReport() {
    const latestUrl = endpoint('/pipeline/leadership-forecast/latest');
    const latest = await req.fetchWithTimeout(latestUrl, { method: 'GET' }, 12000);
    if (!latest || typeof latest !== 'object' || !latest.report || typeof latest.report !== 'object') {
      throw new Error('最新推演结果不可用');
    }
    return latest.report;
  }

  function formatValue(value) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    if (Array.isArray(value)) return `数组(${value.length})`;
    if (typeof value === 'object') return '对象';
    return String(value);
  }

  const summaryItems = computed(() => {
    if (!lastResult.value || typeof lastResult.value !== 'object') return [];
    const source = (lastResult.value.data && typeof lastResult.value.data === 'object')
      ? lastResult.value.data
      : lastResult.value;
    const future = source.futureJudgement && typeof source.futureJudgement === 'object'
      ? source.futureJudgement
      : null;
    if (!future) {
      return [{ k: '状态', v: String(source.status || '已完成') }];
    }

    const summary = future.summary && typeof future.summary === 'object' ? future.summary : {};
    const groups = summary.groupCounts && typeof summary.groupCounts === 'object' ? summary.groupCounts : {};
    return [
      { k: '研判等级', v: String(future.riskLevel || '-') },
      { k: '风险指数', v: Number.isFinite(Number(future.riskIndex)) ? `${Math.round(Number(future.riskIndex) * 100)}%` : '-' },
      { k: '高风险主题', v: String(summary.highRisk ?? '-') },
      { k: '人才风险项', v: String(groups.talent ?? '-') },
      { k: '转化风险项', v: String(groups.conversion ?? '-') },
    ];
  });

  const resultCards = computed(() => {
    if (!lastResult.value || typeof lastResult.value !== 'object') return [];
    const source = (lastResult.value.data && typeof lastResult.value.data === 'object')
      ? lastResult.value.data
      : lastResult.value;
    const cards = [];
    const brief = source.leadershipBrief && typeof source.leadershipBrief === 'object'
      ? source.leadershipBrief
      : {};
    const future = source.futureJudgement && typeof source.futureJudgement === 'object'
      ? source.futureJudgement
      : {};
    const retrieval = future.retrievalEvidence && typeof future.retrievalEvidence === 'object'
      ? future.retrievalEvidence
      : {};

    cards.push({
      title: '领导结论',
      rows: [
        { label: '一句话判断', value: String(brief.headline || '暂无结论') },
      ],
    });

    if (Array.isArray(brief.keyMessages) && brief.keyMessages.length) {
      cards.push({
        title: '关键趋势信号',
        rows: brief.keyMessages.slice(0, 6).map((item, idx) => ({
          label: `信号 ${idx + 1}`,
          value: String(item || '-'),
        })),
      });
    }

    if (Array.isArray(future.recommendations) && future.recommendations.length) {
      cards.push({
        title: '下一年度治理建议',
        rows: future.recommendations.slice(0, 6).map((item, idx) => ({
          label: `建议 ${idx + 1}`,
          value: String(item || '-'),
        })),
      });
    }

    if (Array.isArray(future.priorityTopics) && future.priorityTopics.length) {
      cards.push({
        title: '重点关注主题',
        rows: future.priorityTopics.slice(0, 8).map((item, idx) => ({
          label: `${idx + 1}. ${item.topic || '<未知主题>'}`,
          value: `${item.type || 'unknown'} | ${item.suggestion || '-'}`,
        })),
      });
    }

    cards.push({
      title: '证据基础',
      rows: [
        { label: '领导问题', value: String(retrieval.question || '-') },
        { label: '检索种子', value: String(retrieval.retrievedSeeds ?? '-') },
        { label: '关联节点', value: String(retrieval.retrievedNodes ?? '-') },
        { label: '关联关系', value: String(retrieval.retrievedRelationships ?? '-') },
      ],
    });

    if (Array.isArray(runs.value) && runs.value.length) {
      const rows = runs.value.slice(0, 8).map((item) => ({
        label: item.time,
        value: `${item.title} | ${item.ok ? '成功' : '失败'}`,
      }));
      cards.push({ title: '本地运行记录', rows });
    }

    return cards;
  });

  const isMarkdownReportPayload = computed(() => false);

  async function runAction(actionId) {
    const action = findAction(actionId);
    if (!action) {
      ui.toast('无效操作', 'error', 2000);
      return null;
    }

    if (!req.begin(moduleId, action.title)) {
      ui.toast('当前有请求正在处理中，请稍候');
      return null;
    }

    const controller = new AbortController();
    req.attachController(moduleId, controller);
    const url = endpoint(action.path);
    const bodyPayload = action.id === 'leadership_forecast'
      ? {
          question: String(forecastQuestion.value || '').trim(),
          runPreflight: Boolean(forecastRunPreflight.value),
          mode: String(forecastMode.value || 'quick'),
          forceRefresh: Boolean(forecastForceRefresh.value),
        }
      : null;

    try {
      requestMeta.value = '正在生成领导视角沙盘推演，请稍候...';
      latestActionId.value = action.id;
      const payload = await req.fetchWithTimeout(
        url,
        bodyPayload
          ? {
              method: action.method,
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(bodyPayload),
            }
          : { method: action.method },
        action.timeout,
        controller,
      );

      lastResult.value = payload;
      resultText.value = JSON.stringify(payload, null, 2);
      requestMeta.value = '已生成最新领导推演结论';
      ui.setTab(moduleId, 'result');
      runs.value.unshift({
        id: `${Date.now()}_${action.id}`,
        time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        title: '沙盘推演',
        ok: true,
      });
      runs.value = runs.value.slice(0, 12);
      hist.record({
        title: '政策沙盘 - 领导推演',
        method: action.method,
        url,
        ok: true,
      });
      ui.toast('推演完成，已生成领导简报');
      return payload;
    } catch (error) {
      const msg = String(error || '执行失败');
      if (action.id === 'leadership_forecast' && msg.includes('请求超时')) {
        try {
          const latestReport = await fetchLatestLeadershipReport();
          lastResult.value = latestReport;
          resultText.value = JSON.stringify(latestReport, null, 2);
          requestMeta.value = '请求超时，但已载入后端最新推演结果';
          ui.setTab(moduleId, 'result');
          runs.value.unshift({
            id: `${Date.now()}_${action.id}`,
            time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
            title: '沙盘推演（超时回填）',
            ok: true,
          });
          runs.value = runs.value.slice(0, 12);
          hist.record({
            title: '政策沙盘 - 领导推演（超时回填）',
            method: 'GET',
            url: endpoint('/pipeline/leadership-forecast/latest'),
            ok: true,
          });
          ui.toast('推演请求超时，但已加载最新结果');
          return latestReport;
        } catch (fallbackError) {
          const fallbackMsg = String(fallbackError || '无法读取最新推演结果');
          requestMeta.value = `推演失败：${msg}；回填失败：${fallbackMsg}`;
          resultText.value = `请求错误：${msg}\n回填错误：${fallbackMsg}`;
        }
      } else {
        requestMeta.value = `推演失败：${msg}`;
        resultText.value = msg;
      }

      runs.value.unshift({
        id: `${Date.now()}_${action.id}`,
        time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        title: '沙盘推演',
        ok: false,
      });
      runs.value = runs.value.slice(0, 12);
      hist.record({
        title: '政策沙盘 - 领导推演',
        method: action.method,
        url,
        ok: false,
      });
      ui.toast(msg, 'error', 3000);
      return null;
    } finally {
      req.end(moduleId);
    }
  }

  function stop() {
    if (req.stop(moduleId)) {
      ui.toast('已停止当前请求');
      return;
    }
    ui.toast('当前无进行中的请求');
  }

  function copyResult() {
    if (!req.hasText(resultText.value)) {
      ui.toast('当前没有可复制内容');
      return;
    }
    navigator.clipboard
      .writeText(resultText.value)
      .then(() => ui.toast('已复制到剪贴板'))
      .catch(() => ui.toast('复制失败', 'error', 2200));
  }

  function clearResult() {
    requestMeta.value = '等待开始沙盘推演...';
    lastResult.value = null;
    resultText.value = '';
    latestActionId.value = '';
  }

  function setScenario(scenarioId) {
    const scenario = leadershipScenarios.find((item) => item.id === scenarioId);
    if (!scenario) return;
    selectedScenarioId.value = scenario.id;
    forecastQuestion.value = scenario.question;
  }

  async function runLeadershipForecast() {
    return runAction('leadership_forecast');
  }

  function initialize() {
    if (!latestActionId.value) {
      setActiveTab('form');
    }
  }

  return {
    moduleId,
    actions,
    latestActionId,
    forecastQuestion,
    forecastRunPreflight,
    forecastMode,
    forecastForceRefresh,
    forecastModes,
    selectedScenarioId,
    leadershipScenarios,
    requestMeta,
    lastResult,
    resultText,
    requestInProgress,
    progressText,
    requestStartedAt,
    activeTab,
    summaryItems,
    resultCards,
    isMarkdownReportPayload,
    setActiveTab,
    setScenario,
    runLeadershipForecast,
    runAction,
    stop,
    copyResult,
    clearResult,
    initialize,
  };
});
