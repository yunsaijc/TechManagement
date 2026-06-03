import reportData from './reportData.json';

function ringPoint(index, count, radiusX, radiusY, centerX, centerY, startAngle) {
  const angle = startAngle + (Math.PI * 2 * index) / Math.max(1, count);
  return {
    x: centerX + Math.cos(angle) * radiusX,
    y: centerY + Math.sin(angle) * radiusY,
  };
}

function getRun(year) {
  const scene = reportData?.scene || {};
  const yearRuns = scene.yearRuns || {};
  const activeYear = String(year || scene.activeYear || Object.keys(yearRuns)[0] || '');
  return yearRuns[activeYear] || {};
}

export function getScenarioGraphData(year, filterMode = 'all', showSpill = true, selectedTopicIds = []) {
  const run = getRun(year);
  const topics = (run.topics || []).filter(Boolean);
  const focusId = run.focusTopicId || topics[0]?.id || '';
  const topicMap = new Map(topics.map((item) => [item.id, item]));

  const selectedSet = new Set((selectedTopicIds || []).map((item) => String(item)));
  const hasSelection = selectedSet.size > 0;
  const visibleTopics = topics.filter((topic) => {
    if (hasSelection && !selectedSet.has(String(topic.id || ''))) return false;
    if (filterMode === 'direct' && !topic.direct) return false;
    if (!showSpill && !topic.direct) return false;
    return true;
  });
  const visibleSet = new Set(visibleTopics.map((item) => item.id));

  const visibleEdges = (run.edges || []).filter((edge) => {
    if (!visibleSet.has(edge.sourceId) || !visibleSet.has(edge.targetId)) return false;
    if (!showSpill && edge.kind === 'spill') return false;
    return true;
  });

  const centerX = 360;
  const centerY = 260;
  const maxMagnitude = Math.max(...topics.map((item) => Number(item.maxAbs || 0)), 1);
  const positions = new Map();
  const focusTopic = topicMap.get(focusId) || visibleTopics[0];
  if (focusTopic && visibleSet.has(focusTopic.id)) {
    positions.set(focusTopic.id, { x: centerX, y: centerY, r: 36 });
  }
  const directNodes = visibleTopics.filter((item) => item.direct && item.id !== focusTopic?.id);
  const spillNodes = visibleTopics.filter((item) => !item.direct && item.id !== focusTopic?.id);

  directNodes.forEach((topic, index) => {
    const point = ringPoint(index, directNodes.length, 220, 135, centerX, centerY, -Math.PI / 2);
    positions.set(topic.id, { x: point.x, y: point.y, r: 18 + (Number(topic.maxAbs || 0) / maxMagnitude) * 12 });
  });
  spillNodes.forEach((topic, index) => {
    const point = ringPoint(index, spillNodes.length, 310, 205, centerX, centerY, -Math.PI / 3);
    positions.set(topic.id, { x: point.x, y: point.y, r: 17 + (Number(topic.maxAbs || 0) / maxMagnitude) * 8 });
  });

  return {
    run,
    visibleTopics,
    visibleEdges,
    positions,
    topicMap,
    focusId: focusTopic?.id || '',
  };
}
