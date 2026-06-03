<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';

const loading = ref(true);
const errorText = ref('');
const payload = ref(null);
const API_BASE_STORAGE_KEY = 'tech_api_base';

const state = reactive({
  projectIndex: 0,
  ruleId: '',
  evidenceIndex: 0,
});

function runtimeApiBase() {
  const envBase = String(import.meta.env.VITE_API_BASE || '').trim();
  if (envBase) return envBase.replace(/\/+$/, '');
  const { protocol, hostname, port } = window.location;
  const p = String(port || '').trim();
  const backendPort = p === '8006' ? '8005' : (p || '8000');
  return `${protocol}//${hostname}:${backendPort}/api/v1`;
}

function apiBase() {
  const saved = localStorage.getItem(API_BASE_STORAGE_KEY);
  if (saved && saved.trim()) return saved.trim().replace(/\/+$/, '');
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
    initializeState();
    await nextTick();
    renderAll();
  } catch (error) {
    errorText.value = String(error?.message || error || '加载失败');
  } finally {
    loading.value = false;
  }
}

const STATUS_LABELS = {
  failed: '不通过',
  warning: '警告',
  passed: '通过',
  manual: '需人工处理',
  requires_data: '待补数据',
  not_applicable: '不适用',
  skipped: '跳过',
  system_managed: '系统已限制',
};

const PROJECT_TYPE_LABELS = {
  regional_innovation: '区域创新体系建设项目',
  basic_research: '基础研究项目',
  innovation_base: '科技创新基地建设项目',
  transfer_transformation: '科技成果转移转化项目',
};

const reportData = computed(() => {
  if (!payload.value || typeof payload.value !== 'object') return { projects: [] };
  if (payload.value.reportData && typeof payload.value.reportData === 'object') return payload.value.reportData;
  return payload.value;
});

function normalizeEvidenceTargets(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map((target, idx) => ({
    target_id: String(target?.target_id || `target_${idx + 1}`),
    tab_label: String(target?.tab_label || target?.label || `证据 ${idx + 1}`),
    source_file: String(target?.source_file || '-'),
    location_label: String(target?.location_label || target?.position || '规则说明'),
    clip: String(target?.clip || target?.text || target?.summary || ''),
    open_uri: String(target?.open_uri || ''),
    preview_uri: String(target?.preview_uri || ''),
    preview_mode: String(target?.preview_mode || 'none'),
    viewer_mode: String(target?.viewer_mode || 'explanation'),
    anchor_id: String(target?.anchor_id || ''),
    packet_uri: String(target?.packet_uri || ''),
    packet_page: Number(target?.packet_page || 0),
    highlight_mode: String(target?.highlight_mode || 'none'),
    highlight_text: String(target?.highlight_text || ''),
    highlight_rects: Array.isArray(target?.highlight_rects) ? target.highlight_rects : [],
  }));
}

function buildRuleItemFromCheck(check, index) {
  const status = String(check?.status || '').toLowerCase() || 'not_applicable';
  const code = String(check?.code || '').trim();
  const title = String(check?.label || code || `规则 ${index + 1}`);
  const requirement = String(check?.requirement || check?.summary || '').trim();
  const summary = String(check?.reason || check?.summary || '').trim() || '无';
  return {
    id: `policy:${code || index + 1}`,
    title,
    requirement,
    status,
    status_label: STATUS_LABELS[status] || status,
    source_rule_label: title,
    summary,
    group: status,
    evidence_targets: normalizeEvidenceTargets(check?.evidence_targets),
  };
}

function normalizeProject(project) {
  if (Array.isArray(project?.policy_sections)) {
    return {
      ...project,
      project_type_label: project.project_type_label || PROJECT_TYPE_LABELS[String(project.project_type || '')] || String(project.project_type || ''),
      counts: project.counts || project.status_counts || {},
      extra_sections: Array.isArray(project.extra_sections) ? project.extra_sections : [],
    };
  }

  const checks = Array.isArray(project?.policy_rule_checks) ? project.policy_rule_checks : [];
  const checkItems = checks.map(buildRuleItemFromCheck);

  const missingItems = (project?.missing_attachments || []).map((item, idx) => ({
    id: `missing:${idx + 1}`,
    title: `缺失附件：${String(item?.doc_label || item?.doc_kind || `附件${idx + 1}`)}`,
    requirement: String(item?.reason || '未提交必需附件'),
    status: 'failed',
    status_label: STATUS_LABELS.failed,
    source_rule_label: '缺失附件检查',
    summary: String(item?.reason || '缺失附件'),
    group: 'failed',
    evidence_targets: [],
  }));

  const manualItems = (project?.manual_review_items || []).map((item, idx) => ({
    id: `manual:${String(item?.code || idx + 1)}`,
    title: String(item?.label || item?.code || `人工复核 ${idx + 1}`),
    requirement: String(item?.message || item?.reason || '需人工复核'),
    status: 'manual',
    status_label: STATUS_LABELS.manual,
    source_rule_label: String(item?.automation || '人工复核'),
    summary: String(item?.reason || item?.message || '需人工复核'),
    group: 'manual',
    evidence_targets: [],
  }));

  const groupsOrder = ['failed', 'warning', 'manual', 'requires_data', 'passed', 'not_applicable', 'system_managed', 'skipped'];
  const grouped = groupsOrder
    .map((status) => ({
      status,
      label: STATUS_LABELS[status] || status,
      items: checkItems.filter((x) => x.status === status),
      folded: status === 'not_applicable' || status === 'system_managed' || status === 'skipped',
    }))
    .filter((g) => g.items.length > 0);

  const extraGroups = [];
  if (missingItems.length) {
    extraGroups.push({ status: 'failed', label: STATUS_LABELS.failed, items: missingItems, folded: false });
  }
  if (manualItems.length) {
    extraGroups.push({ status: 'manual', label: STATUS_LABELS.manual, items: manualItems, folded: false });
  }

  const statusCounts = project?.status_counts || {};
  const failedCount = Number(statusCounts.failed || 0) + missingItems.length;
  const manualCount = Number(statusCounts.manual || 0) + manualItems.length;

  return {
    ...project,
    project_type_label: project.project_type_label || PROJECT_TYPE_LABELS[String(project.project_type || '')] || String(project.project_type || ''),
    counts: {
      failed: failedCount,
      manual: manualCount,
      passed: Number(statusCounts.passed || 0),
      warning: Number(statusCounts.warning || 0),
      skipped: Number(statusCounts.skipped || 0),
    },
    policy_sections: [{ title: '形式审查要点对照', groups: grouped }],
    extra_sections: extraGroups.length ? [{ title: '额外检查项', groups: extraGroups }] : [],
  };
}

const projects = computed(() => {
  const list = Array.isArray(reportData.value?.projects) ? reportData.value.projects : [];
  return list.map(normalizeProject);
});

const reportAssetsBase = computed(() => String(payload.value?.reportAssetsBase || '').trim().replace(/\/+$/, ''));

function resolveAssetUri(uri) {
  const raw = String(uri || '').trim();
  if (!raw) return '';
  if (/^(https?:|file:|data:|blob:)/i.test(raw)) return raw;
  if (raw.startsWith('/')) return raw;
  if (reportAssetsBase.value) {
    return `${reportAssetsBase.value}/${raw.replace(/^\/+/, '')}`;
  }
  return raw;
}

const attentionCount = computed(() => {
  return projects.value.filter((p) => Number(p?.counts?.failed || 0) > 0 || Number(p?.counts?.manual || 0) > 0).length;
});

const batchLabel = computed(() => {
  const fileName = String(payload.value?.guideline?.file_name || '').trim();
  if (fileName) return fileName.replace(/\.docx$/i, '');
  return 'batch_review_db832d940a2843e6b3c33970336d0e9e';
});

const batchNote = computed(() => {
  const p = projects.value[state.projectIndex];
  return String(p?.summary || '存在附件类型识别不确定的项目，建议优先人工复核材料类型');
});

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function statusBadge(status, label) {
  const safeStatus = String(status || 'not_applicable');
  const safeLabel = String(label || safeStatus);
  return `<span class="badge status-${escapeHtml(safeStatus)}">${escapeHtml(safeLabel)}</span>`;
}

function initializeState() {
  if (!projects.value.length) {
    state.projectIndex = 0;
    state.ruleId = '';
    state.evidenceIndex = 0;
    return;
  }
  state.projectIndex = Math.max(0, Math.min(state.projectIndex, projects.value.length - 1));
  const project = projects.value[state.projectIndex];
  state.ruleId = findPreferredRuleId(project) || project.default_rule_id || findFirstRuleId(project) || '';
  state.evidenceIndex = 0;
}

function findFirstRuleId(project) {
  const sections = [...(project?.policy_sections || []), ...(project?.extra_sections || [])];
  for (const section of sections) {
    for (const group of (section.groups || [])) {
      if (group.items && group.items.length) {
        return group.items[0].id;
      }
    }
  }
  return '';
}

function hasNavigableEvidence(item) {
  const targets = item?.evidence_targets || [];
  return targets.some((target) => Number(target?.packet_page || 0) > 0);
}

function findPreferredRuleId(project) {
  const sections = [...(project?.policy_sections || []), ...(project?.extra_sections || [])];
  for (const preferredStatus of ['failed', 'manual', 'passed']) {
    for (const section of sections) {
      for (const group of (section.groups || [])) {
        for (const item of (group.items || [])) {
          if (String(item.status || '') === preferredStatus && hasNavigableEvidence(item)) {
            return item.id;
          }
        }
      }
    }
  }
  for (const section of sections) {
    for (const group of (section.groups || [])) {
      for (const item of (group.items || [])) {
        if (hasNavigableEvidence(item)) return item.id;
      }
    }
  }
  return '';
}

function selectProject(index) {
  state.projectIndex = index;
  const project = projects.value[index];
  state.ruleId = findPreferredRuleId(project) || project.default_rule_id || findFirstRuleId(project) || '';
  state.evidenceIndex = 0;
  renderAll();
}

function selectRule(ruleId, cycleEvidence = true) {
  const project = projects.value[state.projectIndex];
  if (state.ruleId === ruleId) {
    if (cycleEvidence && project) {
      const rule = getActiveRule(project);
      if (rule) {
        const navTargets = (rule.evidence_targets || []).filter(t => Number(t?.packet_page || 0) > 0);
        if (navTargets.length > 1) {
          const currentTarget = (rule.evidence_targets || [])[state.evidenceIndex];
          let navIdx = navTargets.indexOf(currentTarget);
          navIdx = (navIdx + 1) % navTargets.length;
          state.evidenceIndex = (rule.evidence_targets || []).indexOf(navTargets[navIdx]);
        }
      }
    }
  } else {
    state.ruleId = ruleId;
    state.evidenceIndex = 0;
    if (project) {
      const rule = [...(project?.policy_sections||[]), ...(project?.extra_sections||[])]
        .flatMap(s => s.groups||[])
        .flatMap(g => g.items||[])
        .find(i => i.id === ruleId);
      if (rule) {
        const firstNav = (rule.evidence_targets || []).findIndex(t => Number(t?.packet_page || 0) > 0);
        if (firstNav >= 0) {
          state.evidenceIndex = firstNav;
        }
      }
    }
  }
  renderRulesPanel();
  renderPdfPanel();
}

function renderProjectList() {
  const container = document.getElementById('projectList');
  if (!container) return;
  if (!projects.value.length) {
    container.innerHTML = '<div class="empty">无项目结果</div>';
    return;
  }
  container.innerHTML = projects.value.map((project, index) => `
    <button class="project-item ${index === state.projectIndex ? 'active' : ''}" data-project-index="${index}">
      <div class="project-item-title">${escapeHtml(project.project_name || project.project_id)}</div>
      <div class="project-item-meta">${escapeHtml(project.project_id)} · ${escapeHtml(project.project_type_label || project.project_type)}</div>
      <div class="project-item-stats">
        ${statusBadge('failed', `失败 ${Number(project?.counts?.failed || 0)}`)}
        ${statusBadge('manual', `需人工 ${Number(project?.counts?.manual || 0)}`)}
      </div>
    </button>
  `).join('');

  container.querySelectorAll('.project-item').forEach((node) => {
    node.addEventListener('click', () => {
      const index = Number(node.dataset.projectIndex || 0);
      selectProject(index);
    });
  });
}

function getActiveRule(project) {
  const sections = [...(project?.policy_sections || []), ...(project?.extra_sections || [])];
  for (const section of sections) {
    for (const group of (section.groups || [])) {
      const item = (group.items || []).find((entry) => entry.id === state.ruleId);
      if (item) return item;
    }
  }
  return null;
}

function renderSections(sections, fallbackTitle) {
  if (!sections || !sections.length) {
    return `<section class="result-section"><div class="section-head"><div class="section-head-title">${escapeHtml(fallbackTitle)}</div></div><div class="empty">无</div></section>`;
  }
  return sections.map((section) => `
    <section class="result-section">
      <div class="section-head">
        <div class="section-head-title">${escapeHtml(section.title)}</div>
      </div>
      <div class="section-subgroups">
        ${renderGroups((section.groups || []).filter((group) => !group.folded))}
        ${renderFoldedGroups((section.groups || []).filter((group) => group.folded))}
      </div>
    </section>
  `).join('');
}

function renderGroups(groups) {
  if (!groups.length) return '<div class="empty">无</div>';
  return groups.map((group) => `
    <section class="status-group">
      <div class="status-group-head">
        ${statusBadge(group.status, group.label)}
        <span class="status-group-count">${(group.items || []).length} 项</span>
      </div>
      <div class="rule-list">
        ${(group.items || []).map((item) => renderRuleCard(item)).join('')}
      </div>
    </section>
  `).join('');
}

function renderFoldedGroups(groups) {
  if (!groups.length) return '';
  const total = groups.reduce((sum, group) => sum + (group.items || []).length, 0);
  return `
    <details class="folded-toggle">
      <summary>系统前置限制 / 不适用（${total} 项）</summary>
      <div class="folded-body">${renderGroups(groups)}</div>
    </details>
  `;
}

function renderRuleCard(item) {
  const navigableTargets = (item?.evidence_targets || []).filter(t => Number(t?.packet_page || 0) > 0);
  const evidenceCount = navigableTargets.length;
  const isSelected = item.id === state.ruleId;
  
  let evidenceHtml = '<div>无可跳转证据</div>';
  if (evidenceCount > 0) {
    if (evidenceCount === 1) {
      evidenceHtml = `<div class="evidence-locator">1 个命中</div>`;
    } else {
      let currentNavIndex = 0;
      if (isSelected) {
        const currentTarget = (item.evidence_targets || [])[state.evidenceIndex];
        currentNavIndex = navigableTargets.indexOf(currentTarget);
        if (currentNavIndex === -1) currentNavIndex = 0;
      }
      const text = isSelected ? `${evidenceCount} 个命中 (第 ${currentNavIndex + 1} 个)` : `${evidenceCount} 个命中`;
      evidenceHtml = `<div class="evidence-locator">${text}</div>`;
    }
  }

  return `
    <button class="rule-card ${isSelected ? 'active' : ''}" data-rule-id="${escapeHtml(item.id)}">
      <div class="rule-card-top">
        <div class="rule-card-title">${escapeHtml(item.title)}</div>
        <div>${statusBadge(item.status, item.status_label)}</div>
      </div>
      <div class="rule-card-requirement">${escapeHtml(item.requirement || item.summary)}</div>
      <div class="rule-card-meta">
        <div class="rule-card-meta-label">核验来源</div><div>${escapeHtml(item.source_rule_label || '-')}</div>
        <div class="rule-card-meta-label">结果说明</div><div>${escapeHtml(item.summary || '-')}</div>
        <div class="rule-card-meta-label">证据定位</div>${evidenceHtml}
      </div>
    </button>
  `;
}

function renderRulesPanel() {
  const panel = document.getElementById('rulesPanel');
  if (!panel) return;
  const project = projects.value[state.projectIndex];
  if (!project) {
    panel.innerHTML = '<div class="empty">无项目</div>';
    return;
  }
  panel.innerHTML = `
    <div class="panel-head">
      <h2>${escapeHtml(project.project_name || project.project_id)}</h2>
      <div class="project-summary">${escapeHtml(project.project_type_label || project.project_type)} · ${statusBadge('failed', `失败 ${Number(project?.counts?.failed || 0)}`)} ${statusBadge('manual', `需人工 ${Number(project?.counts?.manual || 0)}`)}</div>
    </div>
    <div class="result-sections">
      ${renderSections(project.policy_sections || [], '审查要点对照')}
      ${renderSections(project.extra_sections || [], '额外检查项')}
    </div>
  `;

  panel.querySelectorAll('.rule-card').forEach((node) => {
    node.addEventListener('click', (e) => {
      const isLocator = !!e.target.closest('.evidence-locator');
      selectRule(String(node.dataset.ruleId || ''), isLocator);
    });
  });
}

function ensurePdfShell() {
  const viewer = document.getElementById('pdfPanel');
  if (!viewer) return null;
  if (!viewer.dataset.initialized) {
    viewer.innerHTML = `
      <div class="pdf-only">
        <div class="pdf-toast" id="pdfToast"></div>
        <div class="viewer-preview hidden" id="viewerPreview">
          <iframe class="packet-frame" id="packetFrame" title="review packet viewer"></iframe>
        </div>
        <div class="viewer-fallback" id="viewerFallback">选择一条规则后，在这里查看对应材料。</div>
      </div>
    `;
    viewer.dataset.initialized = '1';
  }
  return viewer;
}

function showPdfToast(message) {
  const toast = document.getElementById('pdfToast');
  if (!toast) return;
  if (toast.dataset.timerId) clearTimeout(Number(toast.dataset.timerId));
  toast.textContent = String(message || '');
  toast.classList.add('show');
  const timerId = window.setTimeout(() => {
    toast.classList.remove('show');
    toast.textContent = '';
    toast.dataset.timerId = '';
  }, 1800);
  toast.dataset.timerId = String(timerId);
}

function buildViewerPayload(target, packetPage) {
  return {
    type: 'gotoPacketTarget',
    page: Number(packetPage || 0),
    location_label: String(target.location_label || ''),
    highlight_mode: String(target.highlight_mode || 'none'),
    highlight_text: String(target.highlight_text || target.clip || ''),
    highlight_rects: Array.isArray(target.highlight_rects) ? target.highlight_rects : [],
  };
}

function postViewerPayload(frame, payload) {
  const pageNumber = Number(payload?.page || 0);
  if (!frame || !pageNumber) return;
  const send = () => {
    try {
      frame.contentWindow?.postMessage(payload, '*');
    } catch {}
  };
  window.setTimeout(send, 0);
  window.setTimeout(send, 120);
  window.setTimeout(send, 320);
}

function setViewerPacket(viewerUri, payload) {
  const frame = document.getElementById('packetFrame');
  if (!frame) return;
  const nextUri = String(viewerUri || '');
  const pageNumber = Number(payload?.page || 0);

  if (!nextUri) {
    frame.removeAttribute('src');
    frame.dataset.viewerUri = '';
    frame.dataset.pendingPayload = '';
    return;
  }

  if (frame.dataset.viewerUri !== nextUri) {
    frame.dataset.viewerUri = nextUri;
    frame.dataset.pendingPayload = JSON.stringify(payload || {});
    frame.onload = () => {
      const pending = frame.dataset.pendingPayload ? JSON.parse(frame.dataset.pendingPayload) : null;
      if (pending && Number(pending.page || 0) > 0) postViewerPayload(frame, pending);
    };
    frame.src = nextUri;
    return;
  }

  if (pageNumber > 0) {
    frame.dataset.pendingPayload = JSON.stringify(payload || {});
    postViewerPayload(frame, payload);
  }
}

function renderEvidenceTarget(target, project) {
  const packet = project.packet || {};
  const packetPage = target.packet_page ? Number(target.packet_page) : 0;
  const viewerUri = resolveAssetUri(packet.viewer_file ? String(packet.viewer_file) : '');
  const previewNode = document.getElementById('viewerPreview');
  const fallbackNode = document.getElementById('viewerFallback');
  renderPreview(target, viewerUri, buildViewerPayload(target, packetPage), previewNode, fallbackNode);
}

function renderPreview(target, viewerUri, viewerPayload, previewNode, fallbackNode) {
  if (viewerUri && Number(viewerPayload?.page || 0) > 0) {
    if (previewNode) previewNode.classList.remove('hidden');
    if (fallbackNode) fallbackNode.classList.add('hidden');
    setViewerPacket(viewerUri, viewerPayload);
    return;
  }
  if (!fallbackNode) return;

  if (String(target.viewer_mode || '') === 'explanation') {
    const hasOpenPacket = Boolean(document.getElementById('packetFrame')?.dataset.viewerUri);
    if (hasOpenPacket) {
      if (previewNode) previewNode.classList.remove('hidden');
      fallbackNode.classList.add('hidden');
      showPdfToast('这条规则没有对应的可定位原文页面。');
      return;
    }
    if (previewNode) previewNode.classList.add('hidden');
    setViewerPacket('', null);
    fallbackNode.textContent = '这条规则没有对应的可定位原文页面。';
    fallbackNode.classList.remove('hidden');
    return;
  }

  if (target.open_uri) {
    if (previewNode) previewNode.classList.add('hidden');
    setViewerPacket('', null);
    fallbackNode.textContent = '当前材料暂不可在右侧预览。';
    fallbackNode.classList.remove('hidden');
    return;
  }

  if (previewNode && document.getElementById('packetFrame')?.dataset.viewerUri) {
    previewNode.classList.remove('hidden');
    fallbackNode.classList.add('hidden');
    return;
  }

  if (previewNode) previewNode.classList.add('hidden');
  setViewerPacket('', null);
  fallbackNode.textContent = '当前证据没有可用预览资产。';
  fallbackNode.classList.remove('hidden');
}

function renderPdfPanel() {
  const project = projects.value[state.projectIndex];
  const viewer = ensurePdfShell();
  if (!project) {
    if (viewer) {
      viewer.innerHTML = '<div class="viewer-empty">无项目。</div>';
      delete viewer.dataset.initialized;
    }
    return;
  }

  const previewNode = document.getElementById('viewerPreview');
  const fallbackNode = document.getElementById('viewerFallback');
  const rule = getActiveRule(project);
  const packet = project.packet || {};

  if (!rule) {
    if (previewNode) previewNode.classList.add('hidden');
    if (fallbackNode) {
      fallbackNode.textContent = '选择一条规则后，在这里查看对应材料。';
      fallbackNode.classList.remove('hidden');
    }
    const viewerUri = resolveAssetUri(packet.viewer_file ? String(packet.viewer_file) : '');
    const defaultPage = Number(packet.default_page || 1);
    if (viewerUri && defaultPage > 0) {
      if (previewNode) previewNode.classList.remove('hidden');
      if (fallbackNode) fallbackNode.classList.add('hidden');
      setViewerPacket(viewerUri, {
        type: 'gotoPacketTarget',
        page: defaultPage,
        location_label: '项目材料',
        highlight_mode: 'none',
        highlight_text: '',
        highlight_rects: [],
      });
      return;
    }
    setViewerPacket('', null);
    return;
  }

  const targets = rule.evidence_targets || [];
  const activeIndex = Math.max(0, Math.min(state.evidenceIndex, targets.length - 1));
  const target = targets[activeIndex] || null;
  if (!target) {
    const viewerUri = resolveAssetUri(packet.viewer_file ? String(packet.viewer_file) : '');
    const defaultPage = Number(packet.default_page || 1);
    if (viewerUri && defaultPage > 0) {
      if (previewNode) previewNode.classList.remove('hidden');
      if (fallbackNode) fallbackNode.classList.add('hidden');
      setViewerPacket(viewerUri, {
        type: 'gotoPacketTarget',
        page: defaultPage,
        location_label: '项目材料',
        highlight_mode: 'none',
        highlight_text: '',
        highlight_rects: [],
      });
      showPdfToast('当前规则暂无可定位材料，已切到该项目材料首页。');
    } else {
      if (previewNode) previewNode.classList.add('hidden');
      if (fallbackNode) {
        fallbackNode.textContent = '当前规则暂无可定位材料。';
        fallbackNode.classList.remove('hidden');
      }
      setViewerPacket('', null);
    }
    return;
  }

  renderEvidenceTarget(target, project);
}

function renderAll() {
  renderProjectList();
  renderRulesPanel();
  renderPdfPanel();
}

watch(projects, async () => {
  initializeState();
  if (!loading.value && !errorText.value) {
    await nextTick();
    renderAll();
  }
});

watch(loading, async (isLoading) => {
  if (!isLoading && !errorText.value) {
    await nextTick();
    renderAll();
  }
});

onMounted(() => {
  loadDebugBatch();
});
</script>

<template>
  <div class="content-scroll">
    <div v-if="loading" class="page-loading">正在加载批次审查结果...</div>
    <div v-else-if="errorText" class="page-loading page-error">{{ errorText }}</div>

    <div v-else class="page">
      <section class="hero">
        <div class="hero-main">
          <h1>批次审查工作台</h1>
          <div class="hero-meta">
            <p>批次：<span class="mono">{{ batchLabel }}</span></p>
          </div>
        </div>
        <div class="hero-stats">
          <span class="badge status-failed">需关注 {{ attentionCount }}</span>
          <span class="badge status-passed">项目数 {{ projects.length }}</span>
        </div>
        <div class="batch-notes">
          <span class="batch-note">{{ batchNote }}</span>
        </div>
      </section>

      <section class="workspace">
        <aside class="sidebar">
          <div class="sidebar-head">
            <h2 class="sidebar-title">项目列表</h2>
          </div>
          <div class="project-list" id="projectList"></div>
        </aside>

        <main class="center-panel">
          <div id="pdfPanel"></div>
        </main>

        <aside class="viewer-panel">
          <div id="rulesPanel"></div>
        </aside>
      </section>
    </div>
  </div>
</template>

<style>
.content-scroll {
  --bg: #eef2f7;
  --card: #ffffff;
  --line: #d4dbe7;
  --line-strong: #b6c2d4;
  --text: #162033;
  --muted: #61708a;
  --accent: #0f766e;
  --accent-soft: #dff6f1;
  --passed: #067647;
  --failed: #b42318;
  --warning: #9a3412;
  --manual: #7c3aed;
  --na: #344054;
  --system: #2b6cb0;
  --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
}

.page-loading {
  display: grid;
  place-items: center;
  min-height: 60vh;
  color: var(--muted);
  font-size: 16px;
}

.page-error {
  color: var(--failed);
}

.page {
  width: min(1960px, 100%);
  height: calc(100vh - 56px);
  margin: 0 auto;
  padding: 24px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.1), transparent 26%),
    linear-gradient(180deg, #f7fafc 0%, var(--bg) 180px);
}

.hero,
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: var(--shadow);
}

.hero {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.hero h1 {
  margin: 0;
  font-size: 20px;
}

.hero p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.hero-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.hero-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.batch-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-note {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #f8fafc;
  color: var(--muted);
  font-size: 12px;
}

.workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1.9fr) minmax(320px, 0.95fr);
  gap: 18px;
  align-items: stretch;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.sidebar,
.center-panel,
.viewer-panel {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow);
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.sidebar {
  padding: 18px 14px;
}

.sidebar-head {
  padding: 0 8px 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 12px;
}

.sidebar-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
}

.project-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.project-item {
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fbfcfe;
  padding: 14px 12px;
  cursor: pointer;
  transition: 0.18s ease;
}

.project-item:hover {
  border-color: var(--line-strong);
  transform: translateY(-1px);
}

.project-item.active {
  border-color: var(--accent);
  background: linear-gradient(180deg, #ffffff 0%, #eefcf8 100%);
  box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.12);
}

.project-item-title {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.55;
  margin-bottom: 6px;
}

.project-item-meta {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.project-item-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.center-panel,
.viewer-panel {
  padding: 18px 18px 20px;
}

.panel-head {
  border-bottom: 1px solid var(--line);
  padding-bottom: 14px;
  margin-bottom: 16px;
}

.panel-head h2,
.panel-head h3 {
  margin: 0;
}

.project-summary {
  margin-top: 10px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
}

.badge {
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 11px;
  font-weight: 600;
  border: 0;
  background: #f1f5f9;
  white-space: nowrap;
}

.status-passed {
  color: var(--passed);
  background: #ecfdf3;
}

.status-failed {
  color: var(--failed);
  background: #fff1f2;
}

.status-warning,
.status-manual,
.status-requires_data {
  color: var(--manual);
  background: #f5f3ff;
}

.status-not_applicable,
.status-skipped {
  color: var(--na);
  background: #f2f4f7;
}

.status-system_managed {
  color: var(--system);
  background: #eff6ff;
}

.result-sections {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.result-section {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%);
  padding: 14px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-head-title {
  font-size: 15px;
  font-weight: 800;
}

.section-subgroups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.status-group-count {
  opacity: 0.85;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rule-card {
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #ffffff;
  padding: 14px;
  cursor: pointer;
  transition: 0.18s ease;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
}

.rule-card:hover {
  border-color: var(--line-strong);
}

.rule-card.active {
  border-color: var(--accent);
  background: linear-gradient(180deg, #ffffff 0%, #f0fdfa 100%);
  box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.14);
}

.rule-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}

.rule-card-title {
  font-size: 15px;
  font-weight: 800;
  line-height: 1.5;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.rule-card-requirement {
  color: var(--text);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.rule-card-meta {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 6px 10px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  min-width: 0;
}

.rule-card-meta-label {
  color: var(--muted);
}

.rule-card-meta > div {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.center-panel {
  padding: 18px 18px 16px;
  overflow: hidden;
}

.viewer-panel {
  padding: 18px 18px 20px;
}

#pdfPanel {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#rulesPanel {
  min-width: 0;
  max-width: 100%;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.viewer-empty {
  color: var(--muted);
  font-size: 14px;
  line-height: 1.8;
  padding: 24px 4px 8px;
}

.viewer-preview {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #f8fafc;
  min-height: 0;
  height: 100%;
  flex: 1 1 auto;
  overflow: hidden;
  display: flex;
  align-items: stretch;
  justify-content: center;
}

.viewer-preview iframe {
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.viewer-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  color: var(--muted);
  text-align: center;
  line-height: 1.8;
}

.pdf-only {
  display: flex;
  flex-direction: column;
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
}

.viewer-preview.hidden,
.viewer-fallback.hidden {
  display: none;
}

.packet-frame {
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.pdf-toast {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 4;
  max-width: min(520px, calc(100% - 48px));
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid rgba(15, 118, 110, 0.28);
  background: rgba(240, 253, 250, 0.96);
  color: #115e59;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14);
  font-size: 13px;
  line-height: 1.4;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.pdf-toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(4px);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.empty {
  color: var(--muted);
  font-size: 14px;
}

.folded-toggle {
  margin-top: 6px;
  border: 1px dashed var(--line);
  border-radius: 14px;
  background: #fbfcff;
}

.folded-toggle summary {
  cursor: pointer;
  padding: 12px 14px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
  list-style: none;
}

.folded-toggle summary::-webkit-details-marker {
  display: none;
}

.folded-body {
  padding: 0 12px 12px;
}

@media (max-width: 1320px) {
  .workspace {
    grid-template-columns: 240px minmax(0, 1.45fr) minmax(320px, 0.9fr);
  }
}

@media (max-width: 1080px) {
  .page {
    height: auto;
    overflow: visible;
  }

  .workspace {
    grid-template-columns: 1fr;
    height: auto;
    overflow: visible;
  }

  .sidebar,
  .center-panel,
  .viewer-panel {
    height: auto;
    min-height: auto;
    overflow: visible;
  }

  .project-list {
    flex: initial;
    min-height: auto;
    max-height: none;
    overflow: visible;
  }

  #rulesPanel {
    overflow: visible;
    min-height: auto;
  }

  #pdfPanel {
    height: auto;
    min-height: 480px;
    overflow: visible;
  }

  .pdf-only,
  .viewer-preview {
    height: auto;
    min-height: 480px;
  }
}

.evidence-locator {
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
  text-decoration-style: dashed;
  text-underline-offset: 2px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.evidence-locator:hover {
  opacity: 0.8;
}
</style>
