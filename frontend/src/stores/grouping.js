import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { MODULES } from '../config/modules';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

export const useGroupingStore = defineStore('grouping', () => {
  const moduleId = 'grouping';
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  const moduleConfig = computed(() => MODULES.find((m) => m.id === moduleId) || null);
  const activeActionId = ref(null);
  const formData = ref({});
  const files = ref({});

  const lastResult = ref(null);
  const fixedResults = ref([]);
  const resultText = ref('');
  const requestMeta = ref('等待处理...');
  const loadingFixedResult = ref(true);

  const activeAction = computed(() => {
    const m = moduleConfig.value;
    if (!m) return null;
    return m.actions.find((a) => a.id === activeActionId.value) || m.actions[0] || null;
  });

  const requestInProgress = computed(() => req.inProgressFor(moduleId));
  const progressText = computed(() => req.progressTextFor(moduleId));
  const requestStartedAt = computed(() => req.startedAtFor(moduleId));
  const activeTab = computed(() => ui.getTab(moduleId));

  function setActiveTab(tab) {
    ui.setTab(moduleId, tab);
  }

  function formatKey(key) {
    const k = String(key || '').trim();
    const map = {
      id: '编号',
      project_id: '项目编号',
      created_at: '创建时间',
      statistics: '统计信息',
      groups: '分组',
      matches: '匹配结果',
      report: '报告',
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
    const source = lastResult.value.data || lastResult.value;
    const keys = ['id', 'project_id', 'status'];
    const items = [];
    keys.forEach((k) => {
      if (source[k] !== undefined && source[k] !== null) {
        items.push({ k, v: String(source[k]) });
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

  function buildDefaultFormState() {
    const nextForm = {};
    const nextFiles = {};
    if (!activeAction.value) return { nextForm, nextFiles };
    activeAction.value.fields.forEach((field) => {
      if (field.type === 'checkbox') {
        nextForm[field.name] = Boolean(field.checked);
      } else if (field.type === 'multi-select') {
        nextForm[field.name] = Array.isArray(field.value) ? [...field.value] : [];
      } else if (field.type === 'file' || field.type === 'file-multi') {
        nextFiles[field.name] = field.type === 'file-multi' ? [] : null;
      } else {
        nextForm[field.name] = field.value || '';
      }
    });
    return { nextForm, nextFiles };
  }

  function initialize() {
    if (!moduleConfig.value) return;
    activeActionId.value = moduleConfig.value.actions[0]?.id || null;
    const { nextForm, nextFiles } = buildDefaultFormState();
    formData.value = nextForm;
    files.value = nextFiles;
  }

  async function loadFixedResults() {
    loadingFixedResult.value = true;
    requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 加载测试分组结果 | 处理中...`;
    try {
      const url = `${req.apiBase()}/grouping/debug/fixed-results`;
      const result = await req.fetchWithTimeout(url, { method: 'GET' }, 30000);
      const payload = (result && typeof result === 'object') ? (result.data || result) : null;
      const datasets = Array.isArray(payload?.datasets) ? payload.datasets : [];

      if (datasets.length) {
        fixedResults.value = datasets.map((item, idx) => ({
          key: item.key || `dataset_${idx + 1}`,
          title: item.title || item.filename || `分组结果 ${idx + 1}`,
          filename: item.filename || '',
          payload: item.payload || null,
        })).filter((x) => x.payload && typeof x.payload === 'object');
      } else {
        fixedResults.value = [];
      }

      if (fixedResults.value.length) {
        lastResult.value = { data: fixedResults.value[0].payload };
        resultText.value = '';
        requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 加载测试分组结果 | 成功`;
      } else {
        fixedResults.value = [];
        lastResult.value = null;
        resultText.value = '未获取到可展示的分组结果';
        requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 加载测试分组结果 | 失败`;
      }
    } catch (error) {
      const msg = String(error);
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 加载测试分组结果 | 失败`;
      fixedResults.value = [];
      lastResult.value = null;
      resultText.value = msg;
      ui.toast(msg, 'error', 3000);
    } finally {
      loadingFixedResult.value = false;
    }
  }

  function setAction(actionId) {
    activeActionId.value = actionId;
    const { nextForm, nextFiles } = buildDefaultFormState();
    formData.value = nextForm;
    files.value = nextFiles;
  }

  function onFileChange(field, inputFiles) {
    if (!inputFiles) return;
    if (field.type === 'file') {
      files.value[field.name] = inputFiles[0] || null;
    } else if (field.type === 'file-multi') {
      const existing = Array.isArray(files.value[field.name]) ? files.value[field.name] : [];
      const next = [...existing, ...inputFiles];
      const seen = new Set();
      files.value[field.name] = next.filter((f) => {
        const key = `${f.name}:${f.size}:${f.lastModified}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }
  }
  function onFileRemove(field, index = 0) {
    if (field.type === 'file') {
      files.value[field.name] = null;
      return;
    }
    const arr = Array.isArray(files.value[field.name]) ? files.value[field.name] : [];
    files.value[field.name] = arr.filter((_, i) => i !== index);
  }

  function fillExample() {
    const m = moduleConfig.value;
    if (!m || typeof m.fillExample !== 'function') return;
    m.fillExample((_actionId, fieldName, value) => {
      if (Object.prototype.hasOwnProperty.call(formData.value, fieldName)) {
        formData.value[fieldName] = value;
      }
    });
    ui.toast('示例参数已填充');
  }

  function validateForm() {
    if (!activeAction.value) return;
    for (const field of activeAction.value.fields) {
      if (!field.required) continue;
      if (field.type === 'file' && !files.value[field.name]) {
        throw new Error(`${field.label} 不能为空`);
      }
      if (field.type === 'file-multi' && (!files.value[field.name] || files.value[field.name].length < 2)) {
        throw new Error(`${field.label} 至少选择 2 个文件`);
      }
      if (field.type === 'multi-select' && (!Array.isArray(formData.value[field.name]) || formData.value[field.name].length === 0)) {
        throw new Error(`${field.label} 不能为空`);
      }
      if (!['file', 'file-multi', 'checkbox'].includes(field.type) && !req.hasText(formData.value[field.name])) {
        throw new Error(`${field.label} 不能为空`);
      }
    }
  }

  function resolveTimeoutMs(url, method = 'GET') {
    if (/\/grouping\/(projects|match|full)/.test(url)) return 180000;
    if (method === 'GET') return 60000;
    return 120000;
  }

  function showResult(actionTitle, payload, ok, elapsedMs = null) {
    requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${actionTitle} | ${ok ? '成功' : '失败'}`;
    lastResult.value = typeof payload === 'object' ? payload : null;
    resultText.value = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    ui.setTab(moduleId, 'result');
  }

  async function submit() {
    if (!activeAction.value) return;
    if (!req.begin(moduleId, activeAction.value.title)) {
      ui.toast('当前有请求正在处理中，请稍候');
      return;
    }
    requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${activeAction.value.title} | 处理中...`;

    let built = null;
    const controller = new AbortController();
    try {
      validateForm();
      built = activeAction.value.buildRequest(formData.value, files.value, req);
      const options = { method: built.method };
      if (built.headers) options.headers = built.headers;
      if (built.body !== undefined && built.body !== null) {
        const isJson = built.headers && built.headers['Content-Type'] === 'application/json';
        options.body = isJson && typeof built.body !== 'string' ? JSON.stringify(built.body) : built.body;
      }
      req.attachController(moduleId, controller);
      const timeoutMs = built.timeoutMs || resolveTimeoutMs(built.url, built.method);
      const result = await req.fetchWithTimeout(built.url, options, timeoutMs, controller);
      showResult(activeAction.value.title, result, true, Date.now() - requestStartedAt.value);
      hist.record({
        title: `${moduleConfig.value.title} - ${activeAction.value.title}`,
        method: built.method,
        url: built.url,
        ok: true,
      });
      ui.toast('处理成功');
    } catch (error) {
      const msg = String(error);
      showResult(activeAction.value?.title || '请求执行', msg, false, Date.now() - requestStartedAt.value);
      hist.record({
        title: `${moduleConfig.value?.title || '项目分组'} - ${activeAction.value?.title || '未知操作'}`,
        method: built?.method || 'POST',
        url: built?.url || '-',
        ok: false,
      });
      ui.toast(msg, 'error', 3000);
    } finally {
      req.end(moduleId);
    }
  }

  function stop() {
    if (req.stop(moduleId)) {
      ui.toast('已停止当前请求');
    } else {
      ui.toast('当前无进行中的请求');
    }
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
    requestMeta.value = '等待处理...';
    fixedResults.value = [];
    lastResult.value = null;
    resultText.value = '';
  }

  return {
    moduleId,
    moduleConfig,
    activeActionId,
    activeAction,
    formData,
    files,
    fixedResults,
    lastResult,
    resultText,
    requestMeta,
    loadingFixedResult,
    activeTab,
    requestInProgress,
    progressText,
    requestStartedAt,
    summaryItems,
    resultCards,
    isMarkdownReportPayload,
    setActiveTab,
    initialize,
    loadFixedResults,
    setAction,
    onFileChange,
    onFileRemove,
    fillExample,
    submit,
    stop,
    copyResult,
    clearResult,
  };
});
