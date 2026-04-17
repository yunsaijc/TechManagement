<script setup>
import { computed, onMounted, ref } from 'vue';
import ResultDisplay from '../../components/ResultDisplay.vue';
import SandboxLeadershipView from './SandboxLeadershipView.vue';
import { forecastStepLabel } from './forecastProgressLabels.js';
import { useSandboxStore } from '../../stores/sandbox';

const store = useSandboxStore();
const exportingLocal = ref(false);
const canExportLocal = computed(() => Boolean(store.lastResult || store.resultText));

onMounted(() => {
  store.initialize();
});

function collectInlineStyles() {
  const chunks = [];
  for (const sheet of Array.from(document.styleSheets || [])) {
    try {
      const rules = Array.from(sheet.cssRules || []);
      if (!rules.length) continue;
      chunks.push(rules.map((rule) => rule.cssText).join('\n'));
    } catch {
      // Ignore cross-origin stylesheets that block cssRules.
    }
  }
  return chunks.join('\n');
}

function replaceCanvasWithImages(sourceRoot, clonedRoot) {
  const sourceCanvases = sourceRoot.querySelectorAll('canvas');
  const clonedCanvases = clonedRoot.querySelectorAll('canvas');
  const total = Math.min(sourceCanvases.length, clonedCanvases.length);
  for (let i = 0; i < total; i += 1) {
    const sourceCanvas = sourceCanvases[i];
    const clonedCanvas = clonedCanvases[i];
    if (!sourceCanvas || !clonedCanvas) continue;
    let dataUrl = '';
    try {
      dataUrl = sourceCanvas.toDataURL('image/png');
    } catch {
      dataUrl = '';
    }
    if (!dataUrl) continue;
    const img = document.createElement('img');
    img.src = dataUrl;
    img.alt = 'chart';
    img.style.display = 'block';
    img.style.width = `${sourceCanvas.width || sourceCanvas.clientWidth || 0}px`;
    img.style.maxWidth = '100%';
    img.style.height = 'auto';
    clonedCanvas.replaceWith(img);
  }
}

function downloadHtml(content, filename) {
  const blob = new Blob([content], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function buildExportFilename() {
  const now = new Date();
  const pad = (x) => String(x).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `policy-sandbox-result-${stamp}.html`;
}

function saveResultToLocal() {
  if (exportingLocal.value || !canExportLocal.value) return;
  const sourceRoot = document.querySelector('.sandbox-result-shell');
  if (!sourceRoot) return;
  exportingLocal.value = true;
  try {
    const clonedRoot = sourceRoot.cloneNode(true);
    replaceCanvasWithImages(sourceRoot, clonedRoot);
    const styleText = collectInlineStyles();
    const title = `政策沙盘结果导出 - ${new Date().toLocaleString('zh-CN')}`;
    const htmlDoc = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${title}</title>
  <style>${styleText}</style>
</head>
<body>
  ${clonedRoot.outerHTML}
</body>
</html>`;
    downloadHtml(htmlDoc, buildExportFilename());
  } finally {
    exportingLocal.value = false;
  }
}
</script>

<template>
  <div class="content-scroll">
    <div class="sandbox-panel-head">
      <div class="workbench-tab-bar">
        <button
          class="workbench-tab-btn"
          :class="{ active: store.activeTab === 'form' }"
          @click="store.setActiveTab('form')"
        >功能操作</button>
        <button
          class="workbench-tab-btn"
          :class="{ active: store.activeTab === 'result' }"
          @click="store.setActiveTab('result')"
        >结果展示</button>
      </div>

      <div
        v-if="store.forecastJobRunning"
        class="sandbox-job-banner"
        role="status"
        aria-live="polite"
      >
        <div class="sandbox-job-banner-row">
          <span class="sandbox-job-title">沙盘推演进行中</span>
          <span class="sandbox-job-pct">{{ store.forecastJobProgress }}%</span>
        </div>
        <div class="sandbox-progress-track" aria-hidden="true">
          <div class="sandbox-progress-fill" :style="{ width: `${Math.min(100, Math.max(0, store.forecastJobProgress))}%` }" />
        </div>
        <div class="sandbox-job-meta">
          <span class="sandbox-job-step">{{ forecastStepLabel(store.forecastJobStep) }}</span>
          <span v-if="store.forecastJobMessage" class="sandbox-job-msg"> — {{ store.forecastJobMessage }}</span>
        </div>
        <div class="sandbox-job-eta">{{ store.forecastEtaHint }} · 进度约每 1.5 秒刷新</div>
      </div>
    </div>

    <div v-if="store.activeTab === 'form'" class="workbench-tab-panel">
      <section class="panel-shell panel-shell-stretch sandbox-shell">
        

        <div class="sandbox-scenarios">
          <button
            v-for="scenario in store.leadershipScenarios"
            :key="scenario.id"
            class="sandbox-scenario-btn"
            :class="{ active: store.selectedScenarioId === scenario.id }"
            :disabled="store.requestInProgress || store.forecastJobRunning"
            @click="store.setScenario(scenario.id)"
          >
            <span class="sandbox-scenario-title">{{ scenario.title }}</span>
            <span class="sandbox-scenario-desc">{{ scenario.description }}</span>
          </button>
        </div>

        <div class="sandbox-forecast-box">
          <div class="sandbox-forecast-title">推演问题</div>
          <textarea
            v-model="store.forecastQuestion"
            class="sandbox-forecast-input"
            :disabled="store.requestInProgress || store.forecastJobRunning"
            placeholder="例如：最近两年固态电池申报激增但转化偏低，明年指南如何调整？"
          />

          <div class="sandbox-controls-grid">
            <div class="sandbox-mode-row">
              <label class="sandbox-mode-label" for="forecast-mode">推演模式</label>
              <select id="forecast-mode" v-model="store.forecastMode" class="sandbox-mode-select" :disabled="store.requestInProgress || store.forecastJobRunning">
                <option v-for="mode in store.forecastModes" :key="mode.value" :value="mode.value">
                  {{ mode.label }}
                </option>
              </select>
            </div>

            <label class="sandbox-preflight-toggle sandbox-force-refresh">
              <input v-model="store.forecastForceRefresh" type="checkbox" :disabled="store.requestInProgress || store.forecastJobRunning" />
              强制刷新（不复用缓存）
            </label>
          </div>
          <div class="sandbox-eta-hint">{{ store.forecastEtaHint }}</div>

          <div class="sandbox-footer-row">
            <div class="sandbox-mode-desc">
              {{ (store.forecastModes.find((x) => x.value === store.forecastMode) || {}).description || '' }}
            </div>

            <button
              class="sandbox-primary-btn"
              :disabled="store.requestInProgress || store.forecastJobRunning"
              @click="store.runLeadershipForecast"
            >
              {{ store.forecastJobRunning ? `推演执行中 ${store.forecastJobProgress}%` : (store.requestInProgress ? '任务提交中...' : '开始推演') }}
            </button>
          </div>
        </div>
      </section>
    </div>

    <div v-else class="workbench-tab-panel">
      <div class="sandbox-result-toolbar">
        <button
          class="sandbox-secondary-btn"
          :disabled="!canExportLocal || exportingLocal"
          @click="saveResultToLocal"
        >
          {{ exportingLocal ? '保存中...' : '保存到本地 HTML' }}
        </button>
      </div>
      <section class="panel-shell panel-shell-stretch sandbox-result-shell">
        <SandboxLeadershipView
          v-if="store.lastResult"
          :report="store.lastResult"
          :request-meta="store.requestMeta"
        />
        <ResultDisplay
          v-else-if="store.resultText"
          :request-meta="store.requestMeta"
          :summary-items="store.summaryItems"
          :is-markdown-report-payload="store.isMarkdownReportPayload"
          :last-result="store.lastResult"
          :result-cards="store.resultCards"
          :result-text="store.resultText"
          :module-id="store.moduleId"
          :action-id="store.latestActionId"
        />
        <div v-else class="result-empty-state">
          <div class="result-empty-title">暂无结果</div>
          <div class="result-empty-desc">在“功能操作”中点击“开始生成推演结论”。</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.content-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 6px 4px 12px;
}

/* 与全局 .workbench-tab-bar 的 sticky 解耦：整块顶栏一起吸附，避免「标签一条 + 进度一条」叠在视口顶部 */
.sandbox-panel-head {
  position: sticky;
  top: 0;
  z-index: 40;
  flex-shrink: 0;
  padding-bottom: 4px;
  margin-bottom: 2px;
  background: linear-gradient(180deg, #f4f7fb 0%, #eef2f7 55%, transparent 100%);
}

.sandbox-panel-head :deep(.workbench-tab-bar) {
  position: relative;
  top: auto;
  z-index: auto;
}

.content-scroll > .workbench-tab-panel {
  flex: 1;
  min-height: 0;
}

.sandbox-job-banner {
  max-width: 1280px;
  margin: 8px auto 0;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid #bfdbfe;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}

.sandbox-job-banner-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.sandbox-job-title {
  font-weight: 750;
  font-size: 14px;
  color: #0f172a;
}

.sandbox-job-pct {
  font-variant-numeric: tabular-nums;
  font-weight: 800;
  font-size: 15px;
  color: #1d4ed8;
}

.sandbox-progress-track {
  margin-top: 8px;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.sandbox-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  transition: width 0.35s ease;
}

.sandbox-job-meta {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: #334155;
}

.sandbox-job-step {
  font-weight: 650;
  color: #0f172a;
}

.sandbox-job-msg {
  color: #475569;
}

.sandbox-job-eta {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}

.sandbox-eta-hint {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.sandbox-shell {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  padding: 16px;
  background: #f8fbff;
  max-width: 1280px;
  margin: 0 auto;
}

.sandbox-result-shell {
  padding: 10px 10px 14px;
  background: #f8fafc;
  border-color: #dbe5f0;
}

.sandbox-result-toolbar {
  max-width: 1280px;
  margin: 0 auto 8px;
  display: flex;
  justify-content: flex-end;
}

.sandbox-secondary-btn {
  border: 1px solid #c9d8ea;
  border-radius: 10px;
  background: #ffffff;
  color: #1e3a8a;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 14px;
  cursor: pointer;
}

.sandbox-secondary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.sandbox-headline {
  padding: 2px 2px 10px;
}

.sandbox-title {
  margin: 0;
  font-size: 22px;
  line-height: 1.2;
  font-weight: 800;
  letter-spacing: 0.01em;
  color: #0f172a;
  font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.sandbox-desc {
  margin: 8px 0 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.6;
}

.sandbox-scenarios {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.sandbox-scenario-btn {
  border: 1px solid #d3dce8;
  border-radius: 12px;
  background: #ffffff;
  padding: 14px;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  min-height: 88px;
}

.sandbox-scenario-btn.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.14) inset;
}

.sandbox-scenario-btn:hover {
  border-color: #93c5fd;
}

.sandbox-scenario-title {
  display: block;
  font-weight: 750;
  color: #0f172a;
  font-size: 17px;
  line-height: 1.3;
}

.sandbox-scenario-desc {
  display: block;
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: #475569;
}

.sandbox-forecast-box {
  margin-top: 14px;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid #d6e2f1;
  background: #ffffff;
}

.sandbox-forecast-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.sandbox-forecast-input {
  margin-top: 8px;
  width: 100%;
  min-height: 96px;
  resize: vertical;
  border: 1px solid #c9d8ea;
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.5;
  color: #0f172a;
  background: #ffffff;
}

.sandbox-forecast-input:focus {
  outline: none;
  border-color: #60a5fa;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.sandbox-controls-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.sandbox-preflight-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #1e293b;
}

.sandbox-force-refresh {
  justify-self: end;
  white-space: nowrap;
}

.sandbox-primary-btn {
  width: auto;
  min-width: 180px;
  border: none;
  border-radius: 10px;
  padding: 10px 20px;
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 55%, #3b82f6 100%);
  color: #ffffff;
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 0.01em;
  cursor: pointer;
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.24);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.sandbox-primary-btn:hover:not(:disabled) {
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.3);
}

.sandbox-primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.sandbox-mode-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sandbox-mode-label {
  font-size: 13px;
  color: #1e293b;
  font-weight: 600;
}

.sandbox-mode-select {
  min-width: 280px;
  border: 1px solid #c9d8ea;
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 14px;
  color: #0f172a;
  background: #ffffff;
}

.sandbox-mode-desc {
  margin-top: 0;
  font-size: 13px;
  color: #64748b;
}

.sandbox-footer-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

@media (max-width: 960px) {
  .sandbox-title {
    font-size: 18px;
  }

  .sandbox-scenario-title {
    font-size: 16px;
  }

  .sandbox-controls-grid {
    grid-template-columns: 1fr;
    align-items: start;
  }

  .sandbox-mode-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .sandbox-force-refresh {
    justify-self: start;
  }

  .sandbox-mode-select {
    width: 100%;
    min-width: 0;
  }

  .sandbox-footer-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .sandbox-primary-btn {
    font-size: 15px;
    width: 100%;
    min-width: 0;
  }
}
</style>
