<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRequestStore } from '../../stores/request';

const req = useRequestStore();
const loading = ref(false);
const errorText = ref('');
const bundle = ref(null);
const selectedIndex = ref(0);

const summary = computed(() => bundle.value?.summary || {});
const runConfig = computed(() => bundle.value?.run_config || {});
const results = computed(() => (Array.isArray(bundle.value?.results) ? bundle.value.results : []));

const hasData = computed(() => results.value.length > 0);

const activeRow = computed(() => {
  const list = results.value;
  const i = selectedIndex.value;
  if (!list.length || i < 0 || i >= list.length) return null;
  return list[i];
});

watch(results, (list) => {
  if (!list.length) {
    selectedIndex.value = 0;
    return;
  }
  if (selectedIndex.value >= list.length) selectedIndex.value = 0;
});

const subtitleLine = computed(() => {
  const g = bundle.value?.generated_at;
  const gid = bundle.value?.group_id;
  const parts = [];
  if (g) parts.push(`生成时间 ${String(g).replace('T', ' ')}`);
  if (gid != null && gid !== '') parts.push(`分组编号 ${gid}`);
  return parts.join('　·　') || '';
});

/** 非负整数展示；异常（如负数）显示为「—」 */
function formatStatCount(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v < 0) return '—';
  return v;
}

function configLabelZh(key, index = 0) {
  const k = String(key || '').trim();
  const map = {
    top_k: '返回前若干名专家',
    expert_limit: '专家数量上限',
    llm_candidate_limit: '大模型候选人数上限',
    search_timeout: '检索超时（秒）',
    max_concurrency: '最大并发任务数',
    max_llm_concurrency: '大模型最大并发数',
  };
  if (map[k]) return map[k];
  return `其他参数 ${index + 1}`;
}

/** 下拉选项：仅展示项目名称 */
function dropdownOptionLabel(row) {
  const title = row.subject_name && String(row.subject_name).trim();
  if (title) return title.length > 72 ? `${title.slice(0, 72)}…` : title;
  return '（未命名分组）';
}

function shortGroupId(gid) {
  const s = String(gid || '');
  if (s.length <= 16) return s;
  return `${s.slice(0, 8)}…${s.slice(-6)}`;
}

function rowMiniStats(row) {
  const ex = row.group_experts || [];
  const k = ex.length;
  const top1 = k ? ex[0].avg_match_score : null;
  const sum = ex.reduce((acc, e) => acc + Number(e?.avg_match_score ?? 0), 0);
  const avg = k ? Math.round((sum / k) * 100) / 100 : null;
  return { k, top1, avg };
}

function friendlyError(msg) {
  const s = String(msg || '');
  if (/fetch|network|failed|404|500|超时/i.test(s)) return '加载失败，请检查网络或后端服务是否正常。';
  if (/接口返回失败/.test(s)) return '接口返回失败，请稍后重试。';
  return s || '加载失败。';
}

async function load() {
  loading.value = true;
  errorText.value = '';
  try {
    const url = `${req.apiBase()}/expert-debug/latest`;
    const parsed = await req.fetchWithTimeout(url, { method: 'GET' }, 60000);
    if (parsed?.status && parsed.status !== 'success') {
      throw new Error(parsed.message || '接口返回失败');
    }
    bundle.value = parsed?.data ?? null;
    selectedIndex.value = 0;
  } catch (e) {
    errorText.value = friendlyError(e?.message || e);
    bundle.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="content-scroll em-root">
    <div v-if="errorText" class="em-err">{{ errorText }}</div>
    <div v-else-if="loading && !bundle" class="em-muted">正在加载…</div>
    <div v-else-if="!hasData" class="em-muted">未读取到匹配数据，请确认服务端已放置匹配结果文件。</div>
    <div v-else class="em-layout">
      <div class="em-inner">
        <header class="em-hero">
          <div class="em-hero-top">
            <div>
              <h1 class="em-title">专家匹配报告</h1>
              <p v-if="subtitleLine" class="em-subtitle">{{ subtitleLine }}</p>
            </div>
            <div class="em-count-badge">共 {{ results.length }} 条</div>
          </div>
          <div class="em-stats">
            <div class="em-stat">
              <div class="em-stat-label">项目总数</div>
              <div class="em-stat-value">{{ formatStatCount(summary.project_count) }}</div>
            </div>
            <div class="em-stat">
              <div class="em-stat-label">已匹配条目数</div>
              <div class="em-stat-value">{{ formatStatCount(summary.matched_group_count) }}</div>
            </div>
            <div class="em-stat">
              <div class="em-stat-label">未匹配条目数</div>
              <div class="em-stat-value">{{ formatStatCount(summary.unmatched_group_count) }}</div>
            </div>
            <div class="em-stat">
              <div class="em-stat-label">首名得分平均值</div>
              <div class="em-stat-value">{{ summary.avg_top1_score ?? '—' }}</div>
            </div>
          </div>
        </header>

        <details v-if="Object.keys(runConfig).length" class="em-details">
          <summary class="em-details-sum">运行参数</summary>
          <div class="em-config-grid">
            <div v-for="([key, val], ci) in Object.entries(runConfig)" :key="key" class="em-config-item">
              <div class="em-config-label">{{ configLabelZh(key, ci) }}</div>
              <div class="em-config-value">{{ val }}</div>
            </div>
          </div>
        </details>

        <div class="em-main-shell">
          <main v-if="activeRow" class="em-main">
            <article class="em-card">
              <div class="em-card-header">
                <div class="em-card-head-text">
                  <label class="em-card-head-picker">
                    <select
                      v-model.number="selectedIndex"
                      class="em-picker-select em-card-title-select"
                      aria-label="选择要查看的匹配条目（项目名称与项目编号）"
                    >
                      <option
                        v-for="(row, idx) in results"
                        :key="row.group_id || idx"
                        :value="idx"
                      >
                        {{ dropdownOptionLabel(row) }}
                      </option>
                    </select>
                  </label>
                  <div class="em-card-meta">
                    <span class="em-meta-line" :title="activeRow.group_id">
                      分组编号：<span class="em-mono">{{ shortGroupId(activeRow.group_id) }}</span>
                    </span>
                    <span class="em-meta-line">学科：<strong>{{ activeRow.subject_name || '—' }}</strong></span>
                  </div>
                </div>
                <div class="em-pill">
                  候选专家
                  <b>{{ activeRow.expert_count ?? (activeRow.group_experts || []).length }}</b>
                  人
                </div>
              </div>
              <div class="em-card-body">
                <div v-if="activeRow.query_text" class="em-query">
                  <span class="em-query-label">检索用语</span>
                  <div class="em-query-body">{{ activeRow.query_text }}</div>
                </div>
                <div class="em-mini-grid">
                  <div class="em-mini">
                    <div class="em-mini-label">本组人数</div>
                    <div class="em-mini-value">{{ rowMiniStats(activeRow).k }}</div>
                  </div>
                  <div class="em-mini">
                    <div class="em-mini-label">第一名得分</div>
                    <div class="em-mini-value">{{ rowMiniStats(activeRow).top1 ?? '—' }}</div>
                  </div>
                  <div class="em-mini">
                    <div class="em-mini-label">本组平均分</div>
                    <div class="em-mini-value">{{ rowMiniStats(activeRow).avg ?? '—' }}</div>
                  </div>
                </div>

                <div v-if="activeRow.projects?.length" class="em-query">
                  <span class="em-query-label">本组包含项目 ({{ activeRow.projects.length }})</span>
                  <ul class="em-project-list">
                    <li v-for="(proj, pi) in activeRow.projects" :key="pi">{{ proj }}</li>
                  </ul>
                </div>

                <div v-if="activeRow.group_experts?.length" class="em-table-wrap">
                  <table class="em-table">
                    <thead>
                      <tr>
                        <th class="col-idx">序号</th>
                        <th>专家</th>
                        <th class="col-score">得分</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(ex, ri) in activeRow.group_experts" :key="String(ex.expert_id) + '-' + ri">
                        <td class="col-idx">{{ ri + 1 }}</td>
                        <td>
                          <div class="em-expert-name">{{ ex.expert_name }}</div>
                          <div class="em-expert-id">编号　{{ ex.expert_id }}</div>
                        </td>
                        <td class="col-score">{{ ex.avg_match_score }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </article>
          </main>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.em-root {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: linear-gradient(180deg, #eef2f9 0%, #e8edf5 48%, #f0f3f8 100%);
}

/* 与全局 .content-scroll 解耦：本页用视口内分区高度，不在整块上纵向滚动 */
.em-root.content-scroll {
  overflow: hidden;
  min-height: 0;
}

.em-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 14px;
}

.em-inner {
  max-width: 1280px;
  margin: 0 auto;
  width: 100%;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.em-err {
  color: #b91c1c;
  font-size: 13px;
  padding: 12px 16px;
}

.em-muted {
  font-size: 13px;
  color: #64748b;
  padding: 20px 16px;
}

.em-hero {
  flex-shrink: 0;
  background: linear-gradient(125deg, #ffffff 0%, #f4f7ff 55%, #eef3ff 100%);
  border: 1px solid #d5dff0;
  border-radius: 16px;
  padding: 14px 18px 16px;
  box-shadow: 0 4px 18px rgba(30, 58, 95, 0.08);
}

.em-hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.em-title {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: #0f2744;
  letter-spacing: 0.02em;
}

.em-subtitle {
  margin: 6px 0 0;
  font-size: 12px;
  color: #5a6d85;
}

.em-count-badge {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #1e4b8c;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.22);
  padding: 6px 12px;
  border-radius: 999px;
}

.em-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

@media (max-width: 900px) {
  .em-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.em-stat {
  position: relative;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 12px 10px 14px;
  box-shadow: inset 3px 0 0 #3b82f6;
}

.em-stat-label {
  font-size: 11px;
  color: #64748b;
  font-weight: 500;
}

.em-stat-value {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.em-details {
  flex-shrink: 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 8px 14px 12px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
}

.em-details-sum {
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  font-weight: 700;
  color: #1e3a5f;
  padding: 6px 0 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.em-details-sum::-webkit-details-marker {
  display: none;
}

.em-details-sum::before {
  content: '▸';
  font-size: 11px;
  color: #64748b;
  transition: transform 0.15s;
}

.em-details[open] .em-details-sum::before {
  transform: rotate(90deg);
}

.em-details[open] .em-details-sum {
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 10px;
  padding-bottom: 8px;
}

.em-config-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

@media (max-width: 900px) {
  .em-config-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.em-config-item {
  background: #f8fafc;
  border: 1px solid #e8edf2;
  border-radius: 10px;
  padding: 8px 10px;
}

.em-config-label {
  font-size: 11px;
  color: #64748b;
  line-height: 1.35;
}

.em-config-value {
  margin-top: 4px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.em-main-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.em-card-head-picker {
  display: block;
  width: 100%;
  margin: 0;
  cursor: pointer;
}

.em-picker-select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  padding: 10px 36px 10px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #0f2744;
  font-family: inherit;
  line-height: 1.35;
  border: 1px solid #c7d7ec;
  border-radius: 10px;
  background-color: #f8fafc;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23475569' d='M3 4.5L6 8l3-3.5'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  appearance: none;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
}

.em-card-title-select {
  font-size: 16px;
  font-weight: 800;
  line-height: 1.45;
  padding-top: 8px;
  padding-bottom: 8px;
  border-radius: 12px;
}

.em-picker-select:hover {
  border-color: #93c5fd;
  background-color: #fff;
}

.em-picker-select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}

.em-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  align-self: stretch;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.em-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border: 1px solid #dfe6f0;
  border-radius: 16px;
  box-shadow: 0 6px 22px rgba(30, 58, 95, 0.08);
}

.em-card-header {
  flex-shrink: 0;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
  background: linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%);
  border-bottom: 1px solid #e8edf5;
}

.em-card-head-text {
  flex: 1;
  min-width: 0;
}

.em-card-meta {
  margin-top: 10px;
  font-size: 12px;
  color: #64748b;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.em-meta-line {
  line-height: 1.4;
}

.em-mono {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  color: #475569;
}

.em-pill {
  flex-shrink: 0;
  align-self: flex-start;
  font-size: 12px;
  color: #1d4ed8;
  background: linear-gradient(180deg, #eef5ff 0%, #e0edff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  padding: 8px 14px;
  white-space: nowrap;
}

.em-pill b {
  margin: 0 4px;
  font-size: 14px;
}

.em-card-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 14px 18px 16px;
}

.em-query {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #e8edf2;
  border-radius: 12px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.em-query-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.em-query-body {
  margin-top: 6px;
  font-size: 14px;
  color: #0f2744;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.em-project-list {
  margin: 6px 0 0 0;
  padding: 0 0 0 16px;
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
}

.em-project-list li {
  margin-bottom: 4px;
}

.em-mini-grid {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

@media (max-width: 640px) {
  .em-mini-grid {
    grid-template-columns: 1fr;
  }
}

.em-mini {
  text-align: center;
  padding: 10px 8px;
  border-radius: 12px;
  background: linear-gradient(180deg, #fafbfc 0%, #f4f6f9 100%);
  border: 1px solid #e8ecf0;
}

.em-mini-label {
  font-size: 10px;
  color: #64748b;
  font-weight: 600;
}

.em-mini-value {
  margin-top: 4px;
  font-size: 18px;
  font-weight: 800;
  color: #0f2744;
  font-variant-numeric: tabular-nums;
}

.em-table-wrap {
  flex: 1;
  min-height: 0;
  border: 1px solid #e8edf2;
  border-radius: 12px;
  overflow: auto;
  background: #fafbfd;
}

.em-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: #fff;
}

.em-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  text-align: left;
  padding: 10px 10px;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
  border-bottom: 1px solid #e2e8f0;
}

.em-table td {
  padding: 10px 10px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: top;
}

.em-table tbody tr:nth-child(even) td {
  background: #fafbfc;
}

.em-table tbody tr:hover td {
  background: #f0f7ff;
}

.col-idx {
  width: 48px;
  text-align: center !important;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  color: #64748b;
}

.col-score {
  width: 84px;
  text-align: right !important;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #0f2744;
}

.em-expert-name {
  font-weight: 700;
  color: #0f172a;
}

.em-expert-id {
  margin-top: 3px;
  font-size: 11px;
  color: #64748b;
}
</style>
