<script setup>
defineProps({
  cards: {
    type: Array,
    default: () => [],
  },
});
</script>

<template>
  <div class="scenario-metric-grid">
    <article v-for="card in cards" :key="card.label" class="metric-card">
      <span>{{ card.label }}</span>
      <strong>{{ card.value }}</strong>
      <div class="metric-delta" :class="card.cls || 'up'">{{ card.delta }}</div>
    </article>
  </div>
</template>

<style scoped>
.scenario-metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid #e9eef6;
  background: #fff;
}

.metric-card {
  border: 1px solid #e6ebf3;
  border-radius: 8px;
  padding: 8px;
  background: #fcfdff;
  min-height: 70px;
}

.metric-card span {
  font-size: 11px;
  color: #7e8b9e;
}

.metric-card strong {
  margin-top: 2px;
  display: block;
  font-size: 18px;
  color: #1f2f45;
}

.metric-delta {
  margin-top: 4px;
  font-size: 11px;
  font-weight: 700;
}
.metric-delta.up { color: #0f9f5f; }
.metric-delta.down { color: #e34a4a; }
.metric-delta.warn { color: #d9851a; }
.metric-delta.neutral { color: #64748b; }

@media (max-width: 1400px) {
  .scenario-metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .scenario-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
