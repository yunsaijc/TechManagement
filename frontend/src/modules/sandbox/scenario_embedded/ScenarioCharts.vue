<script setup>
defineProps({
  payload: {
    type: Object,
    default: () => ({}),
  },
});
</script>

<template>
  <section class="scenario-charts-wrap">
    <div class="scenario-charts-grid">
      <article class="chart-card">
        <h3>{{ payload.applicationTitle }}</h3>
        <div class="legend"><span><i class="swatch base" />基准方案</span><span><i class="swatch scenario" />调整后方案</span></div>
        <div class="chart-html" v-html="payload.applicationSvg" />
      </article>
      <article class="chart-card">
        <h3>{{ payload.fundedTitle }}</h3>
        <div class="legend"><span><i class="swatch base" />基准方案</span><span><i class="swatch scenario" />调整后方案</span></div>
        <div class="chart-html" v-html="payload.fundedSvg" />
      </article>
      <article class="chart-card wide">
        <h3>{{ payload.fundingTitle }}</h3>
        <div class="legend"><span><i class="swatch direct" />直接影响</span><span><i class="swatch spill" />带动影响</span></div>
        <div class="chart-html" v-html="payload.fundingSvg" />
      </article>
    </div>
  </section>
</template>

<style scoped>
.scenario-charts-wrap {
  padding: 8px 8px 0;
  background: #fff;
}
.scenario-charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.chart-card {
  border: 1px solid #e6ebf3;
  border-radius: 8px;
  padding: 8px;
  background: #fbfcff;
}
.chart-card.wide {
  grid-column: 1 / -1;
}
.chart-card h3 {
  margin: 0;
  font-size: 12px;
  color: #2b3f57;
}
.legend {
  margin-top: 4px;
  display: flex;
  gap: 10px;
  color: #74839a;
  font-size: 11px;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  margin-right: 4px;
}
.swatch.base { background: #d9e2f1; }
.swatch.scenario { background: #3f7cff; }
.swatch.direct { background: #7aa5ff; }
.swatch.spill { background: #69d2a6; }
.chart-html {
  margin-top: 4px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #eef2f7;
  overflow: hidden;
}

:deep(.chart-frame) {
  width: 100%;
  height: auto;
  display: block;
}

@media (max-width: 1100px) {
  .scenario-charts-grid {
    grid-template-columns: 1fr;
  }
  .chart-card.wide {
    grid-column: auto;
  }
}
</style>
