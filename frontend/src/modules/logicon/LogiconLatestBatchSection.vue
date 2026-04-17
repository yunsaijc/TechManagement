<script setup>
import { onMounted, ref } from 'vue';
import { useRequestStore } from '../../stores/request';

const req = useRequestStore();
const loading = ref(false);
const errorText = ref('');
const batch = ref(null);
const expandedStem = ref('');
const docViewByStem = ref({});

async function load() {
  loading.value = true;
  errorText.value = '';
  try {
    const url = `${req.apiBase()}/logicon/debug-reports/latest`;
    const parsed = await req.fetchWithTimeout(url, { method: 'GET' }, 60000);
    if (parsed && parsed.status && parsed.status !== 'success') {
      throw new Error(parsed.message || '接口返回失败');
    }
    batch.value = parsed?.data ?? null;
  } catch (e) {
    errorText.value = String(e?.message || e);
    batch.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function toggleStem(stem) {
  const next = expandedStem.value === stem ? '' : stem;
  expandedStem.value = next;
  if (next && !docViewByStem.value[next]) {
    docViewByStem.value[next] = 'all';
  }
}

function setDocView(stem, view) {
  if (!stem) return;
  docViewByStem.value[stem] = view || 'all';
}

function docView(stem) {
  if (!stem) return 'all';
  return docViewByStem.value[stem] || 'all';
}

function filteredDocs(row) {
  const all = [row?.declaration, row?.task].filter(Boolean);
  const view = docView(row?.stem);
  if (view === 'declaration') return all.filter((d) => d.doc_kind === 'declaration');
  if (view === 'task') return all.filter((d) => d.doc_kind === 'task');
  return all;
}

function maxSeverity(doc) {
  if (!doc?.conflicts?.length) return 'GREEN';
  const order = { RED: 3, YELLOW: 2, GREEN: 1 };
  let m = 1;
  for (const c of doc.conflicts || []) {
    const s = order[c.severity] || 1;
    if (s > m) m = s;
  }
  if (m >= 3) return 'RED';
  if (m === 2) return 'YELLOW';
  return 'GREEN';
}

function severityClass(sev) {
  if (sev === 'RED') return 'sev-red';
  if (sev === 'YELLOW') return 'sev-yellow';
  return 'sev-green';
}

function outcomeLabel(o) {
  if (o === 'consistent') return '一致';
  if (o === 'inconsistent') return '矛盾';
  return '不足';
}

function outcomeClass(o) {
  if (o === 'inconsistent') return 'out-bad';
  if (o === 'consistent') return 'out-ok';
  return 'out-warn';
}

function docKindLabel(kind) {
  if (kind === 'declaration') return '申报书';
  if (kind === 'task') return '任务书';
  return kind || '-';
}

function conflictCount(doc) {
  return doc?.conflicts?.length ?? 0;
}

/** 卡片标题处「申报书/任务书 · N 条冲突」：无冲突绿、有冲突红 */
function conflictPillClass(doc) {
  return conflictCount(doc) > 0 ? 'doc-pill-bad' : 'doc-pill-ok';
}

function evidenceMeta(ev) {
  const p = ev?.page;
  const hasPage = p !== undefined && p !== null && String(p).trim() !== '';
  const page = hasPage ? `第 ${p} 页` : '页码未知';
  const sec = (ev?.section_title && String(ev.section_title).trim()) || '';
  return sec ? `${page} · ${sec}` : page;
}

function snippetPreview(text, limit = 160) {
  const s = String(text || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!s) return '';
  if (s.length <= limit) return s;
  return `${s.slice(0, limit)}…`;
}

function snippetPretty(text, limit = 420) {
  let s = String(text || '');
  if (!s) return '';
  s = s.replace(/\[表格表头\d+\]/g, '');
  s = s.replace(/\s+/g, ' ').trim();
  // 断行增强可读性：表格/预算串用 ; | 。 做软分段
  s = s
    .replace(/[；;]\s*/g, '；\n')
    .replace(/。\s*/g, '。\n')
    .replace(/\s*\|\s*/g, ' |\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (s.length <= limit) return s;
  return `${s.slice(0, limit)}…`;
}

function dimensionEvidencePairs(d) {
  const lines = Array.isArray(d?.detail_lines) ? d.detail_lines : [];
  const out = [];
  let lastMeta = '';
  for (let i = 0; i < lines.length; i++) {
    const raw = String(lines[i] || '').trim();
    const m1 = raw.match(/证据（(.+?)）/);
    if (m1) {
      lastMeta = m1[1].trim();
      continue;
    }
    const m2 = raw.match(/摘录：`([^`]+)`/);
    if (m2) {
      const sn = m2[1].trim();
      if (sn) out.push({ meta: lastMeta || '', snippet: sn });
      if (out.length >= 4) break;
    }
  }
  if (out.length) return out;
  // 兜底：有些维度只在文本块里出现 ```text ... ```，取前几段当“短摘录”
  const nodes = parseDetailLines(lines);
  for (const n of nodes) {
    if (n.type !== 'code') continue;
    const body = String(n.content || '').trim();
    if (!body) continue;
    out.push({ meta: '', snippet: body });
    if (out.length >= 2) break;
  }
  return out;
}

/** 将 **粗体** 拆成片段，避免 v-html */
function splitInlineBold(text) {
  const s = String(text ?? '');
  if (!s) return [{ bold: false, text: '' }];
  const out = [];
  const re = /\*\*(.+?)\*\*/g;
  let last = 0;
  let m = re.exec(s);
  while (m) {
    if (m.index > last) out.push({ bold: false, text: s.slice(last, m.index) });
    out.push({ bold: true, text: m[1] });
    last = m.index + m[0].length;
    m = re.exec(s);
  }
  out.push({ bold: false, text: s.slice(last) });
  return out;
}

function parseDetailLines(lines) {
  if (!lines || !Array.isArray(lines)) return [];
  const nodes = [];
  for (let i = 0; i < lines.length; i++) {
    const line = String(lines[i]).replace(/\r$/, '');
    const trimmed = line.trim();
    if (trimmed === '') {
      nodes.push({ type: 'spacer' });
      continue;
    }
    if (trimmed.startsWith('#### ')) {
      nodes.push({ type: 'h4', text: trimmed.slice(5).trim() });
      continue;
    }
    if (/^\s*```(?:text)?\s*$/.test(trimmed)) {
      i += 1;
      const codeBody = [];
      while (i < lines.length && String(lines[i]).trim() !== '```') {
        let cl = String(lines[i]);
        if (cl.startsWith('  ')) cl = cl.slice(2);
        codeBody.push(cl);
        i += 1;
      }
      nodes.push({ type: 'code', content: codeBody.join('\n').trimEnd() });
      continue;
    }
    const bulletMatch = trimmed.match(/^-\s+(.*)$/);
    if (bulletMatch) {
      const indent = line.length - line.trimStart().length;
      nodes.push({ type: 'bullet', text: bulletMatch[1], nested: indent >= 2 });
      continue;
    }
    nodes.push({ type: 'text', text: trimmed });
  }
  return nodes;
}

function isCollapsibleSectionTitle(title, ruleId) {
  if (!title) return false;
  if (/③|④[^」]{0,12}摘录|原文摘录|摘录（便于/.test(title)) return true;
  if (ruleId === 'R-METRIC-01' && /^「/.test(title)) return false;
  return false;
}

function foldSummaryLabel(g) {
  const nCode = g.nodes?.filter((x) => x.type === 'code').length ?? 0;
  const t = g.title || '摘录与片段';
  const short = t.length > 40 ? `${t.slice(0, 40)}…` : t;
  return nCode ? `展开：${short}（${nCode} 段）` : `展开：${short}`;
}

function groupDimensionDetail(lines, ruleId) {
  const nodes = parseDetailLines(lines);
  const groups = [];
  let cur = { title: null, collapsible: false, nodes: [] };

  const flush = () => {
    if (cur.title !== null || cur.nodes.length) {
      groups.push({ ...cur });
    }
  };

  for (const n of nodes) {
    if (n.type === 'h4') {
      flush();
      const title = n.text;
      cur = {
        title,
        collapsible: isCollapsibleSectionTitle(title, ruleId),
        nodes: [],
      };
    } else {
      cur.nodes.push(n);
    }
  }
  flush();
  return groups;
}

function splitByFirstColon(text) {
  const s = plainLine(text || '');
  const i1 = s.indexOf('：');
  const i2 = s.indexOf(':');
  const i = i1 >= 0 && i2 >= 0 ? Math.min(i1, i2) : Math.max(i1, i2);
  if (i <= 0) return null;
  return { k: s.slice(0, i).trim(), v: s.slice(i + 1).trim() };
}

function metricOverviewText(lines) {
  const groups = groupDimensionDetail(lines || [], 'R-METRIC-01');
  const g = groups.find((x) => plainLine(x.title || '').includes('总览'));
  if (!g) return '';
  for (const node of g.nodes || []) {
    if (node.type !== 'bullet' && node.type !== 'text') continue;
    const t = plainLine(node.text || '');
    if (t) return t;
  }
  return '';
}

function metricCards(lines) {
  const groups = groupDimensionDetail(lines || [], 'R-METRIC-01');
  const out = [];
  for (const g of groups) {
    const title = plainLine(g.title || '');
    if (!/^「.+」/.test(title)) continue;
    const items = [];
    for (const node of g.nodes || []) {
      if (node.type === 'spacer') continue;
      if (node.type === 'code') {
        if (node.content?.trim()) items.push({ type: 'code', content: node.content });
        continue;
      }
      if (node.type !== 'bullet' && node.type !== 'text') continue;
      const raw = node.text || '';
      const line = plainLine(raw);
      if (!line) continue;
      const tableRows = parseMetricSourcePairs(raw);
      if (tableRows.length) {
        items.push({ type: 'table', rows: tableRows });
        continue;
      }
      if (/^摘录/.test(line)) {
        items.push({ type: 'section', text: line });
        continue;
      }
      const kv = splitByFirstColon(line);
      if (kv && /目标值|出处类型|各来源提及次数|来源口径说明/.test(kv.k)) {
        items.push({ type: 'kv', k: kv.k, v: kv.v || '—' });
        continue;
      }
      items.push({ type: 'text', text: line });
    }
    out.push({ title, items });
  }
  return out;
}

function sectionLinesByHeading(lines, headingKeyword) {
  const src = Array.isArray(lines) ? lines : [];
  let inSec = false;
  const out = [];
  for (const raw of src) {
    const t = String(raw ?? '').trim();
    if (t.startsWith('#### ')) {
      if (inSec) break;
      if (t.includes(headingKeyword)) {
        inSec = true;
      }
      continue;
    }
    if (inSec) out.push(raw);
  }
  return out;
}

function plainLine(text) {
  return String(text ?? '')
    .replace(/^\s*-\s*/, '')
    .replace(/^####\s+/, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

function pickLine(lines, includesAny = []) {
  for (const raw of lines || []) {
    const s = plainLine(raw);
    if (!s) continue;
    if (s.startsWith('①') || s.startsWith('②') || s.startsWith('③') || s.startsWith('④') || s.startsWith('⑤')) {
      continue;
    }
    if (!includesAny.length) return s;
    if (includesAny.some((k) => s.includes(k))) return s;
  }
  return '';
}

function extractValueAfterPrefix(lines, prefixes = []) {
  const line = pickLine(lines, prefixes);
  if (!line) return '';
  const p = prefixes.find((x) => line.includes(x));
  if (!p) return line;
  const i = line.indexOf(p);
  const tail = line.slice(i + p.length).replace(/^[:：]\s*/, '').trim();
  return tail || line;
}

function cleanBudgetValue(text) {
  const s = String(text || '').trim();
  if (!s) return '';
  if (s === '—' || s === '-') return '';
  if (/^(核对|差额|合计核对)\s*[.。]?$/.test(s)) return '';
  return s.replace(/\s+/g, ' ').trim();
}

function addBudgetRow(rows, k, v, opts = {}) {
  const vv = cleanBudgetValue(v);
  if (!vv) return;
  // 去重：避免“加总公式/来源构成”等重复出现
  if (rows.some((r) => r && r.k === k)) return;
  rows.push({ k, v: vv, muted: !!opts.muted });
}

function extractAmountByLabel(lines, label) {
  for (const raw of lines || []) {
    const s = plainLine(raw);
    if (!s || !s.includes(label)) continue;
    const m = s.match(/([0-9]+(?:\.[0-9]+)?)\s*万/);
    if (m) return `${m[1]} 万元`;
  }
  return '';
}

function formatAddends(parts = [], total = '') {
  const valid = parts.filter((x) => x && x.v);
  if (!valid.length) return total || '—';
  const expr = valid.map((x) => `${x.k}${x.v}`).join(' + ');
  return total ? `${expr} = ${total}` : expr;
}

function budgetRowClass(row) {
  const k = String(row?.k || '');
  const v = String(row?.v || '');
  return {
    'is-primary': /预算总额|差额/.test(k) || (k === '分项加总' && !row?.muted),
    'is-diff': k.includes('差额'),
    'is-formula': v.includes('+') || v.includes('='),
    'is-muted': !!row?.muted,
  };
}

function splitBudgetValue(text) {
  const s = String(text || '').trim();
  if (!s) return ['—'];
  const parts = s
    .split(/[；;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  return parts.length ? parts : [s];
}

function budgetResultClass(text) {
  const s = String(text || '');
  if (/一致|匹配|通过/.test(s) && !/不一致|不匹配|未通过/.test(s)) return 'ok';
  if (/不一致|不匹配|差异|超出/.test(s)) return 'bad';
  return 'neutral';
}

function pushItem(arr, seen, item) {
  if (!item || !item.value) return;
  const k = `${item.label}::${item.value}`;
  if (seen.has(k)) return;
  seen.add(k);
  arr.push(item);
}

function dimensionHighlights(d) {
  const lines = Array.isArray(d?.detail_lines) ? d.detail_lines : [];
  const out = [];
  const seen = new Set();
  if (d?.rule_id === 'R-TIME-01') {
    pushItem(out, seen, { label: '执行期', value: extractValueAfterPrefix(lines, ['执行期']) });
    pushItem(out, seen, { label: '最晚进度', value: extractValueAfterPrefix(lines, ['进度最晚节点']) });
    pushItem(out, seen, { label: '核验结论', value: pickLine(lines, ['未发现', '不一致', '可能不一致']) });
  } else if (d?.rule_id === 'R-BUDGET-01') {
    pushItem(out, seen, { label: '预算总额', value: extractValueAfterPrefix(lines, ['预算总额', '（一）直接费用']) });
    pushItem(out, seen, { label: '分项加总', value: extractValueAfterPrefix(lines, ['预算分项加总', '设备费/业务费/劳务费等明细加总']) });
    pushItem(out, seen, { label: '差额', value: extractValueAfterPrefix(lines, ['差额']) });
    pushItem(out, seen, { label: '核验结论', value: pickLine(lines, ['结论']) });
  } else if (d?.rule_id === 'R-METRIC-01') {
    pushItem(out, seen, { label: '指标组数', value: pickLine(lines, ['共 ', '组指标']) });
    pushItem(out, seen, { label: '核验结论', value: pickLine(lines, ['未发现', '不一致', '可能不一致']) });
    const names = [];
    for (const raw of lines) {
      const s = String(raw || '').trim();
      const m = s.match(/^####\s*「(.+?)」/);
      if (m && !names.includes(m[1])) names.push(m[1]);
      if (names.length >= 4) break;
    }
    if (names.length) {
      pushItem(out, seen, { label: '已识别指标', value: names.join('、') });
    }
  } else {
    pushItem(out, seen, { label: '要点', value: pickLine(lines) });
  }
  return out.slice(0, 6);
}

/** 解析「5.70 + 0.30 = 6.00」式子，用于拆出间接费 */
function parseBudgetDirectIndirectSum(value) {
  const s = String(value || '').replace(/\s+/g, ' ');
  const m = s.match(/([\d.]+)\s*\+\s*([\d.]+)\s*=\s*([\d.]+)/);
  if (!m) return null;
  return { direct: m[1], indirect: m[2], sum: m[3] };
}

function isDirectPlusIndirectKey(k) {
  return /直接费用\s*\+\s*间接费用/.test(String(k || '').trim());
}

/** 在明细行里找「直接费用 + 间接费用」；先 sec2，再全量 lines 兜底（防分节标题不一致） */
function findDirectIndirectKv(sec2, allLines) {
  const scan = (arr) => {
    for (const raw of arr || []) {
      const s = plainLine(raw);
      const kv = splitByFirstColon(s);
      if (!kv || !/万/.test(kv.v)) continue;
      if (isDirectPlusIndirectKey(kv.k)) return kv;
    }
    return null;
  };
  return scan(sec2) || scan(allLines);
}

function findBudgetScopeKv(arr) {
  for (const raw of arr || []) {
    const s = plainLine(raw);
    const kv = splitByFirstColon(s);
    if (!kv || !/万/.test(kv.v)) continue;
    if (kv.k === '口径说明') return kv;
  }
  return null;
}

/** 分项加总行的展开：优先「加总公式」，否则「来源构成」，与报告 ② 节一致 */
function findSumBreakdownForSubtotal(sec2) {
  for (const raw of sec2 || []) {
    const s = plainLine(raw);
    const kv = splitByFirstColon(s);
    if (!kv || !/万/.test(kv.v)) continue;
    if (kv.k === '加总公式') return kv.v;
  }
  for (const raw of sec2 || []) {
    const s = plainLine(raw);
    const kv = splitByFirstColon(s);
    if (!kv || !/万/.test(kv.v)) continue;
    if (kv.k === '来源构成') return kv.v;
  }
  return '';
}

function budgetFocusCards(d) {
  const lines = Array.isArray(d?.detail_lines) ? d.detail_lines : [];
  const sec1 =
    sectionLinesByHeading(lines, '① 总额核对（总额 vs 分项求和）') ||
    sectionLinesByHeading(lines, '① 金额核对（直接费用');
  const sec2 = sectionLinesByHeading(lines, '② 分项明细（节选）') || sectionLinesByHeading(lines, '④ 科目结构');
  const cards = [];

  const c1a = extractValueAfterPrefix(sec1, ['预算总额', '（一）直接费用', '（一）直接费用（抽取）']);
  const c1b = extractValueAfterPrefix(
    sec1,
    ['预算分项加总', '来源分项加总', '直接费用分项加总', '设备费/业务费/劳务费等明细加总', '明细科目加总'],
  );
  const c1d = extractValueAfterPrefix(sec1, ['差额']);
  const c1r = extractValueAfterPrefix(sec1, ['结论']);
  const rows = [];
  addBudgetRow(rows, '预算总额', c1a);
  const sumBreakdown = findSumBreakdownForSubtotal(sec2);
  addBudgetRow(rows, '分项加总', sumBreakdown || c1b, { muted: !!sumBreakdown });
  addBudgetRow(rows, '差额', c1d);
  // 科目加总（设备/业务/劳务…）与间接费拆行；间接费与直接费科目行同为 muted 色
  let subjFormula = '';
  let fallbackFormula = '';
  for (const raw of sec2 || []) {
    const s = plainLine(raw);
    const kv = splitByFirstColon(s);
    if (!kv) continue;
    if (!/万/.test(kv.v)) continue;
    if (kv.k === '科目加总公式') {
      subjFormula = kv.v;
      break;
    }
    if (!fallbackFormula && kv.k === '加总公式') {
      fallbackFormula = kv.v;
    }
  }
  const formula = subjFormula || fallbackFormula;

  const bridgeKv = findDirectIndirectKv(sec2, lines);
  const triple = bridgeKv ? parseBudgetDirectIndirectSum(bridgeKv.v) : null;
  const scopeKv = findBudgetScopeKv(sec2) || findBudgetScopeKv(lines);

  if (triple) {
    addBudgetRow(rows, '直接费科目合计', formula, { muted: true });
    addBudgetRow(rows, '间接费用', `${triple.indirect} 万元`, { muted: true });
  } else {
    addBudgetRow(rows, '计算过程', formula, { muted: true });
    if (scopeKv) addBudgetRow(rows, '口径说明', scopeKv.v, { muted: true });
  }

  if (rows.length || c1r) {
    cards.push({
      title: '',
      rows,
      result: cleanBudgetValue(c1r) || '',
    });
  }

  return cards;
}

function parseMetricSourcePairs(text) {
  const s = plainLine(text || '');
  if (!s || !s.includes('各来源提及值')) return [];
  const i = s.indexOf('各来源提及值');
  let body = s.slice(i + '各来源提及值'.length).replace(/^[:：]\s*/, '').trim();
  if (!body) return [];
  if (body.endsWith('。')) body = body.slice(0, -1);
  const segs = body
    .split(/[；;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const rows = [];
  for (const seg of segs) {
    const j = seg.indexOf('=');
    if (j <= 0) continue;
    const source = seg.slice(0, j).trim();
    const value = seg.slice(j + 1).trim();
    if (!source || !value) continue;
    const vals = value
      .split(/[、,，]/)
      .map((v) => v.trim())
      .filter(Boolean);
    rows.push({ source, value, values: vals });
  }
  if (!rows.length) return [];
  const base = rows.find((r) => r.source.includes('绩效指标表')) || rows[0];
  const baseSet = new Set(base.values);
  return rows.map((r) => {
    const cur = new Set(r.values);
    const same = cur.size === baseSet.size && [...cur].every((x) => baseSet.has(x));
    return {
      ...r,
      verdict: same ? '一致' : '差异',
      is_baseline: r.source === base.source,
    };
  });
}
</script>

<template>
  <section class="logicon-batch panel-shell panel-shell-stretch">
    <div class="logicon-batch-head">
      <button type="button" class="workbench-tab-btn logicon-refresh" :disabled="loading" @click="load">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>

    <div v-if="errorText" class="logicon-err">{{ errorText }}</div>
    <div v-else-if="loading && !batch" class="logicon-muted">正在读取最新批次…</div>
    <div v-else-if="!batch?.batch_id" class="logicon-muted">
      暂无可展示的检测结果，请先执行检测后刷新。
    </div>
    <div v-else class="logicon-list">
      <div
        v-for="row in batch.items"
        :key="row.stem"
        class="logicon-card"
        :class="{ 'is-open': expandedStem === row.stem }"
      >
        <button type="button" class="logicon-card-head" @click="toggleStem(row.stem)">
          <span class="logicon-card-title-block">
            <div class="logicon-project-name-row">
              <span class="logicon-project-label">项目名称</span>
              <span class="logicon-title-line">{{ (row.display_name || '').trim() || '—' }}</span>
            </div>
            <span class="logicon-stem-muted">{{ row.stem }}</span>
          </span>
          <span class="logicon-badges">
            <span v-if="row.declaration" class="doc-pill" :class="conflictPillClass(row.declaration)">
              申报书 · {{ conflictCount(row.declaration) }} 条冲突
            </span>
            <span v-if="row.task" class="doc-pill" :class="conflictPillClass(row.task)">
              任务书 · {{ conflictCount(row.task) }} 条冲突
            </span>
          </span>
          <span class="logicon-chev">{{ expandedStem === row.stem ? '▾' : '▸' }}</span>
        </button>
        <div v-show="expandedStem === row.stem" class="logicon-card-body">
          <div
            v-if="row.declaration && row.task"
            class="doc-view-tabs"
          >
            <button
              type="button"
              class="doc-view-tab"
              :class="{ active: docView(row.stem) === 'all' }"
              @click="setDocView(row.stem, 'all')"
            >
              全部
            </button>
            <button
              type="button"
              class="doc-view-tab declaration"
              :class="{ active: docView(row.stem) === 'declaration' }"
              @click="setDocView(row.stem, 'declaration')"
            >
              申报书
            </button>
            <button
              type="button"
              class="doc-view-tab task"
              :class="{ active: docView(row.stem) === 'task' }"
              @click="setDocView(row.stem, 'task')"
            >
              任务书
            </button>
          </div>
          <div
            v-for="doc in filteredDocs(row)"
            :key="doc.doc_id"
            class="logicon-doc-block"
            :class="doc.doc_kind === 'declaration' ? 'is-declaration' : 'is-task'"
          >
            <div class="logicon-doc-title">
              <span class="logicon-doc-kind">{{ docKindLabel(doc.doc_kind) }}</span>
              <span class="logicon-doc-meta" :class="conflictPillClass(doc)">冲突 {{ conflictCount(doc) }} 条</span>
            </div>
            <div class="dim-evidence-section">
              <div
                v-for="d in doc.dimension_summaries || []"
                :key="d.rule_id"
                class="dim-evidence-block"
              >
                <div class="dim-evidence-head">
                  <span class="dim-chip" :class="outcomeClass(d.outcome)">
                    {{ d.name || d.rule_id }} · {{ outcomeLabel(d.outcome) }}
                  </span>
                </div>
                <div v-if="d.detail_lines?.length" class="dim-parsed-root">
                  <div v-if="d.rule_id === 'R-BUDGET-01'" class="budget-focus-grid">
                    <div v-for="(card, bi) in budgetFocusCards(d)" :key="bi" class="budget-focus-card">
                      <div v-if="card.title" class="budget-focus-head">
                        <div class="budget-focus-title">{{ card.title }}</div>
                      </div>
                      <div class="budget-focus-rows">
                        <div
                          v-for="(row, li) in card.rows"
                          :key="li"
                          class="budget-focus-row"
                          :class="budgetRowClass(row)"
                        >
                          <span class="budget-focus-k">{{ row.k }}</span>
                          <span class="budget-focus-v">
                            <span
                              v-for="(line, si) in splitBudgetValue(row.v)"
                              :key="`${li}-${si}`"
                              class="budget-focus-v-line"
                            >
                              {{ line }}
                            </span>
                          </span>
                        </div>
                      </div>
                      <div v-if="card.result" class="budget-focus-result" :class="budgetResultClass(card.result)">
                        {{ card.result }}
                      </div>
                    </div>
                  </div>
                  <div v-else-if="d.rule_id === 'R-METRIC-01'" class="metric-clean-wrap">
                    <div v-if="metricOverviewText(d.detail_lines)" class="metric-clean-overview">
                      {{ metricOverviewText(d.detail_lines) }}
                    </div>
                    <div v-for="(card, ci) in metricCards(d.detail_lines)" :key="ci" class="metric-clean-card">
                      <div class="metric-clean-title">{{ card.title }}</div>
                      <div class="metric-clean-items">
                        <template v-for="(item, ii) in card.items" :key="`${ci}-${ii}`">
                          <div v-if="item.type === 'kv'" class="metric-clean-kv">
                            <span class="metric-clean-k">{{ item.k }}</span>
                            <span class="metric-clean-v">{{ item.v }}</span>
                          </div>
                          <div v-else-if="item.type === 'table'" class="metric-source-table-wrap">
                            <table class="metric-source-table">
                              <thead>
                                <tr>
                                  <th>来源</th>
                                  <th>提及值</th>
                                  <th>判定</th>
                                </tr>
                              </thead>
                              <tbody>
                                <tr v-for="(row, ri) in item.rows" :key="ri">
                                  <td>{{ row.source }}<span v-if="row.is_baseline">（基准）</span></td>
                                  <td>{{ row.value }}</td>
                                  <td :class="row.verdict === '一致' ? 'ok' : 'bad'">{{ row.verdict }}</td>
                                </tr>
                              </tbody>
                            </table>
                          </div>
                          <div v-else-if="item.type === 'section'" class="metric-clean-section">{{ item.text }}</div>
                          <p v-else-if="item.type === 'text'" class="metric-clean-text">{{ item.text }}</p>
                          <pre v-else-if="item.type === 'code'" class="dim-excerpt">{{ item.content }}</pre>
                        </template>
                      </div>
                    </div>
                  </div>
                  <div v-else-if="d.rule_id !== 'R-METRIC-01'" class="dim-quick">
                    <div
                      v-for="(q, qi) in dimensionHighlights(d)"
                      :key="qi"
                      class="dim-quick-line"
                    >
                      <span class="dim-quick-k">{{ q.label }}</span>
                      <span class="dim-quick-v">{{ q.value }}</span>
                    </div>
                  </div>
                  <!-- 按需求：不在维度卡片内展示“矛盾位置/摘录片段” -->
                </div>
                <div v-else class="logicon-muted sm">本维度暂无可展示结果。</div>
              </div>
              <div v-if="!(doc.dimension_summaries || []).length" class="logicon-muted sm">
                无维度汇总数据。
              </div>
            </div>
            <div class="conf-section-label">冲突提示</div>
            <ul v-if="doc.conflicts?.length" class="conf-list">
              <li v-for="c in doc.conflicts" :key="c.conflict_id" class="conf-item" :class="severityClass(c.severity)">
                <div class="conf-title">{{ c.title }}</div>
                <div class="conf-desc">{{ c.description }}</div>
                <!-- 按需求：冲突提示区不展示证据片段，仅保留标题+描述 -->
              </li>
            </ul>
            <div v-else class="logicon-muted sm">未检出冲突项。</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.logicon-batch {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.logicon-batch-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-bottom: 10px;
}

.logicon-code {
  font-size: 11px;
  background: var(--bg-muted, #f3f4f6);
  padding: 1px 6px;
  border-radius: 4px;
}

.logicon-refresh {
  flex-shrink: 0;
}

.logicon-err {
  color: #b91c1c;
  font-size: 13px;
}

.logicon-muted {
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
}

.logicon-muted.sm {
  font-size: 12px;
  margin-top: 6px;
}

.logicon-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.logicon-card {
  border: 1px solid var(--border-subtle, #e5e7eb);
  border-radius: 10px;
  background: var(--bg-surface, #fff);
  overflow: hidden;
  flex-shrink: 0;
}

.logicon-card-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font: inherit;
}

.logicon-card-head:hover {
  background: var(--bg-muted, #f9fafb);
}

.logicon-card-title-block {
  flex: 0 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
}

.logicon-project-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  min-width: 0;
}

.logicon-project-label {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.logicon-title-line {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.logicon-stem-muted {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: #9ca3af;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logicon-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  flex: 1;
  min-width: 0;
}

.doc-pill {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.doc-pill.doc-pill-ok {
  background: #dcfce7;
  color: #166534;
}

.doc-pill.doc-pill-bad {
  background: #fee2e2;
  color: #991b1b;
}

.sev-red {
  background: #e0e7ff;
  color: #3730a3;
}
.sev-yellow {
  background: #e0f2fe;
  color: #0c4a6e;
}
.sev-green {
  background: #f1f5f9;
  color: #334155;
}

.logicon-chev {
  flex-shrink: 0;
  color: #9ca3af;
  font-size: 12px;
}

.logicon-card-body {
  padding: 0 12px 12px;
  border-top: 1px solid var(--border-subtle, #f3f4f6);
}

.doc-view-tabs {
  margin: 10px 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}

.doc-view-tab {
  border: 0;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  padding: 5px 10px;
  border-radius: 8px;
  cursor: pointer;
  line-height: 1.2;
}

.doc-view-tab:hover {
  background: #eef2ff;
}

.doc-view-tab.active {
  background: #e2e8f0;
  color: #0f172a;
}

.doc-view-tab.declaration.active {
  background: #dbeafe;
  color: #1d4ed8;
}

.doc-view-tab.task.active {
  background: #e0e7ff;
  color: #3730a3;
}

.logicon-doc-title {
  font-size: 13px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.logicon-doc-block {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #ffffff;
  padding: 12px;
}

.logicon-doc-block + .logicon-doc-block {
  margin-top: 14px;
}

.logicon-doc-block.is-declaration {
  border-color: #bfdbfe;
  background: linear-gradient(180deg, #f9fcff 0%, #ffffff 100%);
}

.logicon-doc-block.is-task {
  border-color: #c7d2fe;
  background: linear-gradient(180deg, #f8faff 0%, #ffffff 100%);
}

.logicon-doc-kind {
  font-weight: 700;
  color: #0f172a;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
}

.logicon-doc-block.is-declaration .logicon-doc-kind {
  color: #1d4ed8;
  background: #dbeafe;
}

.logicon-doc-block.is-task .logicon-doc-kind {
  color: #3730a3;
  background: #e0e7ff;
}

.logicon-doc-meta {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.logicon-doc-meta.doc-pill-ok {
  color: #166534;
}

.logicon-doc-meta.doc-pill-bad {
  color: #991b1b;
}

.partial-tag {
  font-size: 11px;
  font-weight: 500;
  color: #92400e;
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 4px;
}

.dim-section-label,
.conf-section-label {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
  margin: 16px 0 6px;
  letter-spacing: 0.02em;
}

.dim-section-label {
  margin-top: 0;
}

.conf-section-label {
  margin-top: 22px;
}

.conf-evidence {
  margin-top: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #ffffff;
  padding: 10px 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.conf-evidence-head {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
}

.conf-evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conf-evidence-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conf-evidence-meta {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.conf-evidence-snippet {
  font-size: 12px;
  line-height: 1.55;
  color: #111827;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 10px;
  word-break: break-word;
}

.conf-evidence-more {
  margin-top: 8px;
}

.conf-evidence-more summary {
  font-size: 12px;
  color: #2563eb;
  cursor: pointer;
  user-select: none;
}

.dim-conf-evidence {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #ffffff;
  padding: 10px 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.dim-conf-evidence-head {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
}

.dim-conf-evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dim-conf-evidence-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dim-conf-evidence-meta {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.dim-conf-evidence-snippet {
  font-size: 12px;
  line-height: 1.55;
  color: #111827;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 10px;
  word-break: break-word;
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dim-conf-evidence-more {
  margin-top: 6px;
}

.dim-conf-evidence-more summary {
  font-size: 12px;
  color: #2563eb;
  cursor: pointer;
  user-select: none;
}

.dim-conf-evidence-full {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #111827;
  white-space: pre-wrap;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 10px;
  word-break: break-word;
}

.dim-section-hint {
  margin: 0 0 14px;
  font-size: 12px;
  line-height: 1.5;
  color: #6b7280;
}

.dim-evidence-section {
  margin-bottom: 8px;
}

.dim-evidence-block {
  margin-bottom: 16px;
  padding: 14px 14px 12px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.dim-evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f3f4f6;
}

.dim-rule-id {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  color: #9ca3af;
  font-family: ui-monospace, monospace;
}

.dim-parsed-root {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.budget-focus-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.budget-focus-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #ffffff;
  padding: 10px 12px;
  box-shadow: none;
}

.budget-focus-head {
  margin-bottom: 6px;
}

.budget-focus-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  line-height: 1.4;
  padding-left: 0;
  border-left: 0;
}

.budget-focus-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.budget-focus-row {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 4px 0;
  border-bottom: 0;
  width: 100%;
}

.budget-focus-row.is-formula .budget-focus-v {
  font-family: inherit;
  font-size: 12px;
  color: #475569;
  font-weight: 400;
}

.budget-focus-k {
  font-size: 12px;
  line-height: 1.4;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
}

.budget-focus-k::after {
  content: '';
  flex: 1 1 auto;
  border-bottom: 1px dotted #e2e8f0;
  transform: translateY(-2px);
  min-width: 16px;
}

.budget-focus-row.is-primary .budget-focus-k,
.budget-focus-row.is-primary .budget-focus-v {
  color: #0f172a;
  font-weight: 700;
}

.budget-focus-row.is-diff .budget-focus-k,
.budget-focus-row.is-diff .budget-focus-v {
  color: #334155;
}

.budget-focus-row.is-muted .budget-focus-k,
.budget-focus-row.is-muted .budget-focus-v {
  color: #64748b;
  font-weight: 500;
}

.budget-focus-v {
  font-size: 12px;
  line-height: 1.45;
  color: #475569;
  word-break: break-word;
  font-weight: 400;
  text-align: right;
  flex: 0 0 auto;
  margin-left: auto;
}

.budget-focus-v-line {
  display: block;
}

.budget-focus-v-line + .budget-focus-v-line {
  margin-top: 2px;
}

.budget-focus-result {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.45;
  color: #334155;
  font-weight: 600;
  padding: 6px 8px;
  border-radius: 6px;
  border-left: 3px solid #cbd5e1;
  background: #f8fafc;
}

.budget-focus-result.ok {
  color: #166534;
  background: #ecfdf5;
  border-left-color: #22c55e;
  border-top-color: transparent;
  border-right-color: transparent;
  border-bottom-color: transparent;
}

.budget-focus-result.bad {
  color: #9f1239;
  background: #fff1f2;
  border-left-color: #f43f5e;
  border-top-color: transparent;
  border-right-color: transparent;
  border-bottom-color: transparent;
}

.budget-focus-result.neutral {
  color: #334155;
  background: #f8fafc;
  border-left-color: #cbd5e1;
  border-top-color: transparent;
  border-right-color: transparent;
  border-bottom-color: transparent;
}

.metric-clean-wrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.metric-clean-overview {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  font-size: 13px;
  line-height: 1.6;
  color: #1f2937;
  font-weight: 600;
}

.metric-clean-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 12px;
}

.metric-clean-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

.metric-clean-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-clean-kv {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.metric-clean-k {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  line-height: 1.55;
}

.metric-clean-v {
  font-size: 13px;
  color: #111827;
  font-weight: 600;
  line-height: 1.55;
  word-break: break-word;
}

.metric-clean-section {
  font-size: 12px;
  color: #334155;
  font-weight: 700;
  margin-top: 2px;
}

.metric-clean-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #374151;
}

.dim-quick {
  border: 1px solid #e6eef9;
  background: #f8fbff;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dim-quick-line {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  font-size: 13px;
  line-height: 1.6;
}

.dim-quick-k {
  color: #475569;
  font-weight: 700;
  white-space: nowrap;
}

.dim-quick-v {
  color: #0f172a;
  word-break: break-word;
}

@media (max-width: 720px) {
  .budget-focus-grid {
    grid-template-columns: 1fr;
  }

  .budget-focus-row {
    gap: 6px;
  }

  .metric-clean-kv {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .dim-quick-line {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .dim-quick-k {
    font-size: 12px;
  }
}

.dim-full {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fcfcfd;
  overflow: hidden;
}

.dim-full-sum {
  cursor: pointer;
  list-style: none;
  padding: 9px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  user-select: none;
}

.dim-full-sum::-webkit-details-marker {
  display: none;
}

.dim-full-sum::before {
  content: '▸';
  display: inline-block;
  margin-right: 8px;
  font-size: 10px;
  color: #64748b;
  transition: transform 0.15s;
}

.dim-full[open] .dim-full-sum::before {
  transform: rotate(90deg);
}

.dim-full.metric-inline {
  border: 0;
  background: transparent;
}

.dim-full.metric-inline > .dim-full-sum {
  display: none;
}

.dim-full.metric-inline > .dim-full-inner {
  border-top: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dim-full.metric-inline .dim-group {
  margin-bottom: 0;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 12px;
}

.dim-full.metric-inline .dim-h4 {
  margin-bottom: 10px;
  font-size: 14px;
  color: #111827;
}

.dim-full.metric-inline .dim-fold {
  background: #fff;
  border-color: #dfe7f2;
}

.dim-full.metric-inline .dim-group-open {
  gap: 8px;
}

.dim-full.metric-inline .dim-li {
  padding: 0;
  font-size: 13px;
  line-height: 1.65;
}

.dim-full.metric-inline .dim-li::before {
  display: none;
}

.dim-full.metric-inline .dim-li.nest {
  padding: 0 0 0 10px;
  border-left: 2px solid #e5e7eb;
  font-size: 12.5px;
  color: #4b5563;
}

.dim-full.metric-inline .dim-li.nest::before {
  display: none;
}

.dim-full-inner {
  border-top: 1px solid #eef2f7;
  padding: 10px 12px 12px;
}

.dim-group {
  margin-bottom: 14px;
}

.dim-group:last-child {
  margin-bottom: 0;
}

.dim-h4 {
  margin: 0 0 10px;
  padding: 0 0 6px;
  font-size: 13px;
  font-weight: 700;
  color: #111827;
  line-height: 1.4;
  border-bottom: 1px solid #eef2f7;
}

.dim-group-open {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dim-spacer {
  height: 8px;
  flex-shrink: 0;
}

.dim-li {
  margin: 0;
  padding: 6px 0 6px 2px;
  font-size: 13px;
  line-height: 1.65;
  color: #374151;
  position: relative;
  padding-left: 14px;
}

.dim-li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.85em;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #93c5fd;
}

.dim-li.nest {
  padding-left: 22px;
  font-size: 12px;
  color: #4b5563;
}

.dim-li.nest::before {
  background: #cbd5e1;
  width: 4px;
  height: 4px;
}

.metric-source-table-wrap {
  margin-top: 4px;
  overflow: auto;
}

.metric-source-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: #fff;
  border: 1px solid #dbe4ef;
  border-radius: 8px;
  overflow: hidden;
}

.metric-source-table th,
.metric-source-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
  line-height: 1.45;
  white-space: normal;
  vertical-align: top;
}

.metric-source-table th {
  font-weight: 700;
  color: #475569;
  background: #f8fafc;
}

.metric-source-table td.ok {
  color: #166534;
  font-weight: 700;
}

.metric-source-table td.bad {
  color: #b91c1c;
  font-weight: 700;
}

.dim-excerpt {
  margin: 8px 0 4px;
  padding: 12px 14px;
  max-height: 160px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #1f2937;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.dim-plain {
  margin: 4px 0;
  font-size: 13px;
  line-height: 1.55;
  color: #4b5563;
}

.dim-fold {
  margin-top: 2px;
  border: 1px solid #e8ecf1;
  border-radius: 10px;
  background: #fafbfc;
  overflow: hidden;
}

.dim-fold-sum {
  cursor: pointer;
  list-style: none;
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  user-select: none;
}

.dim-fold-sum::-webkit-details-marker {
  display: none;
}

.dim-fold-sum::before {
  content: '▸';
  display: inline-block;
  margin-right: 8px;
  font-size: 10px;
  color: #64748b;
  transition: transform 0.15s;
}

.dim-fold[open] .dim-fold-sum::before {
  transform: rotate(90deg);
}

.dim-fold-inner {
  padding: 10px 12px 12px;
  border-top: 1px solid #eef2f7;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dim-chip {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 8px;
  max-width: 100%;
  line-height: 1.35;
}

.out-ok {
  background: #ecfdf5;
  color: #166534;
}
.out-bad {
  background: #ede9fe;
  color: #5b21b6;
}
.out-warn {
  background: #f1f5f9;
  color: #475569;
}

.conf-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.conf-item {
  padding: 8px 10px;
  margin-bottom: 8px;
  border-radius: 8px;
  border-left: 3px solid #d1d5db;
  background: #fafafa;
}

.conf-item.sev-red {
  border-left-color: #6366f1;
  background: #eef2ff;
}
.conf-item.sev-yellow {
  border-left-color: #0ea5e9;
  background: #f0f9ff;
}
.conf-item.sev-green {
  border-left-color: #94a3b8;
  background: #f8fafc;
}

.conf-title {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 4px;
}

.conf-desc {
  font-size: 12px;
  color: #4b5563;
  line-height: 1.45;
}

.evidence-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.evidence-box {
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e5e7eb;
}

.evidence-meta {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 6px;
}

.evidence-snippet {
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 11px;
  line-height: 1.45;
  color: #1f2937;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}

.evidence-missing {
  margin-top: 6px;
}

.warn-box {
  margin-top: 8px;
  font-size: 11px;
  color: #92400e;
  background: #fffbeb;
  padding: 8px 10px;
  border-radius: 6px;
}
</style>
