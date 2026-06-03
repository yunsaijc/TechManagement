<script setup>
defineProps({
  rows: {
    type: Array,
    default: () => [],
  },
});
</script>

<template>
  <section class="scenario-impact-wrap">
    <h3>关键影响结果</h3>
    <div class="scenario-impact-scroll">
      <table v-if="rows.length" class="impact-table">
        <thead>
          <tr>
            <th>影响类型</th>
            <th>研究方向</th>
            <th>本批次变化</th>
            <th>当前规模</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rows" :key="`${item.impactType}-${item.fullLabel}`">
            <td><span class="pill" :class="item.impactClass">{{ item.impactType }}</span></td>
            <td>{{ item.fullLabel }}</td>
            <td>{{ item.changeText }}</td>
            <td>{{ item.baselineText }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="scenario-impact-empty">当前批次没有明显变化。</div>
    </div>
  </section>
</template>

<style scoped>
.scenario-impact-wrap {
  padding: 8px 8px 0;
  background: #fff;
}
.scenario-impact-wrap h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #2b3f57;
}
.scenario-impact-scroll {
  border: 1px solid #e6ebf3;
  border-radius: 8px;
  overflow: auto;
  max-height: 240px;
}
.impact-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.impact-table th,
.impact-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #edf2f8;
  text-align: left;
  vertical-align: top;
}
.impact-table th {
  position: sticky;
  top: 0;
  background: #f8fbff;
  z-index: 1;
}
.pill {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 700;
}
.pill.direct { background: #e8f1ff; color: #2e6be6; }
.pill.spill { background: #e9f7ef; color: #0f9f5f; }
.scenario-impact-empty {
  padding: 14px;
  color: #7a8699;
  font-size: 12px;
}
</style>
