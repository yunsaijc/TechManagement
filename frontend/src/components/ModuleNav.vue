<script setup>
import { computed } from 'vue';

const props = defineProps({
  modules: { type: Array, required: true },
  activeId: { type: String, required: true },
});

const emit = defineEmits(['select']);

const activeModule = computed(() => props.modules.find((m) => m.id === props.activeId) || null);
</script>

<template>
  <div class="sidebar-vertical">
    <div class="sidebar-header">
      <div class="sidebar-header-title">功能模块</div>
      <div class="sidebar-header-current" v-if="activeModule">
        <div class="sidebar-current-icon" />
        <div class="sidebar-current-text">{{ activeModule.title }}</div>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button
        v-for="module in modules"
        :key="module.id"
        class="sidebar-nav-item"
        :class="{ active: activeId === module.id }"
        @click="emit('select', module.id)"
      >
        <div class="sidebar-nav-item-title">{{ module.title }}</div>
      </button>
    </nav>
  </div>
</template>
