<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  nodes: { type: Array, default: () => [] }, // [{ id, label, type, evidence? }]
  edges: { type: Array, default: () => [] }, // [{ source, target }]
});

const typeOrder = ['time_exec_period', 'time_progress', 'budget_total', 'budget_items', 'metric', 'other'];
const colors = {
  time_exec_period: '#2563eb',
  time_progress: '#0ea5e9',
  budget_total: '#16a34a',
  budget_items: '#22c55e',
  metric: '#f59e0b',
  other: '#6b7280',
};

const layout = computed(() => {
  const groups = {};
  props.nodes.forEach((n) => {
    const t = n.type || 'other';
    groups[t] = groups[t] || [];
    groups[t].push(n);
  });
  const orderedTypes = typeOrder.filter((t) => groups[t] && groups[t].length).concat(
    Object.keys(groups).filter((t) => !typeOrder.includes(t))
  );
  const colWidth = 240;
  const marginX = 60;
  const marginY = 60;
  const nodeSpacing = 90;
  const nodesPos = {};
  let maxRows = 0;
  orderedTypes.forEach((t, colIdx) => {
    const arr = groups[t] || [];
    maxRows = Math.max(maxRows, arr.length);
    arr.forEach((n, i) => {
      nodesPos[n.id] = {
        x: marginX + colIdx * colWidth,
        y: marginY + i * nodeSpacing,
        node: n,
      };
    });
  });
  const width = marginX * 2 + Math.max(0, orderedTypes.length - 1) * colWidth + 120;
  const height = marginY * 2 + Math.max(1, maxRows) * nodeSpacing;
  const typedColumns = orderedTypes.map((t, idx) => ({
    t,
    x: marginX + idx * colWidth,
  }));
  return { nodesPos, width, height, typedColumns };
});

const panX = ref(0);
const panY = ref(0);
const scale = ref(1);
const dragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const panStart = ref({ x: 0, y: 0 });

const selectedId = ref(null);
const tooltip = ref({ show: false, x: 0, y: 0, title: '', evidence: '' });

function onMouseDown(e) {
  dragging.value = true;
  dragStart.value = { x: e.clientX, y: e.clientY };
  panStart.value = { x: panX.value, y: panY.value };
}
function onMouseMove(e) {
  if (!dragging.value) return;
  const dx = e.clientX - dragStart.value.x;
  const dy = e.clientY - dragStart.value.y;
  panX.value = panStart.value.x + dx;
  panY.value = panStart.value.y + dy;
}
function onMouseUp() {
  dragging.value = false;
}
function onWheel(e) {
  e.preventDefault();
  const delta = e.deltaY > 0 ? -0.1 : 0.1;
  const next = Math.min(2.2, Math.max(0.6, scale.value + delta));
  scale.value = next;
}

function onNodeClick(pos, evt) {
  selectedId.value = pos.node.id;
  const evidence = pos.node.evidence || '';
  tooltip.value = {
    show: true,
    x: evt.clientX + 12,
    y: evt.clientY + 12,
    title: pos.node.label || '',
    evidence,
  };
}

function edgeColor(e) {
  if (selectedId.value && (e.source === selectedId.value || e.target === selectedId.value)) {
    return '#64748b';
  }
  return '#cbd5e1';
}

function nodeStroke(pos) {
  return selectedId.value === pos.node.id ? '#111827' : '#e5e7eb';
}
</script>

<template>
  <div class="graph-wrap" @mousedown="onMouseDown" @mousemove="onMouseMove" @mouseup="onMouseUp" @mouseleave="onMouseUp" @wheel="onWheel">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="graph-svg">
      <g :transform="`translate(${panX}, ${panY}) scale(${scale})`">
      <g class="edges">
        <line
          v-for="(e, idx) in edges"
          :key="`e-${idx}`"
          :x1="layout.nodesPos[e.source]?.x || 0"
          :y1="layout.nodesPos[e.source]?.y || 0"
          :x2="layout.nodesPos[e.target]?.x || 0"
          :y2="layout.nodesPos[e.target]?.y || 0"
          :stroke="edgeColor(e)"
          stroke-width="2"
          stroke-linecap="round"
        />
      </g>
      <g class="columns">
        <g v-for="col in layout.typedColumns" :key="col.t">
          <line :x1="col.x" y1="16" :x2="col.x" :y2="layout.height - 16" stroke="#e5e7eb" stroke-dasharray="4 4" />
          <text :x="col.x" y="24" text-anchor="middle" class="type-label">{{ col.t }}</text>
        </g>
      </g>
      <g class="nodes">
        <g v-for="(pos, id) in layout.nodesPos" :key="id" class="node" @click.stop="(e) => onNodeClick(pos, e)">
          <circle :cx="pos.x" :cy="pos.y" r="14" :fill="colors[pos.node.type] || colors.other" :stroke="nodeStroke(pos)" stroke-width="2" />
          <rect
            :x="pos.x + 18"
            :y="pos.y - 12"
            :width="Math.min(260, (pos.node.label || '').length * 10 + 16)"
            height="24"
            rx="6"
            fill="#fff"
            :stroke="nodeStroke(pos)"
          />
          <text :x="pos.x + 26" :y="pos.y + 6" class="node-label">{{ pos.node.label }}</text>
        </g>
      </g>
      </g>
    </svg>
    <div v-if="tooltip.show" class="tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
      <div class="tooltip-title">{{ tooltip.title }}</div>
      <div class="tooltip-ev">{{ tooltip.evidence || '暂无证据' }}</div>
    </div>
  </div>
  <div class="legend">
    <span class="legend-item" v-for="(c, key) in colors" :key="key">
      <span class="dot" :style="{ background: c }"></span>{{ key }}
    </span>
  </div>
  <div class="hint">关系图仅用于快速理解实体分布与关联，详细证据请查看上方“冲突详情”。</div>
</template>

<style scoped>
.graph-wrap {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
  margin-top: 12px;
}
.graph-svg {
  width: 100%;
  height: 360px;
  display: block;
}
.type-label {
  font-size: 12px;
  fill: #6b7280;
}
.node-label {
  font-size: 12px;
  fill: #111827;
}
.legend {
  margin-top: 8px;
  color: #6b7280;
  font-size: 12px;
}
.tooltip {
  position: fixed;
  max-width: 360px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
  z-index: 20;
}
.tooltip-title {
  font-size: 12px;
  color: #111827;
  margin-bottom: 6px;
}
.tooltip-ev {
  font-size: 12px;
  color: #374151;
  line-height: 1.4;
  word-break: break-all;
}
.legend-item {
  margin-right: 12px;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: #9ca3af;
}
</style>
