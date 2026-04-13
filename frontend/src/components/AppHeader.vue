<script setup>
defineProps({
  backendOk: { type: Boolean, required: true },
  backendStatus: { type: String, required: true },
  currentTime: { type: String, required: true },
  sidebarVisible: { type: Boolean, default: true },
});

const emit = defineEmits(['toggle-sidebar']);
</script>

<template>
  <div class="app-header">
    <div class="header-content">
      <div class="header-left">
        <button class="header-menu-toggle" @click="emit('toggle-sidebar')" :title="sidebarVisible ? '收起导航' : '展开导航'">
          <span class="menu-icon" :class="{ active: sidebarVisible }"></span>
        </button>
        <div class="header-logo">
          <div class="logo-icon">TP</div>
          <div>
            <div class="header-title">科技计划项目综合服务平台</div>
            <div class="header-subtitle">Science and Technology Program Project Integrated Service Platform</div>
          </div>
        </div>
      </div>
      <div class="header-right">
        <div class="header-info-item">
          <span class="header-info-label">系统状态：</span>
          <span class="header-status">
            <span class="header-status-dot" :class="{ ok: backendOk, fail: !backendOk }" />
            {{ backendStatus }}
          </span>
        </div>
        <div class="header-clock">{{ currentTime }}</div>
      </div>
    </div>
  </div>
</template>
