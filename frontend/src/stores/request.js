import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useRequestStore = defineStore('request', () => {
  const moduleBusyState = ref({});
  const clockMs = ref(Date.now());
  const API_BASE_STORAGE_KEY = 'tech_api_base';

  setInterval(() => {
    const anyBusy = Object.values(moduleBusyState.value).some((x) => x && x.inProgress);
    if (anyBusy) clockMs.value = Date.now();
  }, 1000);

  function savedApiBase() {
    const saved = localStorage.getItem(API_BASE_STORAGE_KEY);
    if (saved && saved.trim()) {
      return saved.trim().replace(/\/+$/, '');
    }
    return '';
  }

  function runtimeApiBase() {
    const envBase = String(import.meta.env.VITE_API_BASE || '').trim();
    if (envBase) {
      return envBase.replace(/\/+$/, '');
    }

    const { protocol, hostname, port } = window.location;
    const p = String(port || '').trim();

    // Dev server ports normally proxy to a backend on 8000.
    const devPorts = new Set(['5173', '5174', '4173', '3000']);
    const backendPort = !p ? '8000' : (devPorts.has(p) ? '8000' : p);
    return `${protocol}//${hostname}:${backendPort}/api/v1`;
  }

  function apiBase() {
    return savedApiBase() || runtimeApiBase();
  }

  function hasSavedApiBase() {
    return Boolean(savedApiBase());
  }

  function clearSavedApiBase() {
    localStorage.removeItem(API_BASE_STORAGE_KEY);
  }

  function resolveFallbackUrl(url) {
    const saved = savedApiBase();
    const runtime = runtimeApiBase();
    if (!saved || saved === runtime) return '';
    if (!String(url || '').startsWith(saved)) return '';
    return `${runtime}${String(url).slice(saved.length)}`;
  }

  async function parseResponse(response) {
    const text = await response.text();
    let data = text;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {}
    if (!response.ok) {
      throw new Error(typeof data === 'object' ? JSON.stringify(data) : text || `HTTP ${response.status}`);
    }
    return data;
  }

  function hasText(v) {
    return v !== undefined && v !== null && String(v).trim() !== '';
  }

  function toNumber(v, fallback = 0) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function splitCsv(text) {
    if (!hasText(text)) return undefined;
    return String(text).split(',').map((s) => s.trim()).filter(Boolean);
  }

  function parseJsonIfAny(text) {
    if (!hasText(text)) return undefined;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  function inProgressFor(moduleId) {
    return Boolean(moduleBusyState.value[moduleId]?.inProgress);
  }

  function progressTextFor(moduleId) {
    return moduleBusyState.value[moduleId]?.progressText || '';
  }

  function startedAtFor(moduleId) {
    return moduleBusyState.value[moduleId]?.requestStartedAt || 0;
  }

  function elapsedTextFor(moduleId) {
    if (!inProgressFor(moduleId)) return '0s';
    const startedAt = startedAtFor(moduleId);
    if (!startedAt) return '0s';
    const sec = Math.max(0, Math.floor((clockMs.value - startedAt) / 1000));
    return `${sec}s`;
  }

  function begin(moduleId, actionTitle) {
    const busy = moduleBusyState.value[moduleId];
    if (busy && busy.inProgress) {
      const staleMs = 3 * 60 * 1000;
      const startedAt = Number(busy.requestStartedAt || 0);
      if (startedAt > 0 && (Date.now() - startedAt) > staleMs) {
        moduleBusyState.value[moduleId] = {
          inProgress: false,
          requestStartedAt: 0,
          progressText: '',
        };
      } else {
        return false;
      }
    }
    moduleBusyState.value[moduleId] = {
      inProgress: true,
      requestStartedAt: Date.now(),
      progressText: `正在处理「${actionTitle}」`,
    };
    return true;
  }

  function end(moduleId) {
    moduleBusyState.value[moduleId] = {
      inProgress: false,
      requestStartedAt: 0,
      progressText: '',
    };
  }

  function attachController(moduleId, controller) {
    moduleBusyState.value[moduleId] = {
      ...(moduleBusyState.value[moduleId] || {}),
      controller,
    };
  }

  function stop(moduleId) {
    const busy = moduleBusyState.value[moduleId];
    if (busy && busy.inProgress && busy.controller) {
      try {
        busy.controller.abort('manual-cancel');
      } catch {}
      moduleBusyState.value[moduleId] = {
        inProgress: false,
        requestStartedAt: 0,
        progressText: '',
      };
      return true;
    }
    return false;
  }

  async function fetchWithTimeout(url, options = {}, timeout = 60000, externalController = null) {
    const controller = externalController || new AbortController();
    const id = setTimeout(() => {
      try { controller.abort(); } catch {}
    }, timeout);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      return await parseResponse(response);
    } catch (error) {
      if (error && error.name === 'AbortError') {
        const reason = controller?.signal?.reason;
        if (reason && String(reason).toLowerCase().includes('manual')) {
          throw new Error('请求已停止');
        }
        const seconds = Math.round(timeout / 1000);
        throw new Error(`请求超时（${seconds}秒）。后端可能仍在处理中，请稍后重试或使用“查询”类接口查看状态。`);
      }

      const fallbackUrl = resolveFallbackUrl(url);
      if (fallbackUrl) {
        try {
          localStorage.removeItem(API_BASE_STORAGE_KEY);
          const fallbackResponse = await fetch(fallbackUrl, { ...options, signal: controller.signal });
          return await parseResponse(fallbackResponse);
        } catch {}
      }

      throw error;
    } finally {
      clearTimeout(id);
    }
  }

  return {
    apiBase,
    hasSavedApiBase,
    clearSavedApiBase,
    hasText,
    toNumber,
    splitCsv,
    parseJsonIfAny,
    moduleBusyState,
    inProgressFor,
    progressTextFor,
    startedAtFor,
    elapsedTextFor,
    begin,
    end,
    attachController,
    stop,
    fetchWithTimeout,
  };
});
