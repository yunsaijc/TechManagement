import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useHistoryStore = defineStore('history', () => {
  const requestHistory = ref([]);

  function record(entry) {
    requestHistory.value.unshift({ ...entry, time: new Date().toLocaleString('zh-CN') });
    requestHistory.value = requestHistory.value.slice(0, 30);
    localStorage.setItem('tech_history', JSON.stringify(requestHistory.value));
  }

  function load() {
    try {
      const raw = localStorage.getItem('tech_history');
      requestHistory.value = raw ? JSON.parse(raw) : [];
    } catch {
      requestHistory.value = [];
    }
  }

  function clear() {
    requestHistory.value = [];
    localStorage.setItem('tech_history', JSON.stringify(requestHistory.value));
  }

  return { requestHistory, record, load, clear };
});
