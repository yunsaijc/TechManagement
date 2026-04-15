import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { MODULES } from '../config/modules';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

export const useLogiconStore = defineStore('logicon', () => {
  const moduleId = 'logicon';
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  const moduleConfig = computed(() => MODULES.find((m) => m.id === moduleId) || null);
  const activeActionId = ref(null);
  const formData = ref({});
  const files = ref({});

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

  function setActiveTab(tab) {
    ui.setTab(moduleId, tab);
  }

  function formatKey(key) {
    const k = String(key || '').trim();
    const map = {
      task_id: '任务编号',
      doc_id: '文档编号',
      doc_kind: '文档类型',
      partial: '降级模式',
      conflicts: '冲突列表',
      severity: '级别',
      category: '类别',
      title: '标题',
      description: '说明',
      evidence: '证据',
      page: '页码',
      section_title: '章节',
      snippet: '片段',
      warnings: '警告',
      rule_snapshot: '规则快照',
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
    return [];
  });

  function shortDocId(val) {
    const s = String(val || '').trim();
    if (!s) return '-';
    const parts = s.split('_').filter(Boolean);
    const tail = parts.length ? parts[parts.length - 1] : s;
    if (tail.length >= 8) return tail.slice(-8);
    return s.length >= 8 ? s.slice(-8) : s;
  }

  function zhDocKind(val) {
    const s = String(val || '').trim().toLowerCase();
    const map = { declaration: '申报书', task: '任务书', unknown: '未知', auto: '自动识别' };
    return map[s] || (s ? s : '-');
  }

  function zhSeverity(val) {
    const s = String(val || '').trim().toUpperCase();
    const map = { RED: '严重', YELLOW: '提示', GREEN: '正常' };
    return map[s] || (s ? s : '提示');
  }

  function zhCategory(val) {
    const s = String(val || '').trim().toUpperCase();
    const map = {
      TIME_SPAN: '执行期与进度跨度',
      BUDGET_SUM: '预算算不平',
      BUDGET_TOTAL: '预算算不平',
      METRIC_VALUE: '指标一致性',
      METRIC_UNIT: '指标一致性',
      ORG_ROLE: '组织/角色',
      PERSON_ROLE: '人员/角色',
      OTHER: '其他',
    };
    return map[s] || (s ? s : '其他');
  }

  function zhEntityType(t) {
    const s = String(t || '').trim();
    const map = {
      time_exec_period: '执行期',
      time_progress: '进度安排',
      budget_total: '预算总额',
      budget_items: '预算明细',
      metric: '指标',
    };
    return map[s] || '其他';
  }
  function summarizeSeverity(conflicts) {
    const levels = { RED: 0, YELLOW: 0, GREEN: 0 };
    (conflicts || []).forEach((c) => {
      const sev = String(c?.severity || '').toUpperCase();
      if (levels[sev] !== undefined) levels[sev] += 1;
    });
    return levels;
  }

  function truncate(text, maxLen = 80) {
    const s = String(text || '').replace(/\s+/g, ' ').trim();
    if (!s) return '-';
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen)}…`;
  }

  function firstEvidence(conflict) {
    const ev = conflict?.evidence;
    if (!Array.isArray(ev) || !ev.length) return '';
    const e0 = ev[0] || {};
    const page = e0.page ? `页${e0.page}` : '';
    const sec = e0.section_title ? String(e0.section_title) : '';
    const head = [page, sec].filter(Boolean).join(' ');
    const snippet = truncate(e0.snippet || '', 90);
    return head ? `${head}：${snippet}` : snippet;
  }

  function formatEvidenceItem(e) {
    if (!e || typeof e !== 'object') return '-';
    const page = e.page ? `页${e.page}` : '';
    const sec = e.section_title ? String(e.section_title) : '';
    const head = [page, sec].filter(Boolean).join(' ');
    const snippet = truncate(slimEvidenceSnippet(sec, e.snippet || ''), 160);
    if (head && snippet !== '-') return `${head}：${snippet}`;
    if (head) return head;
    return snippet;
  }

  function parseYearMonth(text) {
    const s = String(text || '').trim();
    const m = s.match(/(20\d{2})\s*[年./-]\s*(\d{1,2})/);
    if (!m) return null;
    const y = Number(m[1]);
    const mm = Number(m[2]);
    if (!Number.isFinite(y) || !Number.isFinite(mm)) return null;
    if (mm < 1 || mm > 12) return null;
    return { y, m: mm, v: y * 12 + mm };
  }

  function pickLatestRange(text) {
    const s = String(text || '');
    const ranges = [];
    const re = /(20\d{2})\s*年\s*(\d{1,2})\s*月\s*[-—~至到]\s*(20\d{2})\s*年\s*(\d{1,2})\s*月/g;
    let m;
    while ((m = re.exec(s)) !== null) {
      const y2 = Number(m[3]);
      const mo2 = Number(m[4]);
      if (!Number.isFinite(y2) || !Number.isFinite(mo2)) continue;
      ranges.push({ text: m[0], end: y2 * 12 + mo2 });
    }
    if (!ranges.length) return '';
    ranges.sort((a, b) => b.end - a.end);
    return ranges[0].text;
  }

  function extractBetween(text, startKey, endKeys) {
    const s = String(text || '');
    const idx = s.indexOf(startKey);
    if (idx < 0) return '';
    const after = s.slice(idx);
    let end = after.length;
    (endKeys || []).forEach((k) => {
      const j = after.indexOf(k);
      if (j > 0 && j < end) end = j;
    });
    return after.slice(0, end).trim();
  }

  function extractBudgetLines(snippet) {
    const raw = String(snippet || '');
    const s = raw.replace(/\[表格行\d+\]\s*/g, '').replace(/\[表格表头\d+\]\s*/g, '').replace(/\[表格标题\d+\]\s*/g, '');
    const lines = s.split('\n').map((x) => x.trim()).filter(Boolean);
    if (!lines.length) return '';
    const keep = [];
    const keyRules = [
      /预算科目名称:.*直接费用.*金额:\s*\d/i,
      /预算科目名称:.*设备费.*金额:\s*\d/i,
      /预算科目名称:.*业务费.*金额:\s*\d/i,
      /预算科目名称:.*劳务费.*金额:\s*\d/i,
      /预算科目名称:.*合\s*计.*金额:\s*\d/i,
      /经费预算明细表\/合计:\s*\d/i,
      /\/合计:\s*\d/i,
    ];
    lines.forEach((ln) => {
      const cleaned = ln.replace(/\s*;\s*/g, '；').replace(/\s*\|\s*/g, ' | ').trim();
      if (keyRules.some((r) => r.test(cleaned))) keep.push(cleaned);
    });
    const out = (keep.length ? keep : lines.slice(0, 6)).slice(0, 6);
    return out.join('；');
  }

  function slimEvidenceSnippet(sectionTitle, snippet) {
    const sec = String(sectionTitle || '').trim();
    const s = String(snippet || '').replace(/\s+/g, ' ').trim();
    if (!s) return '';

    if (sec.includes('基本信息')) {
      const seg = extractBetween(s, '项目起止年月', ['承担单位', '合作单位', '开户', '账号', '负责人', '联系人']);
      if (seg) return seg;
      const seg2 = extractBetween(s, '项 目 起 止 年 月', ['承担单位', '合作单位', '开户', '账号', '负责人', '联系人']);
      if (seg2) return seg2;
      return s;
    }

    if (sec.includes('进度')) {
      const latest = pickLatestRange(s);
      if (latest) return latest;
      return s;
    }

    if (sec.includes('预算')) {
      const budget = extractBudgetLines(snippet);
      if (budget) return budget;
      return s;
    }

    return s;
  }

  function filterWarnings(warnings) {
    if (!Array.isArray(warnings)) return [];
    return warnings.filter((w) => {
      const s = String(w || '');
      if (!s.trim()) return false;
      if (s.startsWith('调试结果已保存')) return false;
      if (s.startsWith('调试结果保存失败')) return false;
      return true;
    });
  }

  const resultCards = computed(() => {
    if (!lastResult.value || typeof lastResult.value !== 'object') return [];
    const source = (lastResult.value.data && typeof lastResult.value.data === 'object') ? lastResult.value.data : lastResult.value;
    const cards = [];
    const conflicts = Array.isArray(source.conflicts) ? source.conflicts : [];
    const warnings = filterWarnings(source.warnings);

    const severity = summarizeSeverity(conflicts);
    cards.push({
      title: '核验结论',
      rows: [
        { label: '文档编号', value: shortDocId(source.doc_id) },
        { label: '文档类型', value: zhDocKind(source.doc_kind) },
        { label: '冲突条数', value: String(conflicts.length) },
        { label: '严重冲突', value: String(severity.RED) },
      ],
    });

    const timeConflicts = conflicts.filter((c) => String(c?.category || '') === 'TIME_SPAN');
    const budgetConflicts = conflicts.filter((c) => ['BUDGET_SUM', 'BUDGET_TOTAL'].includes(String(c?.category || '')));
    const metricConflicts = conflicts.filter((c) => ['METRIC_VALUE', 'METRIC_UNIT'].includes(String(c?.category || '')));

    const timeStatus = timeConflicts.length ? `发现 ${timeConflicts.length} 条冲突` : (warnings.some((w) => String(w).includes('执行期') || String(w).includes('进度安排')) ? '信息不足（建议复核）' : '未发现明显冲突');
    const budgetStatus = budgetConflicts.length ? `发现 ${budgetConflicts.length} 条冲突` : (warnings.some((w) => String(w).includes('预算')) ? '信息不足（建议复核）' : '未发现明显冲突');
    const metricStatus = metricConflicts.length ? `发现 ${metricConflicts.length} 条冲突` : (warnings.some((w) => String(w).includes('指标')) ? '信息不足（建议复核）' : '未发现明显冲突');

    cards.push({
      title: '检查项结果',
      rows: [
        { label: '执行期/进度跨度', value: timeStatus },
        { label: '预算算不平', value: budgetStatus },
        { label: '指标一致性', value: metricStatus },
      ],
    });

    if (conflicts.length) {
      conflicts.slice(0, 8).forEach((c, idx) => {
        const evidence = Array.isArray(c?.evidence) ? c.evidence : [];
        const evidenceRows = evidence.slice(0, 3).map((e, i) => ({
          label: `证据 ${i + 1}`,
          value: formatEvidenceItem(e),
        }));
        if (!evidenceRows.length) {
          evidenceRows.push({ label: '证据', value: '未提供可定位证据片段。' });
        }

        cards.push({
          title: `冲突 ${idx + 1}｜${zhCategory(c.category)}｜${zhSeverity(c.severity)}`,
          rows: [
            { label: '问题', value: truncate(c.title || '', 140) },
            { label: '说明', value: truncate(c.description || '', 240) },
            ...evidenceRows,
          ],
        });
      });
    } else {
      cards.push({
        title: '冲突详情',
        rows: [
          { label: '结论', value: '未检测到可确定的冲突条目。' },
        ],
      });
    }

    if (source.graph && typeof source.graph === 'object' && Array.isArray(source.graph.entities) && source.graph.entities.length) {
      const ents = source.graph.entities;
      const byType = {};
      ents.forEach((e) => {
        const k = String(e?.entity_type || 'other');
        byType[k] = (byType[k] || 0) + 1;
      });
      const typeRows = Object.entries(byType)
        .slice(0, 6)
        .map(([k, v]) => `${zhEntityType(k)}：${v}`);
      const header = typeRows.length ? typeRows.join(' ｜ ') : `节点数：${ents.length}`;

      const sample = ents.slice(0, 6).map((e, i) => {
        const t = zhEntityType(e?.entity_type);
        const name = e?.name ? String(e.name) : '';
        const norm = (e?.normalized && typeof e.normalized === 'object')
          ? Object.entries(e.normalized).slice(0, 2).map(([k, v]) => `${formatKey(k)}=${toDisplayText(v)}`).join('；')
          : '';
        const ev = Array.isArray(e?.spans) && e.spans.length ? formatEvidenceItem(e.spans[0]) : '';
        const value = [name, norm, ev].filter(Boolean).join(' ｜ ');
        return { label: `节点 ${i + 1}（${t}）`, value: truncate(value, 180) || '-' };
      });

      cards.push({
        title: '文档图谱（开发）',
        rows: [{ label: '概览', value: header }, ...sample],
      });
    }

    return cards.slice(0, 8);
  });

  const isMarkdownReportPayload = computed(() => false);

  const hasGraph = computed(() => {
    const source = (lastResult.value && lastResult.value.data) ? lastResult.value.data : lastResult.value;
    return !!(source && source.graph && Array.isArray(source.graph.entities) && source.graph.entities.length);
  });

  const graphNodes = computed(() => {
    const source = (lastResult.value && lastResult.value.data) ? lastResult.value.data : lastResult.value;
    const ents = (source && source.graph && Array.isArray(source.graph.entities)) ? source.graph.entities : [];
    return ents.slice(0, 60).map((e) => {
      let label = zhEntityType(e?.entity_type);
      let evidence = Array.isArray(e?.spans) && e.spans.length ? formatEvidenceItem(e.spans[0]) : '';
      if (e?.entity_type === 'time_exec_period') {
        const s = e?.normalized || {};
        const parts = [];
        if (s.start_ym && s.end_ym) parts.push('起止:已抽取');
        if (s.duration_months) parts.push(`时长:${Math.round(Number(s.duration_months) / 12)}年`);
        if (parts.length) label = `${label}｜${parts.join(' ')}`;
      } else if (e?.entity_type === 'time_progress') {
        label = `${label}｜节点:已抽取`;
      } else if (e?.entity_type === 'budget_total') {
        const amt = e?.normalized?.amount_wan;
        if (amt !== undefined) label = `${label}｜${Number(amt).toFixed(2)} 万`;
      } else if (e?.entity_type === 'budget_items') {
        const sum = e?.normalized?.sum_wan;
        if (sum !== undefined) label = `${label}｜合计 ${Number(sum).toFixed(2)} 万`;
      } else if (e?.entity_type === 'metric') {
        const unit = e?.normalized?.unit || '';
        label = e?.name ? `${e.name} ${unit}` : `${label}`;
      } else if (e?.name) {
        label = `${label}｜${e.name}`;
      }
      return { id: e?.entity_id || Math.random().toString(36).slice(2), label, type: e?.entity_type || 'other', evidence };
    });
  });

  const graphEdges = computed(() => {
    const source = (lastResult.value && lastResult.value.data) ? lastResult.value.data : lastResult.value;
    const ents = (source && source.graph && Array.isArray(source.graph.entities)) ? source.graph.entities : [];
    const byType = {};
    ents.forEach((e) => {
      const t = e?.entity_type || 'other';
      byType[t] = byType[t] || [];
      byType[t].push(e);
    });
    const idOf = (arr) => (arr && arr[0] && arr[0].entity_id) ? arr[0].entity_id : null;
    const edges = [];
    const exec = idOf(byType.time_exec_period);
    const prog = idOf(byType.time_progress);
    if (exec && prog) edges.push({ source: exec, target: prog });
    const btot = idOf(byType.budget_total);
    const bitems = idOf(byType.budget_items);
    if (btot && bitems) edges.push({ source: btot, target: bitems });
    const metrics = byType.metric || [];
    metrics.slice(0, 3).forEach((m) => {
      if (btot) edges.push({ source: btot, target: m.entity_id });
    });
    if (source && source.graph && Array.isArray(source.graph.edges) && source.graph.edges.length) {
      source.graph.edges.slice(0, 20).forEach((e) => {
        if (e && e.source_id && e.target_id) edges.push({ source: e.source_id, target: e.target_id });
      });
    }
    return edges.slice(0, 40);
  });

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
      if (field.type === 'file-multi' && (!files.value[field.name] || files.value[field.name].length === 0)) {
        throw new Error(`${field.label} 不能为空`);
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

  async function pollTask(taskId) {
    const action = activeAction.value;
    const poll = action?.api?.polling;
    if (!poll || !req.hasText(taskId)) return;
    const pollUrl = `${req.apiBase()}${String(poll.path || '').replace('{task_id}', taskId)}`;
    const started = Date.now();

    for (let attempt = 0; attempt < 90; attempt += 1) {
      await sleep(1200);
      try {
        const data = await req.fetchWithTimeout(pollUrl, { method: poll.method || 'GET' }, 60000);
        const payload = data?.data || data;
        const state = String(payload?.state || '').toLowerCase();
        requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${activeAction.value?.title || '查询任务'} | ${buildTaskMeta(payload)}`;
        lastResult.value = data;
        resultText.value = JSON.stringify(data, null, 2);

        if (state === 'finished' && payload?.result) {
          lastResult.value = { ...data, data: payload.result };
          resultText.value = JSON.stringify(payload.result, null, 2);
          ui.toast(`核验完成（用时 ${Math.round((Date.now() - started) / 1000)}s）`);
          return;
        }
        if (state === 'failed') {
          ui.toast('核验失败', 'error', 3000);
          return;
        }
      } catch (e) {
        if (attempt >= 5) return;
      }
    }
  }

  function resolveTimeoutMs(url, method = 'GET') {
    if (/\/logicon\/check/.test(url)) return 120000;
    if (method === 'GET') return 60000;
    return 90000;
  }

  function showResult(actionTitle, payload, ok) {
    requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${actionTitle} | ${ok ? '成功' : '失败'}`;
    lastResult.value = typeof payload === 'object' ? payload : null;
    resultText.value = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    ui.setTab(moduleId, 'result');
  }

  async function submit() {
    if (!activeAction.value) return;
    let built = null;
    const controller = new AbortController();
    const actionTitle = activeAction.value.title;
    try {
      validateForm();
      if (!req.begin(moduleId, actionTitle)) {
        ui.toast('当前有请求正在处理中，请稍候');
        return;
      }
      requestMeta.value = `[${new Date().toLocaleString('zh-CN')}] ${actionTitle} | 处理中...`;
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
      showResult(actionTitle, result, true);
      hist.record({
        title: `${moduleConfig.value.title} - ${actionTitle}`,
        method: built.method,
        url: built.url,
        ok: true,
      });
      ui.toast('处理成功');

      const taskId = extractTaskId(result);
      const isTaskPayload = result && result.data && typeof result.data === 'object' && typeof result.data.state === 'string';
      if (isTaskPayload && req.hasText(taskId)) {
        ui.toast('任务已提交，正在自动跟踪进度');
        pollTask(taskId);
      }
    } catch (error) {
      const msg = String(error);
      showResult(actionTitle || '请求执行', msg, false);
      hist.record({
        title: `${moduleConfig.value?.title || ''} - ${actionTitle || '未知操作'}`,
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
    hasGraph,
    graphNodes,
    graphEdges,
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
  };
});
