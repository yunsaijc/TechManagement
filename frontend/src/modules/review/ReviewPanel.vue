<script setup>
import { computed, onMounted, ref, watch } from 'vue';

const loading = ref(true);
const errorText = ref('');
const payload = ref(null);
const keyword = ref('');
const selectedProjectId = ref('');
const API_BASE_STORAGE_KEY = 'tech_api_base';

function runtimeApiBase() {
  const envBase = String(import.meta.env.VITE_API_BASE || '').trim();
  if (envBase) {
    return envBase.replace(/\/+$/, '');
  }

  const { protocol, hostname, port } = window.location;
  const p = String(port || '').trim();
  const backendPort = p === '8006' ? '8005' : (p || '8000');
  return `${protocol}//${hostname}:${backendPort}/api/v1`;
}

function apiBase() {
  const saved = localStorage.getItem('tech_api_base');
  if (saved && saved.trim()) {
    return saved.trim().replace(/\/+$/, '');
  }

  return runtimeApiBase();
}

async function fetchJsonWithTimeout(url, timeout = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    try { controller.abort(); } catch {}
  }, timeout);

  try {
    const resp = await fetch(url, { signal: controller.signal });
    const text = await resp.text();
    let data = text;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {}
    if (!resp.ok) {
      throw new Error(typeof data === 'object' ? JSON.stringify(data) : text || `HTTP ${resp.status}`);
    }
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('接口请求超时，请检查后端是否已启动');
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function loadDebugBatch() {
  loading.value = true;
  errorText.value = '';
  try {
    let data;
    try {
      data = await fetchJsonWithTimeout(`${apiBase()}/review/debug-batch-view`);
    } catch (error) {
      const saved = localStorage.getItem(API_BASE_STORAGE_KEY);
      const fallback = runtimeApiBase();
      if (saved && saved.trim() && saved.trim().replace(/\/+$/, '') !== fallback) {
        localStorage.removeItem(API_BASE_STORAGE_KEY);
        data = await fetchJsonWithTimeout(`${fallback}/review/debug-batch-view`);
      } else {
        throw error;
      }
    }
    payload.value = data?.data || data;
  } catch (error) {
    errorText.value = String(error?.message || error || '加载失败');
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadDebugBatch();
});

const guideline = computed(() => payload.value?.guideline || { file_name: '', paragraphs: [], full_text: '' });
const guidelineTables = computed(() => Array.isArray(guideline.value?.tables) ? guideline.value.tables : []);
const guidelineTitle = computed(() => {
  const fileName = String(guideline.value?.file_name || '').trim();
  if (!fileName) return '形式审查要点';
  return fileName.replace(/\.docx$/i, '');
});
const projects = computed(() => payload.value?.projects || []);

function normalizeText(text) {
  return String(text || '').toLowerCase().replace(/\s+/g, '');
}

function collectProjectKeywords(project) {
  if (!project) return [];
  const keywords = new Set();
  const add = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return;
    const normalized = normalizeText(raw);
    if (normalized.length < 2) return;
    keywords.add(normalized);
  };

  add(project.project_id);
  add(project.project_name);
  add(project.project_meta?.applicant_unit);
  add(project.project_meta?.guide_name);
  add(project.project_meta?.project_leader);
  add(project.project_type);

  (Array.isArray(project.results) ? project.results : []).forEach((item) => {
    add(item.item);
    add(item.message);
    add(item.status);
    Object.entries(item?.evidence || {}).forEach(([key, value]) => {
      add(evidenceKeyLabel(key));
      if (Array.isArray(value)) {
        value.forEach((entry) => {
          if (typeof entry === 'object' && entry) {
            Object.values(entry).forEach(add);
          } else {
            add(entry);
          }
        });
      } else if (value && typeof value === 'object') {
        Object.values(value).forEach(add);
      } else {
        add(value);
      }
    });
  });

  (Array.isArray(project.missing_attachments) ? project.missing_attachments : []).forEach((item) => {
    add(item.doc_label);
    add(item.doc_kind);
    add(item.reason);
  });

  (Array.isArray(project.manual_review_items) ? project.manual_review_items : []).forEach((item) => {
    add(item.item);
    add(item.code);
    add(item.message);
    add(item.reason);
  });

  (Array.isArray(project.suggestions) ? project.suggestions : []).forEach(add);
  add(project.summary);
  return Array.from(keywords);
}

function rowMatchesProject(row, keywords) {
  const text = normalizeText(row?.content || row?.text || row?.requirement || row?.title || '');
  if (!text || !keywords.length) return false;
  return keywords.some((keyword) => text.includes(keyword) || keyword.includes(text));
}

const projectGuidelineTables = computed(() => {
  if (!selectedProject.value) return [];
  const keywords = collectProjectKeywords(selectedProject.value);
  return guidelineTables.value
    .map((table) => {
      const rows = Array.isArray(table.rows) ? table.rows.filter((row) => rowMatchesProject(row, keywords)) : [];
      return rows.length ? { ...table, rows } : null;
    })
    .filter(Boolean);
});

const filteredProjects = computed(() => {
  const q = String(keyword.value || '').trim().toLowerCase();
  return projects.value.filter((project) => {
    const pid = String(project.project_id || '').toLowerCase();
    const pname = String(project.project_name || '').toLowerCase();
    return !q || pid.includes(q) || pname.includes(q);
  });
});

watch(filteredProjects, (list) => {
  if (!list.length) {
    selectedProjectId.value = '';
    return;
  }
  const exists = list.some((p) => p.project_id === selectedProjectId.value);
  if (!exists) selectedProjectId.value = list[0].project_id;
}, { immediate: true });

const selectedProject = computed(() => {
  if (!filteredProjects.value.length) return null;
  return filteredProjects.value.find((p) => p.project_id === selectedProjectId.value) || filteredProjects.value[0];
});

function hasAny(row) {
  return Array.isArray(row) && row.length > 0;
}

function statusLabel(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'passed') return '通过';
  if (s === 'failed') return '未通过';
  if (s === 'warning') return '警示';
  if (s === 'requires_data') return '待补数据';
  if (s === 'manual') return '人工复核';
  if (s === 'not_applicable') return '不适用';
  return s || '-';
}

function resultStatusClass(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'passed') return 'st-passed';
  if (s === 'failed') return 'st-failed';
  if (s === 'warning') return 'st-warning';
  return 'st-default';
}

function resultStatusLabel(status) {
  return statusLabel(status);
}

function projectFieldLabel(fieldKey) {
  const map = {
    project_id: '项目编号',
    project_type: '项目类型',
    project_name: '项目名称',
    applicant_unit: '申报单位',
    execution_period_years: '执行期(年)',
    year: '年度',
  };
  return map[String(fieldKey || '').trim()] || String(fieldKey || '-');
}

function projectFieldValue(project, fieldKey) {
  if (!project) return '-';
  const key = String(fieldKey || '').trim();
  if (key === 'project_id') return project.project_id || '-';
  if (key === 'project_type') return zhProjectType(project.project_type);
  if (key === 'project_name') return project.project_name || '-';
  if (key === 'applicant_unit') return project.project_meta?.applicant_unit || '-';
  if (key === 'execution_period_years') return project.project_meta?.execution_period_years ?? '-';
  if (key === 'year') return project.project_meta?.year || '-';
  return '-';
}

function zhProjectType(value) {
  const v = String(value || '').trim();
  if (v === 'basic_research') return '基础研究项目';
  if (v === 'regional_innovation') return '区域科技创新体系项目';
  return zhText(v || '-');
}

function evidenceKeyLabel(key) {
  const map = {
    required_fields: '必填字段',
    registered_date: '注册时间',
    registered_after: '时间阈值',
    execution_period_years: '执行期(年)',
    max_execution_period_years: '执行期上限(年)',
    missing_doc_kinds: '缺失材料',
    missing_conditional_attachments: '缺失条件材料',
    pending_review_points: '待补数据/人工复核要点',
    duplicate_submission_status: '重复申报状态',
    reason: '原因',
    requirement: '要点',
    code: '规则',
    doc_kind: '材料类型',
    automation: '处理方式',
    condition_field: '触发条件字段',
    condition_value: '触发条件值',
  };
  return map[String(key || '').trim()] || String(key || '-');
}

function formatEvidencePrimitive(key, value) {
  const k = String(key || '').trim();
  if (k === 'doc_kind') return zhDocKind(value);
  if (k === 'automation') return statusLabel(value);
  if (k === 'code') return zhRule(value);
  if (k === 'project_type') return zhProjectType(value);
  if (k === 'condition_value') return String(value) === 'true' ? '是' : (String(value) === 'false' ? '否' : String(value));
  return zhText(String(value));
}

function formatEvidenceValue(value, project) {
  if (value === null || value === undefined || value === '') return '-';
  return formatEvidenceValueByKey('', value, project);
}

function formatEvidenceValueByKey(key, value, project) {
  const k = String(key || '').trim();
  if (value === null || value === undefined || value === '') return '-';
  if (Array.isArray(value)) {
    if (!value.length) return '-';
    if (k === 'required_fields') {
      return value
        .map((item) => {
          const fieldKey = String(item || '').trim();
          return `${projectFieldLabel(fieldKey)}：${projectFieldValue(project, fieldKey)}`;
        })
        .join('；');
    }
    if (k === 'missing_doc_kinds') return value.map((item) => zhDocKind(item)).join('；');
    return value
      .map((item) => {
        if (item === null || item === undefined || item === '') return '';
        if (typeof item !== 'object') return formatEvidencePrimitive(k, item);
        return Object.entries(item)
          .map(([innerKey, innerVal]) => `${evidenceKeyLabel(innerKey)}：${formatEvidenceValueByKey(innerKey, innerVal, project)}`)
          .join('，');
      })
      .filter(Boolean)
      .join('；');
  }
  if (typeof value !== 'object') return formatEvidencePrimitive(k, value);

  const preferredKeys = [
    'code',
    'requirement',
    'reason',
    'automation',
    'doc_kind',
    'item',
    'message',
    'registered_date',
    'registered_after',
    'execution_period_years',
    'max_execution_period_years',
    'duplicate_submission_status',
    'condition_field',
    'condition_value',
  ];
  const entries = [];
  preferredKeys.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(value, key)) {
      entries.push(`${evidenceKeyLabel(key)}：${formatEvidenceValueByKey(key, value[key], project)}`);
    }
  });
  Object.entries(value).forEach(([key, val]) => {
    if (preferredKeys.includes(key)) return;
    entries.push(`${evidenceKeyLabel(key)}：${formatEvidenceValueByKey(key, val, project)}`);
  });
  return entries.length ? entries.join('；') : JSON.stringify(value);
}

function evidenceRows(evidence, project) {
  const source = evidence && typeof evidence === 'object' ? evidence : null;
  if (!source || !Object.keys(source).length) return [];

  const preferredKeys = [
    'required_fields',
    'missing_doc_kinds',
    'missing_conditional_attachments',
    'pending_review_points',
    'registered_date',
    'registered_after',
    'execution_period_years',
    'max_execution_period_years',
    'duplicate_submission_status',
    'condition_field',
    'condition_value',
    'automation',
    'reason',
    'requirement',
    'code',
    'doc_kind',
  ];

  const orderedKeys = [
    ...preferredKeys.filter((key) => Object.prototype.hasOwnProperty.call(source, key)),
    ...Object.keys(source).filter((key) => !preferredKeys.includes(key)),
  ];

  return orderedKeys.map((key) => ({
    key,
    label: evidenceKeyLabel(key),
    value: formatEvidenceValueByKey(key, source[key], project),
  }));
}

function structuredEvidenceSections(evidence, project) {
  const source = evidence && typeof evidence === 'object' ? evidence : null;
  if (!source) return [];
  const sections = [];

  const requiredFields = Array.isArray(source.required_fields) ? source.required_fields : [];
  if (requiredFields.length) {
    sections.push({
      key: 'required_fields',
      title: '必填字段',
      items: requiredFields.map((fieldKey, idx) => ({
        key: `required_${idx}`,
        title: projectFieldLabel(fieldKey),
        lines: [String(projectFieldValue(project, fieldKey) ?? '-')],
      })),
    });
  }

  const missingDocKinds = Array.isArray(source.missing_doc_kinds) ? source.missing_doc_kinds : [];
  if (missingDocKinds.length) {
    sections.push({
      key: 'missing_doc_kinds',
      title: '缺失材料',
      items: missingDocKinds.map((kind, idx) => ({
        key: `missing_doc_${idx}`,
        title: zhDocKind(kind),
        lines: [],
      })),
    });
  }

  const missingConditional = Array.isArray(source.missing_conditional_attachments) ? source.missing_conditional_attachments : [];
  if (missingConditional.length) {
    sections.push({
      key: 'missing_conditional_attachments',
      title: '缺失条件材料',
      items: missingConditional.map((item, idx) => ({
        key: `missing_conditional_${idx}`,
        title: zhDocKind(item?.doc_kind),
        lines: [
          `原因：${zhText(item?.reason || '-')}`,
        ],
      })),
    });
  }

  const pendingPoints = Array.isArray(source.pending_review_points) ? source.pending_review_points : [];
  if (pendingPoints.length) {
    sections.push({
      key: 'pending_review_points',
      title: '待补数据/人工复核要点',
      items: pendingPoints.map((item, idx) => ({
        key: `pending_${idx}`,
        title: zhRule(item?.code),
        lines: [
          `要点：${zhText(item?.requirement || '-')}`,
          `处理方式：${statusLabel(item?.automation)}`,
          `原因：${zhText(item?.reason || '-')}`,
        ],
      })),
    });
  }

  return sections;
}

function evidenceRowsForDisplay(evidence, project) {
  const rows = evidenceRows(evidence, project);
  const hiddenKeys = [
    'required_fields',
    'missing_doc_kinds',
    'missing_conditional_attachments',
    'pending_review_points',
  ];
  const shouldHide = hiddenKeys.filter((key) => Array.isArray(evidence?.[key]) && evidence[key].length > 0);
  if (!shouldHide.length) return rows;
  return rows.filter((row) => !shouldHide.includes(row.key));
}

function groupedResults(project) {
  const rows = Array.isArray(project?.results) ? project.results : [];
  const groups = [
    { key: 'passed', title: '通过', items: [] },
    { key: 'warning', title: '警示', items: [] },
    { key: 'failed', title: '未通过', items: [] },
  ];
  rows.forEach((item) => {
    const status = String(item?.status || '').toLowerCase();
    const target = groups.find((group) => group.key === status);
    if (target) target.items.push(item);
  });
  return groups;
}

function resultGroupClass(key) {
  const k = String(key || '').toLowerCase();
  if (k === 'passed') return 'group-pass';
  if (k === 'warning') return 'group-warn';
  if (k === 'failed') return 'group-fail';
  return 'group-default';
}

function zhRule(code) {
  const map = {
    registered_date_limit: '注册时间',
    funding_ratio_check: '财政/自筹比例',
    external_status_check: '科研/社会失信',
    ethics_approval_required: '伦理审查意见',
    industry_permit_required: '行业准入许可',
    biosafety_commitment_required: '生物安全承诺',
    commitment_letter_required: '承诺书',
    cooperation_agreement_required: '合作协议',
    cooperation_region_check: '合作地区',
    recommendation_letter_required: '管理部门推荐函',
    execution_period_limit: '执行期限',
    duplicate_submission_check: '重复/多头申报',
    other_policy_compliance: '其他政策条款',
  };
  return map[String(code || '').trim()] || '审查要点';
}

function zhDocKind(kind) {
  const map = {
    commitment_letter: '承诺书',
    ethics_approval: '伦理审查意见',
    biosafety_commitment: '生物安全承诺书',
    cooperation_agreement: '合作协议',
    recommendation_letter: '管理部门推荐函',
    industry_permit: '行业准入许可材料',
  };
  return map[String(kind || '').trim()] || '附件材料';
}

function zhText(text) {
  let out = String(text || '');
  const tokenMap = {
    commitment_letter: '承诺书',
    ethics_approval: '伦理审查意见',
    biosafety_commitment: '生物安全承诺书',
    cooperation_agreement: '合作协议',
    recommendation_letter: '管理部门推荐函',
    industry_permit: '行业准入许可材料',
    regional_innovation: '区域科技创新体系项目',
    basic_research: '基础研究项目',
    warning: '警示',
    failed: '未通过',
    passed: '通过',
  };
  Object.entries(tokenMap).forEach(([en, zh]) => {
    out = out.replaceAll(en, zh);
  });
  return out;
}

</script>

<template>
  <div class="content-scroll review-debug-page">
    <section class="panel-shell panel-shell-stretch review-debug-shell">
      <div v-if="loading" class="state-block">正在加载小批量测试结果...</div>
      <div v-else-if="errorText" class="state-block state-error">{{ errorText }}</div>

      <div v-else class="review-layout">
        <div class="top-filter-bar">
          <div class="top-filter-title">形式审查结果</div>
          <input
            v-model="keyword"
            class="search-input"
            placeholder="按项目编号/名称过滤"
          >
          <select v-model="selectedProjectId" class="project-select-dropdown">
            <option
              v-for="project in filteredProjects"
              :key="project.project_id"
              :value="project.project_id"
            >
              {{ project.project_name || '未命名项目' }}（{{ project.project_id }}）
            </option>
          </select>
        </div>

        <div class="split-grid split-grid-2">

          <section class="middle-pane">
            <div class="pane-title">{{ guidelineTitle }} </div>
            <div v-if="selectedProject" class="middle-subtitle">{{ selectedProject.project_name || selectedProject.project_id }}</div>
            <div v-if="hasAny(projectGuidelineTables)" class="middle-clause-list">
              <article v-for="(table, idx) in projectGuidelineTables" :key="`${table.table_index}_${idx}`" class="middle-clause-card">
                <div class="middle-clause-head">
                  <span class="middle-table-tag">{{ table.title || '未命名表格' }}</span>
                  <span class="middle-seq">第 {{ table.table_index }} 表</span>
                </div>
                <div v-if="hasAny(table.rows)" class="table-row-list">
                  <div v-for="(row, rowIdx) in table.rows" :key="`${table.table_index}_${row.seq}_${rowIdx}`" class="table-row-item">
                    <span class="table-row-seq">{{ row.seq || '—' }}</span>
                    <span class="table-row-content">{{ row.content || '-' }}</span>
                  </div>
                </div>
                <div v-else class="sub-empty">该表暂无内容</div>
              </article>
            </div>
            <div v-else class="sub-empty">当前项目未命中文档表格内容</div>
          </section>

          <section class="right-pane">
            <div class="pane-title">项目审查详情</div>
            <article v-if="selectedProject" class="project-card project-card-full">
            <div class="project-top">
              <div class="project-id">{{ selectedProject.project_id }}</div>
              <div class="project-name">{{ selectedProject.project_name || '未命名项目' }}</div>
            </div>

            <div v-if="selectedProject.summary" class="project-summary">{{ selectedProject.summary }}</div>

            <div class="meta-grid">
              <div class="meta-item"><span>年度</span><strong>{{ selectedProject.project_meta?.year || '-' }}</strong></div>
              <div class="meta-item"><span>指南</span><strong>{{ selectedProject.project_meta?.guide_name || '-' }}</strong></div>
              <div class="meta-item"><span>申报单位</span><strong>{{ selectedProject.project_meta?.applicant_unit || '-' }}</strong></div>
              <div class="meta-item"><span>负责人</span><strong>{{ selectedProject.project_meta?.project_leader || '-' }}</strong></div>
            </div>

            <div class="section-title">结果明细</div>
            <div v-if="hasAny(selectedProject.results)" class="overview-stack">
              <section v-for="section in groupedResults(selectedProject)" :key="section.key" class="overview-block" :class="resultGroupClass(section.key)">
                <div class="overview-head">
                  <span>{{ section.title }}</span>
                  <span class="overview-count">{{ section.items.length }}</span>
                </div>
                <div v-if="hasAny(section.items)" class="result-list">
                  <details v-for="(item, idx) in section.items" :key="`${selectedProject.project_id}_result_${section.key}_${item.item}_${idx}`" class="accordion-card result-row">
                    <summary class="accordion-summary">
                      <div class="accordion-summary-main">
                        <span class="result-item">{{ zhText(item.message || item.item) }}</span>
                        <span class="accordion-summary-sub">{{ zhRule(item.item) }}</span>
                      </div>
                    </summary>
                    <div class="accordion-body">
                      <div v-if="item.evidence && structuredEvidenceSections(item.evidence, selectedProject).length" class="review-point-grid">
                        <div v-for="section in structuredEvidenceSections(item.evidence, selectedProject)" :key="section.key" class="review-section-card">
                          <div class="review-section-title">{{ section.title }}</div>
                          <div class="review-section-items">
                            <div v-for="entry in section.items" :key="entry.key" class="review-point-card">
                              <div class="review-point-head">{{ entry.title }}</div>
                              <div v-for="(line, lineIdx) in entry.lines" :key="`${entry.key}_${lineIdx}`" class="review-point-line">{{ line }}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                      <div class="result-desc" v-if="item.evidence && Object.keys(item.evidence).length">
                        <div v-for="entry in evidenceRowsForDisplay(item.evidence, selectedProject)" :key="entry.key" class="result-evidence">
                          <span class="result-evidence-label">{{ entry.label }}</span>
                          <span class="result-evidence-value">{{ entry.value }}</span>
                        </div>
                      </div>
                      <div v-else class="sub-empty">暂无详细证据</div>
                    </div>
                  </details>
                </div>
                <div v-else class="sub-empty">该状态无结果项</div>
              </section>
            </div>
            <div v-else class="sub-empty">当前无结果明细</div>

            <div class="section-title">缺失附件</div>
            <div v-if="hasAny(selectedProject.missing_attachments)" class="manual-list">
              <div v-for="item in selectedProject.missing_attachments" :key="`${selectedProject.project_id}_${item.doc_kind}`" class="manual-row">
                <div class="manual-head">{{ zhText(item.doc_label || zhDocKind(item.doc_kind)) }}</div>
                <div class="manual-desc manual-desc-strong">缺失原因：{{ zhText(item.reason) || '-' }}</div>
              </div>
            </div>
            <div v-else class="sub-empty">未发现缺失附件</div>

            <div class="section-title">人工复核项</div>
            <div v-if="hasAny(selectedProject.manual_review_items)" class="manual-list">
              <div v-for="item in selectedProject.manual_review_items" :key="`${selectedProject.project_id}_${item.code}`" class="manual-row">
                <div class="manual-head">{{ zhText(item.message) || zhRule(item.code) }}</div>
                <div class="manual-desc manual-desc-strong">复核原因：{{ zhText(item.reason) || '-' }}</div>
              </div>
            </div>
            <div v-else class="sub-empty">无人工复核项</div>

            <div class="section-title">建议</div>
            <div v-if="hasAny(selectedProject.suggestions)" class="manual-list">
              <div v-for="(item, idx) in selectedProject.suggestions" :key="`${selectedProject.project_id}_suggestion_${idx}`" class="manual-row">
                <div class="manual-desc suggestion-text">{{ zhText(item) || '-' }}</div>
              </div>
            </div>
            <div v-else class="sub-empty">暂无建议</div>
            </article>
            <div v-else class="sub-empty">当前无项目数据</div>
          </section>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.review-debug-shell {
  padding: 14px;
  background:
    radial-gradient(circle at 15% 0%, #f3f8ff 0%, transparent 40%),
    radial-gradient(circle at 100% 100%, #fff6ef 0%, transparent 34%);
}

.state-block {
  padding: 20px;
  border: 1px solid #dce4ef;
  border-radius: 10px;
  background: #f8fbff;
}

.state-error {
  color: #b42318;
  background: #fff5f6;
  border-color: #f0c6cc;
}

.split-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-height: 70vh;
}

.split-grid-3 {
  grid-template-columns: 160px minmax(0, 1.24fr) minmax(0, 1.36fr);
}

.split-grid-2 {
  grid-template-columns: minmax(0, 1.14fr) minmax(0, 1.36fr);
}

.review-layout {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.top-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #dce4ef;
  border-radius: 12px;
  padding: 10px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcff 100%);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
}

.top-filter-title {
  font-size: 13px;
  font-weight: 700;
  color: #0b1220;
  white-space: nowrap;
}

.project-pane {
  width: 160px;
  max-width: 160px;
  padding: 10px 10px 8px;
}

.left-pane,
.right-pane {
  border: 1px solid #dce4ef;
  border-radius: 12px;
  padding: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcff 100%);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.middle-pane {
  border: 1px solid #dce4ef;
  border-radius: 12px;
  padding: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcff 100%);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.pane-title {
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 10px;
  color: #0b1220;
}

.pane-title-tight {
  margin-bottom: 8px;
}

.search-input {
  width: 100%;
  border: 1px solid #bfd0e8;
  border-radius: 10px;
  padding: 9px 12px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #0f172a;
  background: #ffffff;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}

.top-filter-bar .search-input {
  margin-left: auto;
  margin-bottom: 0;
  width: 250px;
}

.project-select-dropdown {
  width: 100%;
  border: 1px solid #bfd0e8;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13px;
  line-height: 1.35;
  color: #0f172a;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
}

.top-filter-bar .project-select-dropdown {
  width: 320px;
  max-width: 45vw;
}

.project-select-dropdown:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.left-pane {
  position: relative;
}

.project-select-item {
  border: 1px solid #dbe3ef;
  border-radius: 10px;
  background: #fff;
  padding: 8px;
  text-align: left;
  cursor: pointer;
}

.project-select-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.project-select-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.project-select-id {
  margin-top: 3px;
  font-size: 11px;
  color: #64748b;
  word-break: break-all;
}

.middle-subtitle {
  margin-bottom: 8px;
  font-size: 12px;
  color: #475467;
}

.middle-clause-list {
  overflow: auto;
  display: grid;
  gap: 8px;
}

.middle-clause-card {
  border: 1px solid #dbe4f2;
  border-radius: 10px;
  padding: 10px;
  background: #ffffff;
}

.middle-clause-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}

.middle-table-tag,
.middle-seq {
  background: #f2f4f7;
  color: #344054;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
}

.middle-clause-content {
  font-size: 13px;
  color: #1f2937;
  line-height: 1.45;
}

.middle-clause-reason {
  margin-top: 5px;
  font-size: 12px;
  color: #64748b;
}

.table-row-list {
  display: grid;
  gap: 6px;
}

.table-row-item {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  padding: 6px 0;
  border-top: 1px dashed #e2e8f0;
}

.table-row-item:first-child {
  border-top: 0;
}

.table-row-seq {
  font-size: 12px;
  color: #475467;
  font-weight: 700;
}

.table-row-content {
  font-size: 13px;
  color: #1f2937;
  line-height: 1.5;
}

.point-list {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.point-chip {
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 6px 8px;
  font-size: 11px;
  background: #fff;
  cursor: pointer;
  width: 100%;
  text-align: center;
}

.point-chip.active {
  border-color: #2563eb;
  color: #1d4ed8;
  background: #eff6ff;
}

.doc-scroll {
  overflow: auto;
  border-top: 1px dashed #dbe3ef;
  padding-top: 8px;
}

.guideline-section {
  margin-bottom: 12px;
}

.guideline-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
  text-align: center;
}

.guideline-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #dbe3ef;
}

.guideline-table th,
.guideline-table td {
  border: 1px solid #dbe3ef;
  padding: 8px 10px;
  vertical-align: middle;
  text-align: center;
}

.guideline-table thead th {
  background: #f8fafc;
  font-size: 13px;
  text-align: center;
}

.guideline-table .seq-col {
  width: 64px;
  text-align: center;
  font-weight: 700;
}

.guideline-table tbody tr.related {
  background: #fffbeb;
}

.row-requirement {
  font-size: 13px;
  color: #334155;
  line-height: 1.5;
}

.doc-pre {
  margin: 8px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: #1f2937;
  font-family: inherit;
}

.search-input {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 10px;
}

.project-list {
  overflow: auto;
  display: grid;
  gap: 10px;
}

.project-card {
  border: 1px solid #d7e3f3;
  border-radius: 10px;
  padding: 16px;
  background: #ffffff;
}

.project-card-full {
  overflow: auto;
}

.project-summary {
  margin-top: 10px;
  color: #334155;
  background: #f7faff;
  border: 1px solid #dbe7f7;
  border-radius: 10px;
  padding: 10px;
  font-size: 13px;
}

.meta-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.meta-item {
  border: 1px solid #e3eaf6;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #fcfdff;
}

.meta-item span {
  font-size: 12px;
  color: #64748b;
}

.meta-item strong {
  font-size: 13px;
  color: #0f172a;
}

.project-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  color: #334155;
}

.project-name {
  margin-top: 6px;
  font-weight: 700;
  font-size: 16px;
  line-height: 1.45;
}

.result-list {
  display: grid;
  gap: 6px;
  margin-top: 6px;
}

.result-row {
  border: 1px solid #dae5f5;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
}

.accordion-card {
  overflow: hidden;
  border: 1px solid #dae5f5;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
}

.accordion-card[open] {
  border-color: #c9d9f1;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}

.accordion-summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 9px 7px;
}

.accordion-summary::-webkit-details-marker {
  display: none;
}

.accordion-summary::marker {
  display: none;
}

.accordion-summary-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.accordion-summary-sub {
  font-size: 11px;
  color: #667085;
  line-height: 1.15;
}

.accordion-card .accordion-body {
  padding: 0 9px 9px;
}

.accordion-card .result-desc,
.accordion-card .manual-desc {
  margin-top: 0;
}

.accordion-card .result-evidence:last-child,
.accordion-card .manual-desc:last-child {
  margin-bottom: 0;
}

.accordion-card .manual-head {
  margin-bottom: 0;
}

.accordion-card summary .rule-status {
  margin-top: 2px;
  flex-shrink: 0;
}

.result-head {
  display: grid;
  gap: 10px;
}

.result-item {
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  line-height: 1.18;
}

.result-desc {
  margin-top: 8px;
  display: grid;
  gap: 6px;
}

.result-evidence {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f8fbff;
  border: 1px solid #dbe7f7;
  word-break: break-word;
}

.result-evidence-label {
  font-size: 11px;
  font-weight: 700;
  color: #475467;
}

.result-evidence-value {
  font-size: 12px;
  line-height: 1.25;
  color: #1f2937;
}

.review-point-grid {
  display: grid;
  gap: 8px;
  margin-bottom: 8px;
}

.review-section-card {
  border: 1px solid #dce6f4;
  border-radius: 10px;
  background: #f8fbff;
  padding: 8px;
}

.review-section-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 6px;
}

.review-section-items {
  display: grid;
  gap: 6px;
}

.review-point-card {
  border: 1px solid #dbe5f3;
  border-radius: 10px;
  padding: 8px 10px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.review-point-head {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 4px;
  line-height: 1.2;
}

.review-point-line {
  font-size: 12px;
  line-height: 1.22;
  color: #334155;
  margin-top: 1px;
}

.overview-stack {
  display: grid;
  gap: 12px;
}

.overview-block {
  border: 1px solid #dbe5f3;
  border-radius: 12px;
  background: #ffffff;
  padding: 8px;
}

.overview-block.group-pass {
  border-color: rgba(6, 118, 71, 0.18);
}

.overview-block.group-warn {
  border-color: rgba(181, 71, 8, 0.18);
}

.overview-block.group-fail {
  border-color: rgba(180, 35, 24, 0.18);
}

.overview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  background: linear-gradient(90deg, #f2f6fd 0%, #f8fbff 100%);
}

.overview-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  min-width: 0;
  height: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: 11px;
  font-weight: 700;
}

.overview-block.group-pass .overview-head,
.overview-block.group-pass .overview-count {
  color: #067647;
}

.overview-block.group-warn .overview-head,
.overview-block.group-warn .overview-count {
  color: #b54708;
}

.overview-block.group-fail .overview-head,
.overview-block.group-fail .overview-count {
  color: #b42318;
}

.rule-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.2px;
  border: 1px solid transparent;
  white-space: nowrap;
}

.rule-status.st-passed {
  color: #05603a;
  border-color: #9ad7b4;
  background: linear-gradient(180deg, #f1fcf5 0%, #e6f9ee 100%);
}

.rule-status.st-warning {
  color: #9a3412;
  border-color: #f2bf8a;
  background: linear-gradient(180deg, #fff8eb 0%, #fff1d8 100%);
}

.rule-status.st-failed {
  color: #991b1b;
  border-color: #efb4b4;
  background: linear-gradient(180deg, #fff3f2 0%, #fee8e7 100%);
}

.rule-status.st-default {
  color: #334155;
  border-color: #d3dce8;
  background: #f8fafc;
}

.section-title {
  margin-top: 18px;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  padding: 10px 12px;
  border-left: 3px solid #4f46e5;
  border-radius: 10px;
  background: linear-gradient(90deg, #f5f7ff 0%, #ffffff 100%);
}

.manual-list {
  display: grid;
  gap: 12px;
}

.manual-row {
  border: 1px solid #d9e5f3;
  border-radius: 14px;
  padding: 12px 14px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
}

.manual-head {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 4px;
  color: #0f172a;
  line-height: 1.25;
}

.manual-desc {
  font-size: 13px;
  color: #334155;
  line-height: 1.3;
}

.manual-desc-strong {
  font-size: 14px;
  line-height: 1.3;
}

.suggestion-text {
  font-size: 14px;
  line-height: 1.35;
}

.sub-empty {
  color: #667085;
  font-size: 12px;
}

@media (max-width: 900px) {
  .top-filter-bar {
    flex-wrap: wrap;
  }

  .top-filter-bar .search-input,
  .top-filter-bar .project-select-dropdown {
    width: 100%;
    max-width: none;
  }

  .top-filter-title {
    width: 100%;
  }

  .split-grid {
    grid-template-columns: 1fr;
  }

  .project-pane {
    width: auto;
    max-width: none;
  }
}
</style>
