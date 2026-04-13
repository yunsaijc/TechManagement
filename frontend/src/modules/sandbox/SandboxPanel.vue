<script setup>
import { onMounted } from 'vue';
import ResultDisplay from '../../components/ResultDisplay.vue';
import SandboxLeadershipView from './SandboxLeadershipView.vue';
import { useSandboxStore } from '../../stores/sandbox';

const store = useSandboxStore();

onMounted(() => {
  store.initialize();
});
</script>

<template>
  <div class="content-scroll">
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

    <div v-if="store.activeTab === 'form'" class="workbench-tab-panel">
      <section class="panel-shell panel-shell-stretch sandbox-shell">
        

        <div class="sandbox-scenarios">
          <button
            v-for="scenario in store.leadershipScenarios"
            :key="scenario.id"
            class="sandbox-scenario-btn"
            :class="{ active: store.selectedScenarioId === scenario.id }"
            :disabled="store.requestInProgress"
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
            :disabled="store.requestInProgress"
            placeholder="例如：最近两年固态电池申报激增但转化偏低，明年指南如何调整？"
          />

          <div class="sandbox-controls-grid">
            <div class="sandbox-mode-row">
              <label class="sandbox-mode-label" for="forecast-mode">推演模式</label>
              <select id="forecast-mode" v-model="store.forecastMode" class="sandbox-mode-select" :disabled="store.requestInProgress">
                <option v-for="mode in store.forecastModes" :key="mode.value" :value="mode.value">
                  {{ mode.label }}
                </option>
              </select>
            </div>

            <label class="sandbox-preflight-toggle sandbox-force-refresh">
              <input v-model="store.forecastForceRefresh" type="checkbox" :disabled="store.requestInProgress" />
              强制刷新（不复用缓存）
            </label>
          </div>

          <div class="sandbox-footer-row">
            <div class="sandbox-mode-desc">
              {{ (store.forecastModes.find((x) => x.value === store.forecastMode) || {}).description || '' }}
            </div>

            <button
              class="sandbox-primary-btn"
              :disabled="store.requestInProgress"
              @click="store.runLeadershipForecast"
            >
              {{ store.requestInProgress ? '推演生成中...' : '开始推演' }}
            </button>
          </div>
        </div>
      </section>
    </div>

    <div v-else class="workbench-tab-panel">
      <section class="panel-shell panel-shell-stretch">
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
  padding-top: 6px;
}

.sandbox-shell {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  padding: 16px;
  background: #f8fbff;
  max-width: 1280px;
  margin: 0 auto;
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
