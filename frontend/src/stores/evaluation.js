import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { MODULES } from '../config/modules';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

export const useEvaluationStore = defineStore('evaluation', () => {
  const moduleId = 'evaluation';
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  const moduleConfig = computed(() => MODULES.find((m) => m.id === moduleId) || null);
  const debugResults = ref([]);
  const selectedDebugResultId = ref('');
  const lastResult = ref(null);
  const resultText = ref('');
  const requestMeta = ref('等待加载测试结果...');
  const questionDraft = ref('');
  const questionAnswer = ref('');
  const questionCitations = ref([]);

  const activeTab = computed(() => ui.getTab(moduleId));
  const requestInProgress = computed(() => req.inProgressFor(moduleId));
  const progressText = computed(() => req.progressTextFor(moduleId));
  const requestStartedAt = computed(() => req.startedAtFor(moduleId));

  const activeDebugResult = computed(() => debugResults.value.find((item) => item.id === selectedDebugResultId.value) || null);
  const debugPreviewUrl = computed(() => activeDebugResult.value?.html_url || activeDebugResult.value?.debug_html_url || '');
  const activeEvaluationId = computed(() => lastResult.value?.data?.evaluation_id || lastResult.value?.evaluation_id || '');

  function setActiveTab(tab) {
    ui.setTab(moduleId, tab);
  }

  function debugBaseUrl() {
    return req.apiBase().replace(/\/api\/v1$/, '');
  }

  function formatKey(key) {
    const k = String(key || '').trim();
    const map = {
      project_id: '项目编号',
      project_name: '项目名称',
      source_name: '来源文件',
      evaluation_id: '评审编号',
      overall_score: '总分',
      grade: '等级',
      chat_ready: '可问答',
      partial: '是否完整',
      created_at: '创建时间',
      updated_at: '更新时间',
      summary: '总结',
      recommendations: '修改建议',
      dimension_scores: '维度评分',
      highlights: '亮点',
      errors: '错误',
      result: '结果',
    };
    if (map[k]) return map[k];
    return k.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function toDisplayText(value) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (Array.isArray(value)) return value.length ? value.map((v) => toDisplayText(v)).join(' | ') : '-';
    if (typeof value === 'object') {
      const pairs = Object.entries(value)
        .slice(0, 4)
        .map(([k, v]) => `${formatKey(k)}: ${toDisplayText(v)}`);
      return pairs.length ? pairs.join('；') : '-';
    }
    return String(value);
  }

  const summaryItems = computed(() => {
    if (!lastResult.value || typeof lastResult.value !== 'object') return [];
    const source = (lastResult.value.data && typeof lastResult.value.data === 'object') ? lastResult.value.data : lastResult.value;
    const keys = ['project_id', 'project_name', 'evaluation_id', 'overall_score', 'grade', 'chat_ready', 'partial'];
    const items = [];
    keys.forEach((key) => {
      if (source[key] !== undefined && source[key] !== null) {
        items.push({ k: key, v: String(source[key]) });
      }
    });
    return items.slice(0, 6);
  });

  const resultCards = computed(() => {
    if (!lastResult.value || typeof lastResult.value !== 'object') return [];
    const source = (lastResult.value.data && typeof lastResult.value.data === 'object') ? lastResult.value.data : lastResult.value;
    const cards = [];
    const topRows = [];

    Object.entries(source).forEach(([key, value]) => {
      if (value === null || value === undefined) return;
      if (typeof value === 'object') return;
      topRows.push({ label: formatKey(key), value: toDisplayText(value) });
    });

    if (topRows.length) {
      cards.push({ title: '结果概览', rows: topRows.slice(0, 12) });
    }

    Object.entries(source).forEach(([key, value]) => {
      if (!value || typeof value !== 'object') return;

      if (Array.isArray(value)) {
        const rows = value.slice(0, 8).map((item, idx) => ({
          label: `条目 ${idx + 1}`,
          value: toDisplayText(item),
        }));
        cards.push({ title: `${formatKey(key)}（共 ${value.length} 条）`, rows });
        return;
      }

      const rows = Object.entries(value).slice(0, 12).map(([childKey, childValue]) => ({
        label: formatKey(childKey),
        value: toDisplayText(childValue),
      }));
      cards.push({ title: formatKey(key), rows });
    });

    return cards.slice(0, 8);
  });

  const isMarkdownReportPayload = computed(() => false);

  function normalizePayload(payload) {
    if (payload && typeof payload === 'object' && !Array.isArray(payload) && payload.result && typeof payload.result === 'object') {
      return payload.result;
    }
    return payload;
  }

  function buildRequestMeta(resultItem, payload) {
    const source = normalizePayload(payload);
    const projectName = resultItem?.title || source?.project_name || '未命名项目';
    const score = source?.overall_score;
    const grade = source?.grade || '-';
    const scoreText = Number.isFinite(Number(score)) ? Number(score).toFixed(2) : '-';
    return `${projectName} | ${scoreText} / ${grade}`;
  }

  async function loadDebugResults() {
    const url = `${debugBaseUrl()}/api/v1/evaluation/debug-results`;
    const resp = await req.fetchWithTimeout(url, { method: 'GET' }, 15000);
    const results = Array.isArray(resp?.results) ? resp.results : [];
    debugResults.value = results;
    if (results.length && !selectedDebugResultId.value) {
      selectedDebugResultId.value = results[0].id;
    }
    if (!results.length) {
      selectedDebugResultId.value = '';
    }
    return results;
  }

  function selectDebugResult(resultId) {
    selectedDebugResultId.value = resultId || '';
  }

  async function loadSelectedDebugResult() {
    if (!activeDebugResult.value) {
      ui.toast('没有可加载的测试结果', 'error', 3000);
      return;
    }
    if (!req.begin(moduleId, '加载测试结果')) {
      ui.toast('当前有请求正在处理中，请稍候');
      return;
    }

    const controller = new AbortController();
    req.attachController(moduleId, controller);
    const item = activeDebugResult.value;
    const url = `${debugBaseUrl()}${item.json_url}`;

    try {
      requestMeta.value = `正在加载：${item.title || '测试结果'}`;
      const payload = await req.fetchWithTimeout(url, { method: 'GET' }, 20000, controller);
      const displayData = normalizePayload(payload);
      lastResult.value = { data: displayData };
      resultText.value = JSON.stringify(payload, null, 2);
      requestMeta.value = buildRequestMeta(item, payload);
      questionAnswer.value = '';
      questionCitations.value = [];
      ui.setTab(moduleId, 'result');
      hist.record({
        title: `${moduleConfig.value?.title || '智能评审'} - ${item.title || item.id}`,
        method: 'GET',
        url,
        ok: true,
      });
    } catch (error) {
      const msg = String(error || '加载失败');
      requestMeta.value = '加载失败';
      lastResult.value = null;
      resultText.value = msg;
      hist.record({
        title: `${moduleConfig.value?.title || '智能评审'} - ${item.title || item.id}`,
        method: 'GET',
        url,
        ok: false,
      });
      ui.toast(msg, 'error', 3000);
    } finally {
      req.end(moduleId);
    }
  }

  async function initialize() {
    try {
      await loadDebugResults();
      if (selectedDebugResultId.value) {
        await loadSelectedDebugResult();
      }
    } catch (error) {
      const msg = String(error || '初始化失败');
      ui.toast(msg, 'error', 3000);
    }
  }

  async function refreshDebugResults() {
    try {
      const previousId = selectedDebugResultId.value;
      await loadDebugResults();
      if (previousId && debugResults.value.some((item) => item.id === previousId)) {
        selectedDebugResultId.value = previousId;
      }
      ui.toast('结果列表已刷新');
    } catch (error) {
      ui.toast(String(error || '刷新失败'), 'error', 3000);
    }
  }

  async function submit() {
    await loadSelectedDebugResult();
  }

  async function askQuestion(questionText) {
    const question = String(questionText ?? questionDraft.value ?? '').trim();
    if (!question) {
      ui.toast('请输入要询问的问题');
      return;
    }
    if (!activeEvaluationId.value) {
      ui.toast('当前结果没有评审编号，无法发起问答', 'error', 3000);
      return;
    }
    if (!req.begin(moduleId, '专家问答')) {
      ui.toast('当前有请求正在处理中，请稍候');
      return;
    }

    const controller = new AbortController();
    req.attachController(moduleId, controller);
    const url = `${req.apiBase()}/evaluation/chat/ask`;

    try {
      const payload = await req.fetchWithTimeout(
        url,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ evaluation_id: activeEvaluationId.value, question }),
        },
        20000,
        controller,
      );
      questionAnswer.value = String(payload?.answer || '').trim();
      questionCitations.value = Array.isArray(payload?.citations) ? payload.citations : [];
      questionDraft.value = question;
      ui.toast('问答已完成');
      return payload;
    } catch (error) {
      const msg = String(error || '问答失败');
      questionAnswer.value = '';
      questionCitations.value = [];
      ui.toast(msg, 'error', 3000);
      return null;
    } finally {
      req.end(moduleId);
    }
  }

  function clearQuestionResult() {
    questionAnswer.value = '';
    questionCitations.value = [];
  }

  function stop() {
    if (req.stop(moduleId)) {
      ui.toast('已停止当前加载');
      return;
    }
    ui.toast('当前无进行中的加载任务');
  }

  function copyResult() {
    if (!req.hasText(resultText.value)) {
      ui.toast('当前没有可复制内容');
      return;
    }
    navigator.clipboard
      .writeText(resultText.value)
      .then(() => ui.toast('已复制到剪贴板'))
      .catch(() => ui.toast('复制失败'));
  }

  function clearResult() {
    requestMeta.value = '等待加载测试结果...';
    lastResult.value = null;
    resultText.value = '';
  }

  return {
    moduleId,
    moduleConfig,
    debugResults,
    selectedDebugResultId,
    activeDebugResult,
    debugPreviewUrl,
    lastResult,
    resultText,
    requestMeta,
    activeTab,
    requestInProgress,
    progressText,
    requestStartedAt,
    summaryItems,
    resultCards,
    isMarkdownReportPayload,
    activeEvaluationId,
    questionDraft,
    questionAnswer,
    questionCitations,
    setActiveTab,
    initialize,
    refreshDebugResults,
    selectDebugResult,
    loadSelectedDebugResult,
    submit,
    askQuestion,
    clearQuestionResult,
    stop,
    copyResult,
    clearResult,
  };
});