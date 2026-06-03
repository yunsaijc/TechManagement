<script setup>
defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  options: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['update:modelValue']);
</script>

<template>
  <div class="scenario-year-tabs">
    <button
      v-for="item in options"
      :key="item.year"
      type="button"
      class="scenario-year-tab"
      :class="{ active: modelValue === item.year }"
      @click="emit('update:modelValue', item.year)"
    >
      {{ item.label }}
    </button>
  </div>
</template>

<style scoped>
.scenario-year-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid #e8edf5;
  background: #f9fbfe;
}
.scenario-year-tab {
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #d8e1ef;
  background: #fff;
  color: #4a5f7d;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
.scenario-year-tab.active {
  border-color: #9dbbf7;
  color: #2b63df;
  background: #edf3ff;
}
</style>
