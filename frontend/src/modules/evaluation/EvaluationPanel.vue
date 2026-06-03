<script setup>
import { computed, ref } from 'vue';

const projects = [
  {
    html: 'EVAL_ffb75a4c639d4ebab2c33e21d75d7bac.html',
    packet: 'projects/ffb75a4c639d4ebab2c33e21d75d7bac/packet_viewer.html',
    title: '生殖健康科普示范基地标准化建设与创新模式探索',
    score: '6.5 / C',
  },
  {
    html: 'EVAL_c0a6828463cb4c1985c7fca26d5328d3.html',
    packet: 'projects/c0a6828463cb4c1985c7fca26d5328d3/packet_viewer.html',
    title: '低空多源感知一体化病害检测和灾害监测装备研发与应用示范',
    score: '7.01 / C',
  },
  {
    html: 'EVAL_8170da049eae4caf88322ef03f410310.html',
    packet: 'projects/8170da049eae4caf88322ef03f410310/packet_viewer.html',
    title: '智能与数字化技术在骨科领域的应用及临床研究',
    score: '7.04 / C',
  },
];

const packetFrameEl = ref(null);
const resultFrameEl = ref(null);
const activeProject = ref(projects[0]);

const workspaceTitle = computed(() => activeProject.value?.title || '');
const workspaceScore = computed(() => activeProject.value?.score || '');
const packetSrc = computed(() => (
  activeProject.value?.packet ? `/debug-eval/${activeProject.value.packet}` : ''
));
const resultSrc = computed(() => `/debug-eval/${activeProject.value?.html || ''}`);

function selectProject(project) {
  activeProject.value = project;
}

function postPacketJump({ page, file, highlightText, rects }) {
  const packetFrame = packetFrameEl.value;
  const pageNumber = Number(page || 0);
  if (!packetFrame?.contentWindow || !pageNumber) return;

  const payload = {
    type: 'gotoPacketTarget',
    page: pageNumber,
    location_label: String(file || '统一材料'),
    highlight_text: String(highlightText || ''),
    highlight_rects: Array.isArray(rects) ? rects : [],
  };

  const send = () => {
    try {
      packetFrame.contentWindow?.postMessage(payload, '*');
    } catch (error) {
      console.warn('packet viewer postMessage failed', error);
    }
  };

  window.setTimeout(send, 0);
  window.setTimeout(send, 120);
  window.setTimeout(send, 320);
}

function resetResultPanelViewport(doc, targetId = '') {
  const resultPanels = doc.querySelector('.result-panels');
  if (!resultPanels) return;

  const applyReset = () => {
    const activePanel = targetId
      ? doc.getElementById(targetId)
      : resultPanels.querySelector('.result-panel.is-active');

    resultPanels.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    resultPanels.scrollTop = 0;
    resultPanels.scrollLeft = 0;
    doc.documentElement.scrollTop = 0;
    doc.body.scrollTop = 0;

    if (activePanel) {
      activePanel.scrollTop = 0;
      activePanel.scrollLeft = 0;
    }
  };

  applyReset();
  window.requestAnimationFrame(applyReset);
  window.setTimeout(applyReset, 60);
  window.setTimeout(applyReset, 180);
}

function bindResultInteractions(doc) {
  const body = doc.body;
  if (!body || body.dataset.jumpBridgeBound === 'true') return;

  body.dataset.jumpBridgeBound = 'true';

  const forceActivateTabPanel = (tabTarget = '') => {
    const targetId = String(tabTarget || '').trim();
    if (!targetId) return;

    const tabs = Array.from(doc.querySelectorAll('.result-tab'));
    const panels = Array.from(doc.querySelectorAll('.result-panel'));
    if (!tabs.length || !panels.length) return;

    tabs.forEach((node) => {
      const isTarget = String(node?.dataset?.tabTarget || '') === targetId;
      node.classList.toggle('is-active', isTarget);
    });
    panels.forEach((node) => {
      const isTarget = String(node?.id || '') === targetId;
      node.classList.toggle('is-active', isTarget);
      if (!isTarget) {
        node.scrollTop = 0;
      }
    });
  };

  doc.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-doc-jump]');
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();

      let rects = [];
      try {
        rects = JSON.parse(trigger.dataset.highlightRects || '[]');
      } catch (error) {
        rects = [];
      }

      postPacketJump({
        page: Number(trigger.dataset.packetPage || trigger.dataset.page || 0),
        file: trigger.dataset.file || '',
        highlightText: trigger.dataset.highlightText || '',
        rects,
      });
      return;
    }

    const tab = event.target.closest('.result-tab');
    const tabTarget = tab?.dataset?.tabTarget || '';
    if (tabTarget) {
      // 某些历史报告模板的 tab 脚本不稳定，这里统一兜底确保切换到正确面板。
      window.setTimeout(() => forceActivateTabPanel(tabTarget), 0);
      window.setTimeout(() => forceActivateTabPanel(tabTarget), 120);
    }
    if (tabTarget === 'report-dimensions') {
      window.setTimeout(() => resetResultPanelViewport(doc, tabTarget), 0);
      window.setTimeout(() => resetResultPanelViewport(doc, tabTarget), 120);
    }
  }, true);
}

function syncResultLayout() {
  const frame = resultFrameEl.value;
  if (!frame) return;

  try {
    const doc = frame.contentDocument;
    if (!doc) return;
    const styleId = 'embedded-result-only-override';
    let style = doc.getElementById(styleId);
    if (!style) {
      style = doc.createElement('style');
      style.id = styleId;
      doc.head.appendChild(style);
    }

    style.textContent = `
      html, body {
        height: 100% !important;
        overflow: hidden !important;
        background: #f0f2f5 !important;
      }
      body {
        margin: 0 !important;
      }
      .page {
        height: 100% !important;
        min-height: 0 !important;
        overflow: hidden !important;
        padding: 0 !important;
        background: transparent !important;
      }
      .page-stack {
        display: grid !important;
        grid-template-rows: minmax(0, 1fr) !important;
        height: 100% !important;
        min-height: 0 !important;
        gap: 0 !important;
      }
      .hero,
      .project-stack,
      .main-stack {
        display: none !important;
      }
      .content-grid,
      .workspace-layout {
        display: grid !important;
        grid-template-columns: minmax(0, 1fr) !important;
        gap: 0 !important;
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
      }
      .side-stack {
        display: grid !important;
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        padding-right: 0 !important;
        overflow: hidden !important;
      }
      .result-shell {
        display: grid !important;
        grid-template-rows: auto minmax(0, 1fr) !important;
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        margin: 0 !important;
        overflow: hidden !important;
      }
      .workspace-head {
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 10px !important;
      }
      .result-panels {
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        overflow: auto !important;
      }
      .result-tabs {
        display: flex !important;
        flex-wrap: wrap !important;
        justify-content: flex-start !important;
        align-items: center !important;
        width: 100% !important;
        overflow: visible !important;
        gap: 10px !important;
        max-height: none !important;
      }
      .result-tab {
        min-width: 110px !important;
        width: auto !important;
        white-space: nowrap !important;
        word-break: keep-all !important;
        font-size: 16px !important;
        padding-inline: 14px !important;
        flex: 0 0 auto !important;
      }
      .result-panel {
        width: 100% !important;
      }
      .result-panel.is-active {
        display: grid !important;
        width: 100% !important;
      }
      .doc-toast {
        display: none !important;
      }
    `;

    bindResultInteractions(doc);
    resetResultPanelViewport(doc);
  } catch (error) {
    console.warn('failed to sync embedded evaluation layout', error);
  }
}
</script>

<template>
  <div class="workspace-shell">
    <aside class="project-rail">
      <div class="project-rail-head">
        <!-- <h1>项目评审工作台</h1> -->
      </div>

      <div class="project-list">
        <button
          v-for="project in projects"
          :key="project.html"
          type="button"
          class="project-item"
          :class="{ 'is-active': activeProject.html === project.html }"
          @click="selectProject(project)"
        >
          <div class="project-item-top">
            <div class="project-item-title">{{ project.title }}</div>
            <div class="project-item-score">{{ project.score }}</div>
          </div>
        </button>
      </div>
    </aside>

    <header class="workspace-head">
      <div class="workspace-title">{{ workspaceTitle }}</div>
      <div class="workspace-score">{{ workspaceScore }}</div>
    </header>

    <section class="document-panel">
      <iframe
        v-if="packetSrc"
        ref="packetFrameEl"
        class="workspace-frame document-frame"
        :src="packetSrc"
        title="项目正文材料"
      />
      <div v-else class="document-empty">
        当前项目暂无 PDF 预览
      </div>
    </section>

    <section class="feature-panel">
      <iframe
        ref="resultFrameEl"
        class="workspace-frame result-frame"
        :src="resultSrc"
        title="项目评审功能区"
        @load="syncResultLayout"
      />
    </section>
  </div>
</template>

<style scoped>
* {
  box-sizing: border-box;
  min-width: 0;
}

:global(html),
:global(body) {
  height: 100%;
}

.workspace-shell {
  flex: 1;
  width: 100%;
  height: auto;
  min-height: calc(100vh + 180px);
  min-width: 0;
  overflow: visible;
  display: grid;
  grid-template-columns: 136px minmax(0, 1.52fr) minmax(420px, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px 10px;
  padding: 8px 10px 10px 0;
  font-family: "Source Han Sans SC", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  background: #f0f2f5;
  color: #1b2430;
}

.project-rail {
  grid-row: 1 / span 2;
  border-right: 1px solid #d7dfe8;
  background: #e8ebf0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
}

.project-rail-head {
  padding: 18px 10px 12px;
  border-bottom: 1px solid #e6edf4;
}

.project-rail-head h1 {
  margin: 0;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.35;
}

.project-list {
  min-height: 0;
  overflow: auto;
  padding: 8px 6px 10px 5px;
  display: grid;
  gap: 9px;
  align-content: start;
}

.project-item {
  width: 100%;
  border: 1px solid #d7dfe8;
  border-radius: 11px;
  background: #ffffff;
  text-align: left;
  padding: 8px 7px;
  cursor: pointer;
  display: grid;
  gap: 0;
  box-shadow: 0 4px 12px rgba(18, 31, 53, 0.035);
}

.project-item:hover,
.project-item.is-active {
  border-color: #9eb6cf;
  background: #eef4f9;
}

.project-item-top {
  display: grid;
  gap: 8px;
}

.project-item-title {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
}

.project-item-score {
  justify-self: end;
  color: #1d3c61;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid #c8d6e5;
  border-radius: 999px;
  padding: 2px 6px;
  background: #f5f8fb;
}

.workspace-head {
  grid-column: 2 / 4;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 6px 4px 2px;
  background: transparent;
}

.workspace-title {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.45;
}

.workspace-score {
  flex-shrink: 0;
  color: #1d3c61;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid #c8d6e5;
  border-radius: 999px;
  padding: 4px 8px;
  background: #f5f8fb;
}

.document-panel,
.feature-panel {
  min-height: clamp(860px, 96vh, 1180px);
  overflow: hidden;
  border: 1px solid #d7dfe8;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(18, 31, 53, 0.05);
}

.document-panel {
  grid-column: 2;
}

.feature-panel {
  grid-column: 3;
}

.workspace-frame {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: block;
  border: 0;
  background: #eef2f6;
}

.document-frame {
  background: #dfe5ec;
}

.result-frame {
  background: #f0f2f5;
}

.document-empty {
  height: 100%;
  min-height: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  color: #66758a;
  font-size: 14px;
  background: #f7f9fb;
}

@media (max-width: 1200px) {
  .workspace-shell {
    grid-template-columns: 136px minmax(0, 1fr);
    grid-template-rows: auto minmax(720px, 1fr) minmax(860px, 1fr);
  }

  .workspace-head {
    grid-column: 2;
  }

  .document-panel {
    grid-column: 2;
  }

  .feature-panel {
    grid-column: 2;
  }
}

@media (max-width: 1024px) {
  .workspace-shell {
    height: auto;
    min-height: calc(100vh + 220px);
    grid-template-columns: 1fr;
    grid-template-rows: auto auto minmax(58vh, auto) minmax(78vh, auto);
    padding-left: 0;
  }

  .project-rail {
    grid-row: auto;
    border-right: 0;
    border-bottom: 1px solid #d7dfe8;
  }

  .workspace-head,
  .document-panel,
  .feature-panel {
    grid-column: 1;
  }

  .workspace-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
