<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useWorkbenchStore } from './stores/workbench';
import { useRequestStore } from './stores/request';
import { useUiStore } from './stores/ui';
import AppHeader from './components/AppHeader.vue';
import ModuleNav from './components/ModuleNav.vue';
import ToastNotice from './components/ToastNotice.vue';
import RequestHud from './components/RequestHud.vue';

const store = useWorkbenchStore();
const req = useRequestStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

const sidebarVisible = computed(() => ui.sidebarVisible);

const activeNavId = computed(() => (route.name === 'history' ? 'history' : store.selectedModuleId));
const requestInProgress = computed(() => (
  route.name !== 'history' && req.inProgressFor(store.selectedModuleId)
));
const requestTitle = computed(() => req.progressTextFor(store.selectedModuleId));

let clockTimer = null;
let backendTimer = null;

function onSelectModule(moduleId) {
  if (moduleId === 'history') {
    router.push({ name: 'history' });
    return;
  }
  if (route.name !== 'workbench') {
    router.push({ name: 'workbench' });
  }
  store.selectModule(moduleId);
}

function toggleSidebar() {
  ui.setSidebarVisible(!ui.sidebarVisible);
}

onMounted(() => {
  store.bootstrap();
  clockTimer = setInterval(() => {
    store.tickClock();
  }, 1000);
  backendTimer = setInterval(() => {
    store.checkBackend();
  }, 10000);
});

onBeforeUnmount(() => {
  if (clockTimer) {
    clearInterval(clockTimer);
  }
  if (backendTimer) {
    clearInterval(backendTimer);
  }
});
</script>

<template>
  <div class="app">
    <AppHeader
      :backend-ok="store.backendOk"
      :backend-status="store.backendStatus"
      :current-time="store.currentTime"
      :sidebar-visible="sidebarVisible"
      @toggle-sidebar="toggleSidebar"
    />

    <div class="app-body">
      <div class="app-sidebar-wrapper" :class="{ collapsed: !sidebarVisible }">
        <ModuleNav
          :modules="store.navModules"
          :active-id="activeNavId"
          @select="onSelectModule"
        />
      </div>

      <div class="app-content-wrapper">
        <RouterView />
      </div>
    </div>

    <ToastNotice
      v-if="ui.toastVisible"
      :message="ui.toastMessage"
    />

    <RequestHud
      v-if="requestInProgress"
      :title="requestTitle"
    />
  </div>
</template>
