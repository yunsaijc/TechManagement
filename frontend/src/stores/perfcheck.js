import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { MODULES } from '../config/modules';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

export const usePerfcheckStore = defineStore('perfcheck', () => {
  const moduleId = 'perfcheck';
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  function fileSignature(file) {
    if (!file) return '';
    const name = file.name || '';
    const size = Number.isFinite(file.size) ? file.size : '';
    const lastModified = Number.isFinite(file.lastModified) ? file.lastModified : '';
    return `${name}:${size}:${lastModified}`;
  }


  function isTaskNotFoundError(error) {
    const msg = String(error || '');
    if (msg.includes('404')) return true;
    if (msg.includes('不存在') && msg.includes('任务')) return true;
    if (msg.includes('"detail"') && msg.includes('不存在')) return true;
    return false;
  }

  const moduleConfig = computed(() => MODULES.find((m) => m.id === moduleId) || null);
  const activeActionId = ref(null);
  const formData = ref({});
  const files = ref({});
  const fixedResults = ref([]);
  const selectedFixedResultId = ref('');
  const fixedResultsLoading = ref(false);

  const lastResult = ref(null);
  const resultText = ref('');
  const requestMeta = ref('等待处理...');

  const activeAction = computed(() => {
    const m = moduleConfig.value;
    if (!m) return null;
    return m.actions.find((a) => a.id === activeActionId.value) || m.actions[0] || null;
  });

  const requestInProgress = computed(() => req.inProgressFor(moduleId));
  const progressText = computed(() => req.progressTextFor(moduleId));
  const requestStartedAt = computed(() => req.startedAtFor(moduleId));
  const activeTab = computed(() => ui.getTab(moduleId));
  const selectedFixedResult = computed(() => fixedResults.value.find((item) => item.project_id === selectedFixedResultId.value) || null);

  function buildFixedResultLabel(item) {
    if (!item) return '';
    const projectId = String(item.project_id || '').trim();
    const taskId = String(item.task_id || '').trim();
    if (projectId && taskId) return `${projectId}${taskId}`;
    return projectId || taskId || '未命名结果';
  }

  function setActiveTab(tab) {
    ui.setTab(moduleId, tab);
  }

  function formatKey(key) {
    const k = String(key || '').trim();
    const map = {
      task_id: '任务编号',
      project_id: '项目编号',
      state: '状态',
      progress: '进度',
      stage: '阶段',
      message: '消息',
      summary: '总结',
      warnings: '警告',
      metrics_risks: '指标差异',
      content_risks: '内容差异',
      budget_risks: '预算差异',
      other_risks: '其他差异',
      unit_budget_risks: '分单位预算差异',
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
    const keys = ['task_id', 'project_id', 'state', 'progress', 'stage'];
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

  const isMarkdownReportPayload = computed(() => Boolean(
    lastResult.value
    && typeof lastResult.value === 'object'
    && typeof lastResult.value.data === 'string'
    && activeAction.value
    && activeAction.value.id === 'perfcheck_report',
  ));

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
    ui.setTab(moduleId, 'result');
    void loadFixedResults();
  }

  async function loadFixedResults() {
    if (fixedResultsLoading.value) return;
    fixedResultsLoading.value = true;
    const url = `${req.apiBase()}/perfcheck/debug-fixed-results`;
    try {
      const payload = await req.fetchWithTimeout(url, { method: 'GET' }, 20000);
      const list = Array.isArray(payload?.data) ? payload.data : (Array.isArray(payload) ? payload : []);
      fixedResults.value = list;
      if (!selectedFixedResultId.value || !list.some((item) => item.project_id === selectedFixedResultId.value)) {
        selectedFixedResultId.value = list[0]?.project_id || '';
      }
      if (selectedFixedResultId.value) {
        await loadFixedDebugResult(selectedFixedResultId.value);
      }
    } catch (error) {
      const msg = String(error || '加载固定核验结果清单失败');
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 固定核验结果 | 失败`;
      lastResult.value = null;
      resultText.value = msg;
      ui.toast(msg, 'error', 3000);
    } finally {
      fixedResultsLoading.value = false;
    }
  }

  async function loadFixedDebugResult(projectId = selectedFixedResultId.value) {
    const normalizedProjectId = String(projectId || '').trim();
    if (!normalizedProjectId) return;
    if (!req.begin(moduleId, '加载固定核验结果')) {
      return;
    }

    const controller = new AbortController();
    req.attachController(moduleId, controller);
    const url = `${req.apiBase()}/perfcheck/debug-fixed-result/by-project?project_id=${encodeURIComponent(normalizedProjectId)}`;

    try {
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 固定核验结果 ${normalizedProjectId} | 加载中...`;
      const payload = await req.fetchWithTimeout(url, { method: 'GET' }, 20000, controller);
      const data = (payload && typeof payload === 'object' && payload.data && typeof payload.data === 'object')
        ? payload.data
        : payload;
      lastResult.value = { data };
      resultText.value = JSON.stringify(payload, null, 2);
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 固定核验结果 ${normalizedProjectId} | 成功`;
      ui.setTab(moduleId, 'result');
      hist.record({
        title: `${moduleConfig.value?.title || '核验对比'} - ${normalizedProjectId}`,
        method: 'GET',
        url,
        ok: true,
      });
    } catch (error) {
      const msg = String(error || '加载固定核验结果失败');
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] 固定核验结果 ${normalizedProjectId} | 失败`;
      lastResult.value = null;
      resultText.value = msg;
      hist.record({
        title: `${moduleConfig.value?.title || '核验对比'} - ${normalizedProjectId}`,
        method: 'GET',
        url,
        ok: false,
      });
      ui.toast(msg, 'error', 3000);
    } finally {
      req.end(moduleId);
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

  function extractTaskId(payload) {
    if (!payload || typeof payload !== 'object') return '';
    if (req.hasText(payload.task_id)) return payload.task_id;
    if (payload.data && typeof payload.data === 'object' && req.hasText(payload.data.task_id)) {
      return payload.data.task_id;
    }
    return '';
  }

  function buildTaskMeta(task) {
    try {
      const state = String(task?.state || '').toLowerCase();
      if (state === 'finished') return '核验完成';
      if (state === 'failed') return '核验失败';
      return '核验进行中';
    } catch {
      return '核验进行中';
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function fetchTaskOnce(taskId) {
    const url = `${req.apiBase()}/perfcheck/${encodeURIComponent(taskId)}`;
    const resp = await req.fetchWithTimeout(url, { method: 'GET' }, 20000);
    return (resp && resp.data) ? resp.data : resp;
  }

  async function pollTask(taskId) {
    if (!req.hasText(taskId)) return;
    const baseTitle = moduleConfig.value ? `${moduleConfig.value.title} - 查询核验进度` : '查询核验进度';
    let attempts = 0;
    const maxAttempts = 180;
    while (attempts < maxAttempts) {
      attempts += 1;
      try {
        const task = await fetchTaskOnce(taskId);
        if (task && typeof task === 'object') {
          lastResult.value = { data: task };
          requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${baseTitle} | ${buildTaskMeta(task)}`;
          ui.setTab(moduleId, 'result');
          if (task.state === 'finished') {
            ui.toast('核验完成');
            return;
          }
          if (task.state === 'failed') {
            ui.toast('核验失败', 'error', 3000);
            return;
          }
        }
      } catch (error) {
        if (isTaskNotFoundError(error)) {
          ui.toast('任务不存在（服务重启或已清理），请重新提交核验', 'error', 3000);
          return;
        }
      }
      await sleep(3000);
    }
    ui.toast('进度跟踪超时，可手动点击“查询核验进度”继续查看', 'error', 3000);
  }

  function resolveTimeoutMs(url, method = 'GET') {
    if (/\/perfcheck\/compare/.test(url)) return 240000;
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
    await loadFixedDebugResult(selectedFixedResultId.value);
  }

  async function selectFixedResult(projectId) {
    selectedFixedResultId.value = String(projectId || '').trim();
    await loadFixedDebugResult(selectedFixedResultId.value);
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
    fixedResults,
    selectedFixedResultId,
    selectedFixedResult,
    fixedResultsLoading,
    setActiveTab,
    initialize,
    setAction,
    onFileChange,
    onFileRemove,
    fillExample,
    submit,
    stop,
    copyResult,
    clearResult,
    pollTask,
    loadFixedDebugResult,
    loadFixedResults,
    selectFixedResult,
    buildFixedResultLabel,
  };
});
