import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { MODULES, HISTORY_MODULE } from '../config/modules';
import { useHistoryStore } from './history';
import { useRequestStore } from './request';
import { useUiStore } from './ui';

export const useWorkbenchStore = defineStore('workbench', () => {
  const req = useRequestStore();
  const hist = useHistoryStore();
  const ui = useUiStore();

  const modules = MODULES;
  const selectedModuleId = ref('review');

  const currentTime = ref('--:--:--');
  const backendStatus = ref('检测中');
  const backendOk = ref(false);

  const navModules = computed(() => [...modules, HISTORY_MODULE]);
  const isHistoryModule = computed(() => selectedModuleId.value === HISTORY_MODULE.id);
  const activeModule = computed(() => modules.find((m) => m.id === selectedModuleId.value) || null);
  const currentModuleMeta = computed(() => (isHistoryModule.value ? HISTORY_MODULE : activeModule.value));

  function selectModule(moduleId) {
    selectedModuleId.value = moduleId;
  }

  function tickClock() {
    currentTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  }

  async function checkBackend() {
    try {
      const base = req.apiBase();
      const sandboxUrl = `${base}/sandbox/health`;
      const evalUrl = `${base}/evaluation/health`;
      try {
        await req.fetchWithTimeout(sandboxUrl, { method: 'GET' }, 5000);
      } catch {
        await req.fetchWithTimeout(evalUrl, { method: 'GET' }, 5000);
      }
      backendOk.value = true;
      backendStatus.value = `已连接 (${base})`;
    } catch {
      backendOk.value = false;
      backendStatus.value = `未连接 (${req.apiBase()})`;
    }
  }

  function bootstrap() {
    hist.load();
    ui.initSidebar();
    tickClock();
    checkBackend();
  }

  return {
    modules,
    navModules,
    selectedModuleId,
    currentTime,
    backendStatus,
    backendOk,
    isHistoryModule,
    activeModule,
    currentModuleMeta,
    bootstrap,
    tickClock,
    checkBackend,
    selectModule,
  };
});

