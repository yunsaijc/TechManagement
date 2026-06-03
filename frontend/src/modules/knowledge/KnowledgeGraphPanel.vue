<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRequestStore } from '../../stores/request';

const req = useRequestStore();

const query = ref('人工智能');
const year = ref('2024');
const graphView = ref('all');
const startType = ref('project');
const loading = ref(false);
const error = ref('');
const graph = ref({ nodes: [], edges: [], typeCounts: {}, totals: {} });
const selectedNodeId = ref('');
const selectedEdgeId = ref('');
const labelMode = ref('all');
const hoveredNodeId = ref('');
const displayMode = ref('cluster');
const nextOffset = ref(0);
const hasMore = ref(false);
const loadingMore = ref(false);
const wideLoading = ref(false);
const drillLoading = ref(false);
const wideProgress = ref('');
const wideCoverage = ref({ combos: 0, pages: 0, emptyPages: 0, failedPages: 0, mode: '' });
const zoom = ref(0.72);
const pan = ref({ x: 0, y: 0 });
const dragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const panStart = ref({ x: 0, y: 0 });
const graphHistory = ref([]);

const nodes = computed(() => graph.value.nodes || []);
const edges = computed(() => graph.value.edges || []);
const selectedNode = computed(() => nodes.value.find((item) => item.id === selectedNodeId.value) || null);
const selectedEdge = computed(() => edges.value.find((item) => item.id === selectedEdgeId.value) || null);
const nodeMap = computed(() => new Map(nodes.value.map((item) => [item.id, item])));
const typeRows = computed(() => Object.entries(graph.value.typeCounts || {}).map(([label, value]) => ({ label, value })));
const hasGraph = computed(() => nodes.value.length > 0);
const searchHint = computed(() => {
  const parts = [];
  if (query.value.trim()) parts.push(`关键词「${query.value.trim()}」`);
  if (String(year.value || '').trim()) parts.push(`${year.value} 年`);
  parts.push(startOptions.find((item) => item.value === startType.value)?.label || '项目');
  parts.push(viewOptions.find((item) => item.value === graphView.value)?.label || '全部关系');
  return parts.join(' / ') || '默认项目样本';
});

const quickQueries = [
  '人工智能',
  '中医药',
  '电池储能',
  '生态环境',
  '半导体',
];

const viewOptions = [
  { value: 'all', label: '全部关系' },
  { value: 'project_person', label: '项目-人员' },
  { value: 'project_program', label: '项目-计划' },
  { value: 'project_output', label: '项目-成果论文' },
  { value: 'discipline', label: '学科概念' },
  { value: 'organization', label: '机构协作' },
];

const wideStarts = ['project', 'person', 'organization', 'paper', 'concept', 'discipline', 'output', 'venue', 'policy'];
const wideViews = ['all', 'project_person', 'project_program', 'project_output', 'discipline', 'organization'];
const WIDE_NODE_LIMIT = 9000;
const WIDE_EDGE_LIMIT = 14000;
const WIDE_BATCH_LIMIT = 36;
const WIDE_PAGES_PER_COMBO = 8;
const FULL_WIDE_BATCH_LIMIT = 56;
const FULL_WIDE_PAGES_PER_COMBO = 14;
const TYPE_NODE_LOAD_CAP = 500;

const startOptions = [
  { value: 'project', label: '项目' },
  { value: 'person', label: '人员' },
  { value: 'organization', label: '机构' },
  { value: 'paper', label: '论文' },
  { value: 'concept', label: '概念' },
  { value: 'discipline', label: '学科' },
  { value: 'output', label: '成果' },
  { value: 'venue', label: '期刊/会议' },
  { value: 'policy', label: '政策' },
];

const palette = {
  Project: '#f0b84b',
  Person: '#71c6a9',
  Organization: '#76a9ff',
  Org: '#76a9ff',
  Paper: '#db7c6d',
  Concept: '#b9a3ff',
  DisciplineL1: '#88d7f2',
  DisciplineL2: '#88d7f2',
  DisciplineL3: '#88d7f2',
  'Fund/Program': '#f4df72',
  Policy: '#ff9f7a',
  Output: '#9fd56e',
};

const layoutNodes = computed(() => {
  const centerX = 560;
  const centerY = 350;
  const rows = nodes.value;
  const projectNodes = rows.filter((item) => item.type === 'Project');
  const otherNodes = rows.filter((item) => item.type !== 'Project');
  const placed = [];

  projectNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(projectNodes.length, 1) - Math.PI / 2;
    const layer = Math.floor(index / 14);
    const radius = projectNodes.length <= 5 ? 130 : 190 + layer * 92;
    const offset = layer * 0.18;
    placed.push({
      ...node,
      x: centerX + Math.cos(angle + offset) * radius,
      y: centerY + Math.sin(angle + offset) * radius,
      r: 17,
    });
  });

  otherNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(otherNodes.length, 1) + Math.PI / 7;
    const ring = 340 + (index % 4) * 94;
    placed.push({
      ...node,
      x: centerX + Math.cos(angle) * ring,
      y: centerY + Math.sin(angle) * ring,
      r: node.type === 'Person' ? 13 : 12,
    });
  });

  return placed;
});

const layoutMap = computed(() => new Map(layoutNodes.value.map((item) => [item.id, item])));
const visibleEdges = computed(() => edges.value
  .map((edge) => ({ ...edge, sourceNode: layoutMap.value.get(edge.source), targetNode: layoutMap.value.get(edge.target) }))
  .filter((edge) => edge.sourceNode && edge.targetNode));
const clusterNodes = computed(() => {
  const counts = new Map();
  const globalCounts = graph.value.typeCounts || {};
  const localCounts = {};
  nodes.value.forEach((node) => {
    const key = nodeTypeKey(node);
    localCounts[key] = (localCounts[key] || 0) + 1;
  });

  Object.keys({ ...globalCounts, ...localCounts }).forEach((key) => {
    const inGraph = localCounts[key] || 0;
    const libraryCount = Number(globalCounts[key] || 0);
    const loadableCount = resolveTypeLoadLimit({ libraryCount, count: inGraph });
    counts.set(key, {
      id: `cluster:${key}`,
      label: key,
      type: key,
      typeLabel: key,
      count: loadableCount,
      libraryCount,
      sample: [],
    });
  });

  nodes.value.forEach((node) => {
    const key = nodeTypeKey(node);
    const current = counts.get(key);
    if (!current) return;
    if (current.sample.length < 4) current.sample.push(node.label);
  });
  const rows = Array.from(counts.values()).sort((a, b) => b.count - a.count);
  const centerX = 560;
  const centerY = 350;
  return rows.map((cluster, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(rows.length, 1) - Math.PI / 2;
    const radius = rows.length <= 1 ? 0 : 220 + (index % 2) * 78;
    return {
      ...cluster,
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
      r: Math.min(74, Math.max(28, 18 + Math.sqrt(cluster.count) * 4.2)),
    };
  });
});
const clusterMap = computed(() => new Map(clusterNodes.value.map((item) => [item.label, item])));
const clusterEdges = computed(() => {
  if (Array.isArray(graph.value.clusterEdges) && graph.value.clusterEdges.length) {
    return graph.value.clusterEdges
      .map((edge) => ({
        ...edge,
        sourceNode: clusterMap.value.get(edge.sourceLabel),
        targetNode: clusterMap.value.get(edge.targetLabel),
      }))
      .filter((edge) => edge.sourceNode && edge.targetNode);
  }
  const counts = new Map();
  edges.value.forEach((edge) => {
    const source = nodeMap.value.get(edge.source);
    const target = nodeMap.value.get(edge.target);
    if (!source || !target) return;
    const sourceLabel = source.typeLabel || source.type || '其他';
    const targetLabel = target.typeLabel || target.type || '其他';
    if (sourceLabel === targetLabel) return;
    const key = [sourceLabel, targetLabel].sort().join(' -> ');
    const current = counts.get(key) || {
      id: `cluster-edge:${key}`,
      sourceLabel,
      targetLabel,
      label: '类型关联',
      type: 'cluster',
      count: 0,
    };
    current.count += 1;
    counts.set(key, current);
  });
  return Array.from(counts.values())
    .map((edge) => ({
      ...edge,
      sourceNode: clusterMap.value.get(edge.sourceLabel),
      targetNode: clusterMap.value.get(edge.targetLabel),
    }))
    .filter((edge) => edge.sourceNode && edge.targetNode);
});
const graphNodes = computed(() => (displayMode.value === 'cluster' ? clusterNodes.value : layoutNodes.value));
const graphEdges = computed(() => (displayMode.value === 'cluster' ? clusterEdges.value : visibleEdges.value));
const graphTransform = computed(() => `translate(${pan.value.x}, ${pan.value.y}) scale(${zoom.value})`);
const zoomPercent = computed(() => `${Math.round(zoom.value * 100)}%`);
const nodeLabelLayouts = computed(() => buildNodeLabelLayouts());
const renderedGraphNodes = computed(() => graphNodes.value.map((node) => ({
  ...node,
  labelLayout: nodeLabelLayouts.value.get(node.id) || null,
})));
const canGoBack = computed(() => graphHistory.value.length > 0);
const breadcrumbTrail = computed(() => {
  const trail = graphHistory.value.map((item) => item.label);
  trail.push(currentLevelLabel());
  return trail;
});

function currentLevelLabel() {
  if (displayMode.value === 'cluster') {
    return `聚合 · ${searchHint.value}`;
  }
  if (selectedNodeId.value && selectedNode.value) {
    return shortLabel(selectedNode.value.label, 22);
  }
  const typeLabels = [...new Set(nodes.value.map((item) => item.typeLabel || item.type).filter(Boolean))];
  if (typeLabels.length === 1) {
    return `${typeLabels[0]} (${nodes.value.length})`;
  }
  return `节点列表 (${nodes.value.length})`;
}

function pushCurrentLevel() {
  graphHistory.value.push({
    label: currentLevelLabel(),
    graph: JSON.parse(JSON.stringify(graph.value)),
    displayMode: displayMode.value,
    selectedNodeId: selectedNodeId.value,
    selectedEdgeId: selectedEdgeId.value,
    nextOffset: nextOffset.value,
    hasMore: hasMore.value,
  });
}

function restoreSnapshot(snapshot) {
  graph.value = snapshot.graph;
  displayMode.value = snapshot.displayMode;
  selectedNodeId.value = snapshot.selectedNodeId;
  selectedEdgeId.value = snapshot.selectedEdgeId;
  nextOffset.value = snapshot.nextOffset;
  hasMore.value = snapshot.hasMore;
  resetView();
}

function clearGraphHistory() {
  graphHistory.value = [];
}

function goBack() {
  if (!canGoBack.value) return;
  const prev = graphHistory.value.pop();
  restoreSnapshot(prev);
  wideProgress.value = `已返回「${prev.label}」`;
}

function goBackToLevel(index) {
  if (index >= graphHistory.value.length) return;
  const target = graphHistory.value[index];
  graphHistory.value = graphHistory.value.slice(0, index);
  restoreSnapshot(target);
  wideProgress.value = `已返回「${target.label}」`;
}

function nodeColor(node) {
  return palette[node.type] || '#c7d2fe';
}

function isDimmedNode(node) {
  if (displayMode.value === 'cluster') return false;
  if (!selectedNodeId.value && !selectedEdgeId.value) return false;
  if (selectedNodeId.value) {
    if (node.id === selectedNodeId.value) return false;
    return !edges.value.some((edge) => (
      (edge.source === selectedNodeId.value && edge.target === node.id)
      || (edge.target === selectedNodeId.value && edge.source === node.id)
    ));
  }
  const edge = selectedEdge.value;
  return edge ? node.id !== edge.source && node.id !== edge.target : false;
}

function isActiveEdge(edge) {
  if (displayMode.value === 'cluster') return false;
  if (selectedEdgeId.value) return edge.id === selectedEdgeId.value;
  return selectedNodeId.value && (edge.source === selectedNodeId.value || edge.target === selectedNodeId.value);
}

function shortLabel(text, max = 18) {
  const value = String(text || '');
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function isNeighborNode(nodeId) {
  if (!selectedNodeId.value) return false;
  return edges.value.some((edge) => (
    (edge.source === selectedNodeId.value && edge.target === nodeId)
    || (edge.target === selectedNodeId.value && edge.source === nodeId)
  ));
}

function nodeLabelPriority(node) {
  if (selectedNodeId.value === node.id) return 120;
  if (hoveredNodeId.value === node.id) return 110;
  if (displayMode.value === 'cluster') return 90;
  if (node.type === 'Project') return 80;
  if (isNeighborNode(node.id)) return 70;
  if (node.type === 'Person') return 50;
  return 30;
}

function labelCharLimit(node) {
  const count = graphNodes.value.length;
  if (displayMode.value === 'cluster') return zoom.value >= 0.9 ? 16 : 12;
  if (labelMode.value === 'all' && count > 40) {
    return zoom.value >= 1.1 ? 14 : zoom.value >= 0.85 ? 10 : 8;
  }
  if (labelMode.value === 'all' && count > 20) {
    return zoom.value >= 1.1 ? 18 : zoom.value >= 0.85 ? 12 : 10;
  }
  if (node.type === 'Project') return zoom.value >= 1 ? 28 : 20;
  return zoom.value >= 1.1 ? 22 : zoom.value >= 0.85 ? 16 : 12;
}

function useCompactLabels() {
  return labelMode.value === 'all'
    && displayMode.value === 'nodes'
    && graphNodes.value.length > 20;
}

function shouldIncludeNodeLabel(node) {
  if (displayMode.value === 'cluster') return true;
  if (labelMode.value === 'hover') {
    return hoveredNodeId.value === node.id || selectedNodeId.value === node.id;
  }
  if (labelMode.value === 'all') return true;
  if (selectedNodeId.value === node.id) return true;
  if (node.type === 'Project') return true;
  if (selectedNodeId.value && isNeighborNode(node.id)) return true;
  if (graphNodes.value.length <= 18) return true;
  if (graphNodes.value.length <= 34 && zoom.value >= 0.88) return true;
  return zoom.value >= 1.15;
}

function rectsOverlap(a, b, padding = 8) {
  return !(
    a.x + a.w + padding < b.x
    || b.x + b.w + padding < a.x
    || a.y + a.h + padding < b.y
    || b.y + b.h + padding < a.y
  );
}

function buildCompactNodeLabelLayout(node) {
  const centerX = 560;
  const centerY = 350;
  const dx = node.x - centerX;
  const dy = node.y - centerY;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  const text = shortLabel(node.label, labelCharLimit(node));
  const offset = node.r + 14;
  const textX = node.x + ux * offset;
  const textY = node.y + uy * offset + 4;
  let textAnchor = 'middle';
  if (ux > 0.25) textAnchor = 'start';
  else if (ux < -0.25) textAnchor = 'end';

  return {
    compact: true,
    textX,
    textY,
    textAnchor,
    text,
    subtext: '',
    showLeader: false,
  };
}

function buildNodeLabelLayout(node) {
  const centerX = 560;
  const centerY = 350;
  const dx = node.x - centerX;
  const dy = node.y - centerY;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  const text = shortLabel(node.label, labelCharLimit(node));
  const subtext = displayMode.value === 'cluster' ? `${node.count} 个节点` : (node.typeLabel || node.type || '');
  const boxW = Math.max(92, Math.min(228, text.length * 12 + 28));
  const boxH = 38;
  const pad = node.r + 12;
  const anchorX = node.x + ux * pad;
  const anchorY = node.y + uy * pad;
  const leaderStart = { x: node.x + ux * node.r, y: node.y + uy * node.r };

  let rectX = 0;
  let rectY = 0;
  let textX = 0;
  let textY = 0;
  let subY = 0;
  let textAnchor = 'start';
  let leaderEnd = { x: anchorX, y: anchorY };

  if (ux >= 0.2) {
    rectX = anchorX + 6;
    rectY = anchorY - boxH / 2;
    textX = rectX + 10;
    textAnchor = 'start';
    leaderEnd = { x: rectX, y: anchorY };
  } else if (ux <= -0.2) {
    rectX = anchorX - boxW - 6;
    rectY = anchorY - boxH / 2;
    textX = rectX + boxW - 10;
    textAnchor = 'end';
    leaderEnd = { x: rectX + boxW, y: anchorY };
  } else if (uy < 0) {
    rectX = anchorX - boxW / 2;
    rectY = anchorY - boxH - 8;
    textX = anchorX;
    textAnchor = 'middle';
    textY = rectY + 16;
    subY = rectY + 30;
    leaderEnd = { x: anchorX, y: rectY + boxH };
  } else {
    rectX = anchorX - boxW / 2;
    rectY = anchorY + 8;
    textX = anchorX;
    textAnchor = 'middle';
    textY = rectY + 16;
    subY = rectY + 30;
    leaderEnd = { x: anchorX, y: rectY };
  }

  if (!textY) textY = rectY + 16;
  if (!subY) subY = rectY + 30;

  return {
    compact: false,
    rectX,
    rectY,
    boxW,
    boxH,
    textX,
    textY,
    subY,
    textAnchor,
    text,
    subtext,
    leaderStart,
    leaderEnd,
    showLeader: dist > 80,
  };
}

function buildNodeLabelLayouts() {
  const compact = useCompactLabels();
  const candidates = graphNodes.value
    .filter((node) => shouldIncludeNodeLabel(node))
    .map((node) => ({
      node,
      layout: compact ? buildCompactNodeLabelLayout(node) : buildNodeLabelLayout(node),
      priority: nodeLabelPriority(node),
    }));

  if (labelMode.value === 'all' || labelMode.value === 'hover') {
    const layouts = new Map();
    candidates.forEach((item) => layouts.set(item.node.id, item.layout));
    return layouts;
  }

  candidates.sort((a, b) => b.priority - a.priority);

  const placed = [];
  const layouts = new Map();
  const useCollisionGuard = graphNodes.value.length > 18;

  candidates.forEach((item) => {
    if (item.layout.compact) {
      layouts.set(item.node.id, item.layout);
      return;
    }
    const box = {
      x: item.layout.rectX,
      y: item.layout.rectY,
      w: item.layout.boxW,
      h: item.layout.boxH,
    };
    if (useCollisionGuard && item.priority < 115) {
      const overlaps = placed.some((placedBox) => rectsOverlap(box, placedBox));
      if (overlaps) return;
    }
    placed.push(box);
    layouts.set(item.node.id, item.layout);
  });

  return layouts;
}

function onNodeMouseEnter(node) {
  hoveredNodeId.value = node.id;
}

function onNodeMouseLeave(node) {
  if (hoveredNodeId.value === node.id) hoveredNodeId.value = '';
}

function edgeTitle(edge) {
  if (displayMode.value === 'cluster') {
    return `${edge.sourceLabel} 与 ${edge.targetLabel} 共 ${edge.count || 0} 条关系`;
  }
  const source = nodeMap.value.get(edge.source)?.label || edge.source;
  const target = nodeMap.value.get(edge.target)?.label || edge.target;
  return `${shortLabel(source, 16)} ${edge.label || edge.type} ${shortLabel(target, 16)}`;
}

function edgeEndpoint(edge, key) {
  if (displayMode.value === 'cluster') return key === 'source' ? edge.sourceLabel : edge.targetLabel;
  return nodeMap.value.get(edge[key])?.label || edge[key];
}

function propRows(node) {
  return Object.entries(node?.properties || {}).filter(([, value]) => value !== undefined && value !== null && String(value).trim());
}

function nodeTypeKey(node) {
  return node.typeLabel || node.type || '其他';
}

function resolveTypeLoadLimit(cluster) {
  const libraryCount = Number(cluster?.libraryCount || 0);
  const inGraph = Number(cluster?.count || 0);
  const basis = libraryCount > 0 ? libraryCount : inGraph;
  if (basis > TYPE_NODE_LOAD_CAP) return TYPE_NODE_LOAD_CAP;
  return Math.max(basis, 1);
}

function collectTypeNodes(typeLabel) {
  return nodes.value.filter((node) => nodeTypeKey(node) === typeLabel);
}

function buildClusterExpansionPage(typeLabel) {
  const matchingNodes = collectTypeNodes(typeLabel);
  const nodeIds = new Set(matchingNodes.map((node) => node.id));
  const relatedEdges = edges.value.filter((edge) => nodeIds.has(edge.source) || nodeIds.has(edge.target));
  return {
    status: 'ok',
    source: graph.value.source,
    mode: 'type_page',
    query: graph.value.query ?? query.value,
    year: graph.value.year ?? year.value,
    nodes: matchingNodes,
    edges: relatedEdges,
    typeCounts: summarizeTypes(matchingNodes),
    totals: {
      nodes: matchingNodes.length,
      relationships: relatedEdges.length,
    },
    hasMore: false,
    view: graphView.value,
    start: startType.value,
  };
}

function mergeGraphNodes(primaryNodes, extraNodes) {
  const byId = new Map(primaryNodes.map((node) => [node.id, node]));
  (extraNodes || []).forEach((node) => byId.set(node.id, node));
  return Array.from(byId.values());
}

function mergeGraphEdges(primaryEdges, extraEdges) {
  const byId = new Map(primaryEdges.map((edge) => [edge.id, edge]));
  (extraEdges || []).forEach((edge) => byId.set(edge.id, edge));
  return Array.from(byId.values());
}

async function selectGraphNode(node) {
  if (displayMode.value === 'cluster' && node.count) {
    pushCurrentLevel();
    selectedEdgeId.value = '';
    selectedNodeId.value = node.id;
    drillLoading.value = true;
    error.value = '';
    const typeLabel = node.label;
    const targetLimit = resolveTypeLoadLimit(node);
    wideProgress.value = `正在展开「${typeLabel}」，目标加载 ${targetLimit} 个节点...`;
    try {
      let page = buildClusterExpansionPage(typeLabel);
      if (page.nodes.length < targetLimit) {
        try {
          const remotePage = await fetchTypeNodesUpTo(typeLabel, targetLimit);
          const mergedNodes = mergeGraphNodes(page.nodes, remotePage.nodes).slice(0, targetLimit);
          const nodeIds = new Set(mergedNodes.map((item) => item.id));
          const mergedEdges = mergeGraphEdges(page.edges, remotePage.edges)
            .filter((edge) => nodeIds.has(edge.source) || nodeIds.has(edge.target));
          page = {
            ...page,
            ...remotePage,
            nodes: mergedNodes,
            edges: mergedEdges,
            typeCounts: summarizeTypes(mergedNodes),
            totals: {
              nodes: mergedNodes.length,
              relationships: mergedEdges.length,
            },
            hasMore: Number(node.libraryCount || 0) > TYPE_NODE_LOAD_CAP,
          };
        } catch (remoteErr) {
          if (!page.nodes.length) throw remoteErr;
        }
      }
      if (!page.nodes.length) {
        graphHistory.value.pop();
        error.value = `「${typeLabel}」在当前图谱中没有可展开节点。`;
        return;
      }
      graph.value = page;
      displayMode.value = 'nodes';
      selectedNodeId.value = '';
      selectedEdgeId.value = '';
      wideProgress.value = `已展开「${typeLabel}」：显示 ${page.nodes.length} 个节点 / ${page.edges.length} 条关系。`;
      resetView();
    } catch (err) {
      graphHistory.value.pop();
      error.value = err?.message || String(err);
    } finally {
      drillLoading.value = false;
    }
    return;
  }
  if (displayMode.value === 'nodes' && node.elementId) {
    pushCurrentLevel();
    selectedEdgeId.value = '';
    selectedNodeId.value = node.id;
    drillLoading.value = true;
    error.value = '';
    wideProgress.value = `正在展开「${shortLabel(node.label, 18)}」的一跳邻居...`;
    try {
      const page = await fetchNodeNeighbors(node.elementId);
      graph.value = page;
      selectedNodeId.value = page.nodes?.find((item) => item.elementId === node.elementId)?.id || node.id;
      selectedEdgeId.value = '';
      wideProgress.value = `已展开「${shortLabel(node.label, 18)}」一跳邻居：${nodes.value.length} 节点 / ${edges.value.length} 边。`;
      resetView();
    } catch (err) {
      graphHistory.value.pop();
      error.value = err?.message || String(err);
    } finally {
      drillLoading.value = false;
    }
    return;
  }
  selectedEdgeId.value = '';
  selectedNodeId.value = node.id;
}

function selectGraphEdge(edge) {
  selectedNodeId.value = '';
  selectedEdgeId.value = edge.id;
}

function summarizeTypes(rows) {
  const counts = {};
  rows.forEach((node) => {
    counts[node.typeLabel] = (counts[node.typeLabel] || 0) + 1;
  });
  return counts;
}

function mergeGraphPage(page) {
  const nodeMapById = new Map(nodes.value.map((node) => [node.id, node]));
  (page.nodes || []).forEach((node) => nodeMapById.set(node.id, node));
  const edgeMapById = new Map(edges.value.map((edge) => [edge.id, edge]));
  (page.edges || []).forEach((edge) => edgeMapById.set(edge.id, edge));
  const mergedNodes = Array.from(nodeMapById.values()).slice(0, WIDE_NODE_LIMIT);
  const nodeIds = new Set(mergedNodes.map((node) => node.id));
  const mergedEdges = Array.from(edgeMapById.values())
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .slice(0, WIDE_EDGE_LIMIT);
  graph.value = {
    ...page,
    nodes: mergedNodes,
    edges: mergedEdges,
    typeCounts: summarizeTypes(mergedNodes),
    totals: {
      nodes: mergedNodes.length,
      relationships: mergedEdges.length,
    },
  };
  nextOffset.value = Number(page.nextOffset || 0);
  hasMore.value = Boolean(page.hasMore);
}

function mergeWideGraphPage(page) {
  mergeGraphPage(page);
  hasMore.value = false;
  nextOffset.value = wideCoverage.value.pages;
}

async function fetchGraphPage(offset = 0) {
  const params = new URLSearchParams();
  if (query.value.trim()) params.set('query', query.value.trim());
  if (String(year.value || '').trim()) params.set('year', String(year.value).trim());
  params.set('limit', '30');
  params.set('offset', String(offset));
  params.set('view', graphView.value);
  params.set('start', startType.value);
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph?${params.toString()}`, { method: 'GET' }, 45000);
}

async function fetchGraphPageFor({ start, view, offset = 0, batchLimit = 12, includeFilters = true, timeoutMs = 22000 }) {
  const params = new URLSearchParams();
  if (includeFilters && query.value.trim()) params.set('query', query.value.trim());
  if (includeFilters && String(year.value || '').trim()) params.set('year', String(year.value).trim());
  params.set('limit', String(batchLimit));
  params.set('offset', String(offset));
  params.set('view', view);
  params.set('start', start);
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph?${params.toString()}`, { method: 'GET' }, timeoutMs);
}

async function fetchWideGraph({ fullLibrary = false, taskOffset = 0, taskLimit = 8 } = {}) {
  const params = new URLSearchParams();
  if (!fullLibrary && query.value.trim()) params.set('query', query.value.trim());
  if (!fullLibrary && String(year.value || '').trim()) params.set('year', String(year.value).trim());
  params.set('fullLibrary', String(fullLibrary));
  params.set('batchLimit', String(fullLibrary ? 12 : 10));
  params.set('pagesPerCombo', String(fullLibrary ? FULL_WIDE_PAGES_PER_COMBO : WIDE_PAGES_PER_COMBO));
  params.set('offsetStride', String(fullLibrary ? 18 : 8));
  params.set('nodeLimit', String(WIDE_NODE_LIMIT));
  params.set('edgeLimit', String(WIDE_EDGE_LIMIT));
  params.set('timeoutSeconds', String(fullLibrary ? 4 : 5));
  params.set('taskOffset', String(taskOffset));
  params.set('taskLimit', String(taskLimit));
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph/wide?${params.toString()}`, { method: 'GET' }, 28000);
}

async function fetchGraphOverview() {
  const params = new URLSearchParams();
  params.set('samplePerLabel', '18');
  params.set('samplePerRelation', '8');
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph/overview?${params.toString()}`, { method: 'GET' }, 60000);
}

async function fetchTypeNodes(typeLabel, offset = 0, limit = 120) {
  const params = new URLSearchParams();
  params.set('typeLabel', typeLabel);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  params.set('view', graphView.value);
  params.set('start', startType.value);
  if (query.value.trim()) params.set('query', query.value.trim());
  if (String(year.value || '').trim()) params.set('year', String(year.value).trim());
  const timeoutMs = limit >= 300 ? 90000 : 60000;
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph/type?${params.toString()}`, { method: 'GET' }, timeoutMs);
}

async function fetchTypeNodesUpTo(typeLabel, targetLimit) {
  const pageSize = Math.min(120, targetLimit);
  let offset = 0;
  let mergedNodes = [];
  let mergedEdges = [];
  let lastPage = { nodes: [], edges: [], hasMore: false };

  while (mergedNodes.length < targetLimit) {
    const batchLimit = Math.min(pageSize, targetLimit - mergedNodes.length);
    const page = await fetchTypeNodes(typeLabel, offset, batchLimit);
    lastPage = page;
    mergedNodes = mergeGraphNodes(mergedNodes, page.nodes || []);
    mergedEdges = mergeGraphEdges(mergedEdges, page.edges || []);
    if (!page.hasMore || !(page.nodes || []).length) break;
    offset = Number(page.nextOffset ?? offset + batchLimit);
    if (offset >= targetLimit) break;
  }

  const nodes = mergedNodes.slice(0, targetLimit);
  const nodeIds = new Set(nodes.map((item) => item.id));
  const relatedEdges = mergedEdges.filter((edge) => nodeIds.has(edge.source) || nodeIds.has(edge.target));
  return {
    ...lastPage,
    nodes,
    edges: relatedEdges,
    typeCounts: summarizeTypes(nodes),
    totals: {
      nodes: nodes.length,
      relationships: relatedEdges.length,
    },
  };
}

async function fetchNodeNeighbors(elementId) {
  const params = new URLSearchParams();
  params.set('elementId', elementId);
  params.set('limit', '90');
  return req.fetchWithTimeout(`${req.apiBase()}/sandbox/knowledge-graph/neighbors?${params.toString()}`, { method: 'GET' }, 60000);
}

async function loadGraph() {
  loading.value = true;
  error.value = '';
  selectedNodeId.value = '';
  selectedEdgeId.value = '';
  nextOffset.value = 0;
  hasMore.value = false;
  clearGraphHistory();
  try {
    const page = await fetchGraphPage(0);
    graph.value = { nodes: [], edges: [], typeCounts: {}, totals: {} };
    mergeGraphPage(page);
    resetView();
  } catch (err) {
    error.value = err?.message || String(err);
  } finally {
    loading.value = false;
  }
}

async function loadNextBatch() {
  if (!hasMore.value || loadingMore.value || loading.value) return;
  loadingMore.value = true;
  error.value = '';
  try {
    const page = await fetchGraphPage(nextOffset.value);
    mergeGraphPage(page);
  } catch (err) {
    error.value = err?.message || String(err);
  } finally {
    loadingMore.value = false;
  }
}

async function loadAllBatches(maxRounds = 8) {
  let rounds = 0;
  while (hasMore.value && rounds < maxRounds) {
    await loadNextBatch();
    rounds += 1;
  }
}

async function loadWideSample({ fullLibrary = false } = {}) {
  if (wideLoading.value || loading.value || loadingMore.value) return;
  wideLoading.value = true;
  error.value = '';
  clearGraphHistory();
  graph.value = { nodes: [], edges: [], typeCounts: {}, totals: {} };
  wideCoverage.value = { combos: 0, pages: 0, emptyPages: 0, failedPages: 0, mode: fullLibrary ? '全库' : '当前筛选' };
  selectedNodeId.value = '';
  selectedEdgeId.value = '';
  try {
    if (fullLibrary) {
      wideProgress.value = '正在读取 Neo4j 全库快速概览：统计所有类型规模，并抽取少量代表节点/边...';
      const page = await fetchGraphOverview();
      graph.value = page;
      const coverage = page.coverage || {};
      wideCoverage.value = {
        combos: Number(coverage.combos || 0),
        pages: Number(coverage.pages || 1),
        emptyPages: 0,
        failedPages: Number(coverage.failedPages || 0),
        mode: '全库概览',
      };
      displayMode.value = 'cluster';
      wideProgress.value = `全库概览已加载：库内约 ${page.totals?.nodes || 0} 节点 / ${page.totals?.relationships || 0} 边；页面展示 ${nodes.value.length} 个代表节点 / ${edges.value.length} 条代表边`;
      return;
    }
    const maxPages = wideStarts.length * wideViews.length * (fullLibrary ? FULL_WIDE_PAGES_PER_COMBO : WIDE_PAGES_PER_COMBO);
    let taskOffset = 0;
    const taskLimit = fullLibrary ? 3 : 4;
    let slowBatches = 0;
    let totalTasks = maxPages;
    let hasMoreTasks = true;
    while (hasMoreTasks && nodes.value.length < WIDE_NODE_LIMIT && edges.value.length < WIDE_EDGE_LIMIT) {
      wideProgress.value = `${fullLibrary ? '全库分批聚合' : '当前条件分批聚合'}：${taskOffset}/${totalTasks}，已合并 ${nodes.value.length} 节点 / ${edges.value.length} 边`;
      let page;
      try {
        page = await fetchWideGraph({ fullLibrary, taskOffset, taskLimit });
      } catch (err) {
        slowBatches += 1;
        taskOffset += taskLimit;
        wideCoverage.value = {
          ...wideCoverage.value,
          failedPages: Number(wideCoverage.value.failedPages || 0) + taskLimit,
        };
        wideProgress.value = `已跳过慢批次 ${slowBatches} 个：继续从 ${taskOffset}/${totalTasks} 采样，当前已合并 ${nodes.value.length} 节点 / ${edges.value.length} 边`;
        if (slowBatches >= 8) break;
        continue;
      }
      mergeWideGraphPage(page);
      const coverage = page.coverage || {};
      totalTasks = Number(coverage.totalTasks || totalTasks);
      taskOffset = Number(coverage.nextTaskOffset || taskOffset + taskLimit);
      hasMoreTasks = Boolean(coverage.hasMoreTasks);
      wideCoverage.value = {
        combos: Math.max(Number(wideCoverage.value.combos || 0), Number(coverage.combos || 0)),
        pages: Number(wideCoverage.value.pages || 0) + Number(coverage.pages || 0),
        emptyPages: 0,
        failedPages: Number(wideCoverage.value.failedPages || 0) + Number(coverage.failedPages || 0),
        mode: fullLibrary ? '全库' : '当前筛选',
      };
    }
    wideProgress.value = `${wideCoverage.value.mode}分批聚合${hasMoreTasks ? '已暂停' : '完成'}：${nodes.value.length} 节点 / ${edges.value.length} 边，扫描 ${wideCoverage.value.pages} 页，跳过慢页 ${wideCoverage.value.failedPages} 页`;
  } catch (err) {
    error.value = err?.message || String(err);
  } finally {
    resetView();
    wideLoading.value = false;
  }
}

function onKeywordChange() {
  loadGraph();
}

function onViewChange() {
  loadGraph();
}

function onStartTypeChange() {
  loadGraph();
}

function clampZoom(value) {
  return Math.min(2.4, Math.max(0.34, value));
}

function zoomBy(delta) {
  zoom.value = clampZoom(zoom.value + delta);
}

function resetView() {
  zoom.value = 0.72;
  pan.value = { x: 0, y: 0 };
}

function onWheel(event) {
  event.preventDefault();
  const rect = event.currentTarget.getBoundingClientRect();
  const mouseX = ((event.clientX - rect.left) / rect.width) * 1120;
  const mouseY = ((event.clientY - rect.top) / rect.height) * 700;
  const oldZoom = zoom.value;
  const next = clampZoom(zoom.value + (event.deltaY > 0 ? -0.08 : 0.08));
  if (next === oldZoom) return;
  const ratio = next / oldZoom;
  pan.value = {
    x: mouseX - (mouseX - pan.value.x) * ratio,
    y: mouseY - (mouseY - pan.value.y) * ratio,
  };
  zoom.value = next;
}

function onGraphMouseDown(event) {
  if (event.button !== 0) return;
  dragging.value = true;
  dragStart.value = { x: event.clientX, y: event.clientY };
  panStart.value = { ...pan.value };
}

function onGraphMouseMove(event) {
  if (!dragging.value) return;
  pan.value = {
    x: panStart.value.x + event.clientX - dragStart.value.x,
    y: panStart.value.y + event.clientY - dragStart.value.y,
  };
}

function onGraphMouseUp() {
  dragging.value = false;
}

onMounted(loadGraph);
</script>

<template>
  <div class="kg-view">
    <section class="kg-topbar">
      <div class="kg-hero">
        <div>
          <div class="eyebrow">Neo4j Knowledge Graph</div>
          <h2>项目知识图谱</h2>
          <p>连接 192.168.0.198 的 Neo4j 图数据库，按项目搜索抽取一跳子图，帮助快速查看项目、人员、机构、计划与成果之间的关系。</p>
        </div>
        <form class="kg-search" @submit.prevent="loadGraph">
        <label>
          <span>关键词</span>
          <select v-model="query" @change="onKeywordChange">
            <option v-for="item in quickQueries" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label>
          <span>加载视角</span>
          <select v-model="graphView" @change="onViewChange">
            <option v-for="item in viewOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label>
          <span>起点类型</span>
          <select v-model="startType" @change="onStartTypeChange">
            <option v-for="item in startOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label>
          <span>年份</span>
          <input v-model="year" type="number" min="2000" max="2035" placeholder="可空" />
          </label>
          <button type="submit" :disabled="loading">{{ loading ? '读取中...' : '刷新图谱' }}</button>
        </form>
      </div>

      <section class="kg-stats">
        <div class="stat-card">
          <span>当前节点</span>
          <strong>{{ nodes.length }}</strong>
        </div>
        <div class="stat-card">
          <span>当前关系</span>
          <strong>{{ edges.length }}</strong>
        </div>
        <div class="stat-card">
          <span>已扫描页数</span>
          <strong>{{ wideCoverage.pages || nextOffset }}</strong>
        </div>
        <div class="stat-card">
          <span>覆盖规则</span>
          <strong>{{ wideCoverage.combos || 1 }}</strong>
        </div>
        <div v-for="row in typeRows" :key="row.label" class="stat-card stat-card-type">
          <span>{{ row.label }}</span>
          <strong>{{ row.value }}</strong>
        </div>
      </section>
    </section>

    <section class="batch-bar">
      <div class="batch-copy">
        <strong>{{ wideLoading ? '正在后端聚合图谱数据' : hasMore ? '当前筛选可继续分页加载' : '当前普通分页已到末尾' }}</strong>
        <span>{{ wideProgress || '普通分页只追加当前筛选结果；广域采样会由后端跨类型、关系和 offset 聚合更多节点与边。' }}</span>
      </div>
      <div class="batch-actions">
        <div class="action-group">
          <span>当前筛选</span>
          <button type="button" :disabled="!hasMore || loadingMore || loading || wideLoading" @click="loadNextBatch">
            {{ loadingMore ? '加载中...' : '追加一页' }}
          </button>
          <button type="button" :disabled="!hasMore || loadingMore || loading || wideLoading" @click="loadAllBatches">
            自动追加
          </button>
        </div>
        <div class="action-group action-group-wide">
          <span>后端广域采样</span>
          <button type="button" :disabled="wideLoading || loading || loadingMore" @click="loadWideSample()">
            {{ wideLoading ? '聚合中...' : '按当前条件聚合' }}
          </button>
          <button type="button" class="primary-sample" :disabled="wideLoading || loading || loadingMore" @click="loadWideSample({ fullLibrary: true })">
            {{ wideLoading ? '全库聚合中...' : '全库聚合展示' }}
          </button>
        </div>
      </div>
    </section>

    <div v-if="error" class="error-box">
      <div>
        <strong>图谱读取失败</strong>
        <span>{{ error }}</span>
      </div>
      <button type="button" @click="loadGraph">重试</button>
    </div>

    <section class="kg-main">
      <div
        class="graph-shell"
        :class="{ dragging }"
        @mousedown="onGraphMouseDown"
        @mousemove="onGraphMouseMove"
        @mouseup="onGraphMouseUp"
        @mouseleave="onGraphMouseUp"
        @wheel="onWheel"
      >
        <div class="graph-toolbar">
          <button type="button" :disabled="!canGoBack" @click.stop="goBack">返回上一级</button>
          <button type="button" @click.stop="zoomBy(0.12)">放大</button>
          <button type="button" @click.stop="zoomBy(-0.12)">缩小</button>
          <button type="button" @click.stop="resetView">重置</button>
          <button type="button" :disabled="!hasMore || loadingMore" @click.stop="loadNextBatch">下一批</button>
          <button type="button" :class="{ active: displayMode === 'cluster' }" @click.stop="displayMode = 'cluster'">聚合视图</button>
          <button type="button" :class="{ active: displayMode === 'nodes' }" @click.stop="displayMode = 'nodes'">节点视图</button>
          <label class="label-mode-control">
            <span>名称</span>
            <select v-model="labelMode">
              <option value="all">全部名称</option>
              <option value="smart">智能显示</option>
              <option value="hover">悬停显示</option>
            </select>
          </label>
          <span>{{ zoomPercent }}</span>
        </div>
        <nav v-if="canGoBack" class="graph-breadcrumb" @click.stop>
          <template v-for="(label, index) in breadcrumbTrail" :key="`crumb-${index}`">
            <button
              type="button"
              class="crumb"
              :class="{ active: index === breadcrumbTrail.length - 1 }"
              :disabled="index === breadcrumbTrail.length - 1"
              @click="goBackToLevel(index)"
            >
              {{ label }}
            </button>
            <span v-if="index < breadcrumbTrail.length - 1" class="crumb-sep">›</span>
          </template>
        </nav>
        <div v-if="loading || drillLoading" class="graph-overlay">
          <div class="pulse-orbit"></div>
          <strong>{{ drillLoading ? '正在展开局部子图' : '正在扫描 Neo4j 子图' }}</strong>
          <span>{{ drillLoading ? wideProgress : searchHint }}</span>
        </div>
        <div v-else-if="!hasGraph" class="graph-overlay graph-empty">
          <strong>暂无可展示节点</strong>
          <span>换一个关键词或清空年份后再试。建议先从“人工智能”“中医药”“电池储能”开始。</span>
        </div>
        <svg class="kg-svg" viewBox="0 0 1120 700" role="img" aria-label="项目知识图谱">
          <defs>
            <radialGradient id="kgGlow" cx="50%" cy="50%" r="60%">
              <stop offset="0%" stop-color="#284366" stop-opacity="0.95" />
              <stop offset="100%" stop-color="#0a1422" stop-opacity="1" />
            </radialGradient>
          </defs>
          <rect width="1120" height="700" rx="28" fill="url(#kgGlow)" />
          <circle cx="560" cy="350" r="150" fill="none" stroke="#4d6380" stroke-dasharray="8 10" opacity="0.55" />
          <circle cx="560" cy="350" r="285" fill="none" stroke="#334f6d" stroke-dasharray="3 14" opacity="0.45" />
          <g :transform="graphTransform">
            <g class="edges">
              <g v-for="edge in graphEdges" :key="edge.id" class="edge" @click.stop="selectGraphEdge(edge)">
                <line
                  :x1="edge.sourceNode.x"
                  :y1="edge.sourceNode.y"
                  :x2="edge.targetNode.x"
                  :y2="edge.targetNode.y"
                  :stroke="isActiveEdge(edge) ? '#ffe08a' : '#7990a9'"
                  :stroke-width="displayMode === 'cluster' ? Math.min(10, 1.8 + Math.sqrt(edge.count || 1)) : isActiveEdge(edge) ? 4.2 : 1.25"
                  :opacity="displayMode === 'cluster' ? 0.44 : isActiveEdge(edge) ? 0.95 : 0.22"
                  stroke-linecap="round"
                />
              </g>
            </g>
            <g class="nodes">
              <g
                v-for="node in renderedGraphNodes"
                :key="node.id"
                class="node"
                :class="{ dimmed: isDimmedNode(node), selected: selectedNodeId === node.id }"
                @click.stop="selectGraphNode(node)"
                @mouseenter="onNodeMouseEnter(node)"
                @mouseleave="onNodeMouseLeave(node)"
              >
                <circle :cx="node.x" :cy="node.y" :r="node.r + 12" :fill="nodeColor(node)" opacity="0.12" />
                <circle :cx="node.x" :cy="node.y" :r="node.r" :fill="nodeColor(node)" stroke="#f8fafc" stroke-width="1.5" />
                <text
                  v-if="displayMode === 'cluster'"
                  :x="node.x"
                  :y="node.y + 6"
                  text-anchor="middle"
                  class="cluster-count"
                >{{ node.count }}</text>
                <g v-if="node.labelLayout" class="node-label-group">
                  <template v-if="node.labelLayout.compact">
                    <title>{{ node.label }}</title>
                    <text
                      :x="node.labelLayout.textX"
                      :y="node.labelLayout.textY"
                      :text-anchor="node.labelLayout.textAnchor"
                      class="node-label node-label-compact"
                    >{{ node.labelLayout.text }}</text>
                  </template>
                  <template v-else>
                    <title>{{ node.label }}</title>
                    <line
                      v-if="node.labelLayout.showLeader"
                      :x1="node.labelLayout.leaderStart.x"
                      :y1="node.labelLayout.leaderStart.y"
                      :x2="node.labelLayout.leaderEnd.x"
                      :y2="node.labelLayout.leaderEnd.y"
                      class="label-leader"
                    />
                    <rect
                      :x="node.labelLayout.rectX"
                      :y="node.labelLayout.rectY"
                      :width="node.labelLayout.boxW"
                      :height="node.labelLayout.boxH"
                      rx="10"
                      class="label-bg"
                    />
                    <text
                      :x="node.labelLayout.textX"
                      :y="node.labelLayout.textY"
                      :text-anchor="node.labelLayout.textAnchor"
                      class="node-label"
                    >{{ node.labelLayout.text }}</text>
                    <text
                      :x="node.labelLayout.textX"
                      :y="node.labelLayout.subY"
                      :text-anchor="node.labelLayout.textAnchor"
                      class="node-type"
                    >{{ node.labelLayout.subtext }}</text>
                  </template>
                </g>
              </g>
            </g>
          </g>
        </svg>
      </div>

      <aside class="kg-side">
        <div class="side-card focus-card">
          <div class="side-title">当前焦点</div>
          <div class="focus-card-body">
            <template v-if="selectedNode">
              <div class="focus-type">{{ selectedNode.typeLabel }}</div>
              <h3>{{ selectedNode.label }}</h3>
              <p v-if="selectedNode.count" class="muted">该聚合簇包含 {{ selectedNode.count }} 个节点。示例：{{ selectedNode.sample?.join('、') || '暂无示例' }}</p>
              <dl>
                <template v-for="[key, value] in propRows(selectedNode)" :key="key">
                  <dt>{{ key }}</dt>
                  <dd>{{ value }}</dd>
                </template>
              </dl>
            </template>
            <template v-else-if="selectedEdge">
              <div class="focus-type">{{ selectedEdge.label }}</div>
              <h3>{{ edgeTitle(selectedEdge) }}</h3>
              <p class="muted">关系类型：{{ selectedEdge.type }}</p>
            </template>
            <p v-else class="muted">聚合视图下点击类型簇可展开一批真实节点；节点视图下点击真实节点可展开一跳邻居和关系。展开后可点「返回上一级」或面包屑回到之前的视图。</p>
          </div>
        </div>

        <div class="side-card edge-panel">
          <div class="side-title side-title-row">
            <span>关系清单</span>
            <em>{{ graphEdges.length }} 条</em>
          </div>
          <p v-if="!graphEdges.length" class="muted">暂无关系边。可以放宽关键词或年份，让子图抓到更多邻接节点。</p>
          <div v-else class="edge-list">
            <button
              v-for="edge in graphEdges.slice(0, 40)"
              :key="`edge-row-${edge.id}`"
              type="button"
              class="edge-row"
              :class="{ active: selectedEdgeId === edge.id }"
              @click="selectGraphEdge(edge)"
            >
              <span class="edge-relation">{{ displayMode === 'cluster' ? `${edge.count} 条类型关系` : edge.label || edge.type }}</span>
              <span class="edge-node">{{ shortLabel(edgeEndpoint(edge, 'source'), 18) }}</span>
              <span class="edge-arrow">→</span>
              <span class="edge-node edge-node-target">{{ shortLabel(edgeEndpoint(edge, 'target'), 18) }}</span>
            </button>
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.kg-view {
  width: 100%;
  min-height: 0;
  overflow: auto;
  padding: 14px 20px 22px;
  background:
    radial-gradient(circle at 14% 4%, rgba(210, 154, 45, 0.22), transparent 26%),
    radial-gradient(circle at 92% 10%, rgba(63, 120, 184, 0.18), transparent 28%),
    linear-gradient(135deg, #eef3f0 0%, #dde9ee 45%, #f6efd9 100%);
  color: #172033;
}

.kg-hero {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(560px, 0.82fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 10px;
}

.kg-topbar {
  display: grid;
  gap: 8px;
}

.eyebrow {
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #7a5a16;
  font-weight: 900;
}

.kg-hero h2 {
  margin: 5px 0 6px;
  font-size: 28px;
  line-height: 1;
  color: #102033;
}

.kg-hero p {
  max-width: 780px;
  margin: 0;
  color: #536579;
  line-height: 1.45;
  font-size: 13px;
}

.kg-search {
  display: grid;
  grid-template-columns: 1fr 0.95fr 0.82fr 0.48fr auto;
  gap: 8px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(119, 139, 159, 0.28);
  border-radius: 16px;
  box-shadow: 0 10px 30px rgba(35, 61, 89, 0.1);
}

.kg-search label {
  display: grid;
  gap: 5px;
  font-size: 11px;
  color: #64748b;
  font-weight: 800;
}

.kg-search input,
.kg-search select {
  height: 34px;
  border: 1px solid #c7d3df;
  border-radius: 11px;
  padding: 0 10px;
  background: #fff;
  color: #102033;
  outline: none;
  font: inherit;
}

.kg-search button {
  align-self: end;
  height: 34px;
  border: none;
  border-radius: 11px;
  padding: 0 14px;
  background: #17314f;
  color: #fff7df;
  font-weight: 900;
  cursor: pointer;
}

.kg-search button:disabled {
  opacity: 0.65;
  cursor: wait;
}

.kg-stats {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: thin;
  padding-bottom: 8px;
}

.batch-bar {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) auto;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  padding: 9px 12px;
  border: 1px solid rgba(119, 139, 159, 0.22);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 12px 34px rgba(35, 61, 89, 0.09);
}

.batch-copy strong,
.batch-copy span {
  display: block;
}

.batch-copy strong {
  color: #17314f;
  font-size: 12px;
}

.batch-copy span {
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
}

.batch-actions {
  display: flex;
  align-items: stretch;
  gap: 10px;
  flex-shrink: 0;
}

.action-group {
  display: grid;
  grid-template-columns: auto auto;
  gap: 6px;
  align-items: center;
  padding: 6px;
  border: 1px solid rgba(119, 139, 159, 0.22);
  border-radius: 13px;
  background: rgba(246, 249, 253, 0.82);
}

.action-group > span {
  grid-column: 1 / -1;
  margin: 0 2px 1px;
  color: #64748b;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.action-group-wide {
  background: rgba(255, 250, 240, 0.86);
  border-color: rgba(164, 106, 24, 0.25);
}

.batch-actions button {
  height: 30px;
  border: 1px solid #c9d8ea;
  border-radius: 10px;
  padding: 0 11px;
  background: #17314f;
  color: #fff7df;
  font-weight: 900;
  cursor: pointer;
  white-space: nowrap;
}

.batch-actions button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.batch-actions .primary-sample {
  border-color: #a46a18;
  background: linear-gradient(135deg, #d28a22, #17314f);
  box-shadow: 0 10px 22px rgba(146, 89, 16, 0.22);
}

.stat-card {
  flex: 1 0 150px;
  min-width: 150px;
  padding: 9px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(119, 139, 159, 0.22);
  box-shadow: 0 10px 30px rgba(35, 61, 89, 0.08);
}

.stat-card span {
  display: block;
  font-size: 11px;
  color: #64748b;
  font-weight: 800;
}

.stat-card strong {
  display: block;
  margin-top: 3px;
  font-size: 20px;
  color: #14233a;
}

.stat-card-type strong {
  color: #9b5d13;
}

.error-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, #fff7ed, #fff1f2);
  color: #9f1239;
  border: 1px solid #fecdd3;
}

.error-box strong,
.error-box span {
  display: block;
}

.error-box span {
  margin-top: 4px;
  font-size: 13px;
  color: #be123c;
  word-break: break-word;
}

.error-box button {
  border: none;
  border-radius: 12px;
  padding: 9px 14px;
  background: #9f1239;
  color: #fff;
  font-weight: 900;
  cursor: pointer;
}

.kg-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: stretch;
}

.graph-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 620px;
  border-radius: 28px;
  box-shadow: 0 24px 70px rgba(15, 30, 50, 0.24);
  overflow: hidden;
  background: #0a1422;
  cursor: grab;
  user-select: none;
}

.graph-shell.dragging {
  cursor: grabbing;
}

.graph-toolbar {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid rgba(226, 232, 240, 0.16);
  border-radius: 16px;
  background: rgba(10, 20, 34, 0.72);
  backdrop-filter: blur(10px);
  color: #dbe7f5;
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.24);
}

.graph-toolbar button {
  height: 30px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  padding: 0 10px;
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.graph-toolbar button:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

.graph-toolbar button.active {
  border-color: rgba(255, 224, 138, 0.68);
  background: rgba(255, 224, 138, 0.18);
  color: #ffe08a;
}

.graph-toolbar label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 4px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.label-mode-control select {
  height: 30px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  padding: 0 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.label-mode-control select option {
  color: #102033;
}

.graph-toolbar span {
  min-width: 42px;
  color: #ffe08a;
  font-size: 12px;
  font-weight: 900;
}

.graph-breadcrumb {
  position: absolute;
  top: 62px;
  right: 16px;
  left: 16px;
  z-index: 4;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  justify-content: flex-start;
  padding: 7px 10px;
  border: 1px solid rgba(226, 232, 240, 0.16);
  border-radius: 14px;
  background: rgba(10, 20, 34, 0.72);
  backdrop-filter: blur(10px);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.24);
}

.crumb {
  max-width: 220px;
  padding: 4px 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #dbe7f5;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.crumb:hover:not(:disabled) {
  border-color: rgba(255, 224, 138, 0.5);
  color: #ffe08a;
}

.crumb.active,
.crumb:disabled {
  border-color: rgba(255, 224, 138, 0.68);
  background: rgba(255, 224, 138, 0.18);
  color: #ffe08a;
  cursor: default;
}

.crumb-sep {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 900;
}

.kg-svg {
  display: block;
  flex: 1;
  width: 100%;
  min-height: 620px;
  height: 100%;
  background: #0a1422;
  touch-action: none;
}

.graph-overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 12px;
  padding: 28px;
  background: radial-gradient(circle, rgba(20, 45, 76, 0.62), rgba(10, 20, 34, 0.82));
  color: #f8fafc;
  text-align: center;
}

.graph-overlay strong {
  font-size: 20px;
}

.graph-overlay span {
  max-width: 420px;
  color: #cad6e4;
  line-height: 1.6;
}

.graph-empty {
  background: radial-gradient(circle, rgba(34, 54, 82, 0.68), rgba(10, 20, 34, 0.9));
}

.pulse-orbit {
  width: 104px;
  height: 104px;
  border-radius: 50%;
  border: 2px solid rgba(255, 224, 138, 0.28);
  border-top-color: #ffe08a;
  box-shadow: inset 0 0 28px rgba(255, 224, 138, 0.14), 0 0 40px rgba(255, 224, 138, 0.18);
  animation: orbit-spin 1.1s linear infinite;
}

.node {
  cursor: pointer;
  transition: opacity 0.18s ease;
}

.node.dimmed {
  opacity: 0.24;
}

.node.selected circle:nth-child(2) {
  stroke: #ffe08a;
  stroke-width: 3;
}

.node-label-group {
  pointer-events: none;
}

.label-leader {
  stroke: rgba(186, 200, 216, 0.42);
  stroke-width: 1;
  stroke-linecap: round;
}

.label-bg {
  fill: rgba(8, 18, 32, 0.78);
  stroke: rgba(255, 255, 255, 0.14);
}

.node-label {
  fill: #f8fafc;
  font-size: 12px;
  font-weight: 800;
  pointer-events: none;
}

.node-label-compact {
  font-size: 10px;
  font-weight: 700;
  paint-order: stroke fill;
  stroke: rgba(8, 18, 32, 0.9);
  stroke-width: 3px;
  stroke-linejoin: round;
}

.node-type {
  fill: #bac8d8;
  font-size: 10px;
  pointer-events: none;
}

.cluster-count {
  fill: #0a1422;
  font-size: 18px;
  font-weight: 950;
  pointer-events: none;
}

.edge {
  cursor: pointer;
}

.kg-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  align-self: stretch;
}

.side-card {
  padding: 16px;
  border-radius: 22px;
  background: #ffffff;
  border: 1px solid #d7e2ef;
  box-shadow: 0 18px 45px rgba(35, 61, 89, 0.12);
  overflow: hidden;
  min-height: 0;
}

.focus-card {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  min-height: 220px;
  overflow: hidden;
}

.focus-card-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.edge-panel {
  flex: 1 1 0;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.edge-panel > .muted {
  flex: 1;
  min-height: 0;
}

.side-title {
  font-size: 13px;
  font-weight: 900;
  color: #7a5a16;
  margin-bottom: 10px;
  flex: 0 0 auto;
}

.focus-type {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 999px;
  background: #17314f;
  color: #fff7df;
  font-size: 12px;
  font-weight: 900;
}

.side-card h3 {
  margin: 10px 0;
  font-size: 17px;
  line-height: 1.45;
  color: #14233a;
}

.side-card dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.side-card dt {
  font-size: 12px;
  color: #718096;
  font-weight: 800;
}

.side-card dd {
  margin: -4px 0 0;
  color: #26374d;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}

.muted {
  color: #64748b;
  line-height: 1.65;
}

.side-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.side-title-row em {
  font-style: normal;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.edge-list {
  display: grid;
  gap: 10px;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 2px 6px 2px 2px;
  background: #ffffff;
  overscroll-behavior: contain;
}

.edge-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 7px 8px;
  align-items: center;
  width: 100%;
  padding: 12px;
  border: 1px solid #d7e2ef;
  border-radius: 16px;
  background: #ffffff;
  color: #1b3150;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 8px 22px rgba(31, 58, 95, 0.07);
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.edge-row:hover,
.edge-row.active {
  transform: translateY(-1px);
  border-color: #a98b38;
  box-shadow: 0 12px 28px rgba(124, 92, 22, 0.14);
  background: #fffdf7;
}

.edge-relation {
  grid-column: 1 / -1;
  justify-self: start;
  padding: 3px 8px;
  border-radius: 999px;
  background: #17314f;
  color: #fff7df;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.03em;
}

.edge-node {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #213757;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.edge-node-target {
  color: #755211;
  background: #fffaf0;
  border-color: #eadcb7;
}

.edge-arrow {
  color: #94a3b8;
  font-size: 16px;
  font-weight: 900;
}

@keyframes orbit-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1080px) {
  .kg-hero,
  .kg-main {
    grid-template-columns: 1fr;
  }

  .graph-shell {
    min-height: 520px;
  }

  .kg-svg {
    min-height: 520px;
  }

  .focus-card,
  .edge-panel {
    flex: 1 1 auto;
    min-height: 220px;
  }

  .edge-panel > .muted {
    flex: 1;
    min-height: 0;
  }

  .kg-search {
    grid-template-columns: 1fr 1fr;
  }

  .batch-bar {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .batch-actions {
    flex-wrap: wrap;
  }

  .action-group {
    flex: 1 1 260px;
  }
}

@media (max-width: 680px) {
  .kg-view {
    padding: 12px;
  }

  .kg-search {
    grid-template-columns: 1fr;
  }

  .kg-hero h2 {
    font-size: 28px;
  }
}
</style>
