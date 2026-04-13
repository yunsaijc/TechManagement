import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useUiStore = defineStore('ui', () => {
  const moduleTabState = ref({});
  const sidebarVisible = ref(true);
  const toastMessage = ref('');
  const toastVisible = ref(false);

  function setTab(moduleId, tab) {
    if (!moduleId) return;
    moduleTabState.value[moduleId] = tab === 'result' ? 'result' : 'form';
  }

  function getTab(moduleId) {
    return moduleId && moduleTabState.value[moduleId] === 'result' ? 'result' : 'form';
  }

  function toast(message, _type = 'info', timeout = 2200) {
    toastMessage.value = message;
    toastVisible.value = true;
    setTimeout(() => {
      toastVisible.value = false;
    }, timeout);
  }

  function setSidebarVisible(v) {
    sidebarVisible.value = Boolean(v);
    localStorage.setItem('tech_sidebar_visible', sidebarVisible.value ? '1' : '0');
  }

  function initSidebar() {
    const saved = localStorage.getItem('tech_sidebar_visible');
    if (saved !== null) {
      sidebarVisible.value = saved === '1';
    }
  }

  return {
    moduleTabState,
    sidebarVisible,
    toastMessage,
    toastVisible,
    setTab,
    getTab,
    setSidebarVisible,
    initSidebar,
    toast,
  };
});
