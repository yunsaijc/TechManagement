<script setup>
import { computed } from 'vue';

const emit = defineEmits(['select']);

const props = defineProps({
  actions: { type: Array, required: true },
  activeActionId: { type: String, default: null },
  variant: { type: String, default: 'grid' },
});

const selectedId = computed(() => props.activeActionId || (props.actions[0] ? props.actions[0].id : null));

function onChange(event) {
  emit('select', event.target.value);
}
</script>

<template>
  <div v-if="props.actions.length">
    <div v-if="props.variant === 'select'" class="action-selector action-selector-compact">
      <select
        class="action-selector-control"
        :value="selectedId"
        @change="onChange"
      >
        <option v-for="action in props.actions" :key="action.id" :value="action.id">
          {{ action.title }}
        </option>
      </select>
    </div>

    <div v-else class="action-tabs" :class="{ 'action-tabs-rail': props.variant === 'rail' }">
      <button
        v-for="(action, idx) in props.actions"
        :key="action.id"
        class="action-tab"
        :class="{ active: props.activeActionId === action.id }"
        @click="emit('select', action.id)"
      >
        <span class="action-tab-index">{{ idx + 1 }}</span>
        <span class="action-tab-body">
          <span class="action-tab-title">{{ action.title }}</span>
          <span class="action-tab-desc">{{ action.description || '执行该流程' }}</span>
        </span>
      </button>
    </div>
  </div>
</template>
