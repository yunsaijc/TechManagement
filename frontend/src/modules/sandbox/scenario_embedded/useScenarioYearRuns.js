import reportData from './reportData.json';

export function useScenarioYearRuns() {
  const scene = reportData?.scene || {};
  const yearRuns = scene.yearRuns || {};
  const runOrder = (scene.runOrder || Object.keys(yearRuns)).filter((year) => yearRuns[year]);
  const activeYear = String(scene.activeYear || runOrder[0] || '');
  const yearOptions = runOrder.map((year) => ({
    year: String(year),
    label: String(yearRuns[year]?.label || year),
  }));

  return {
    activeYear,
    yearOptions,
  };
}

export function getScenarioTopicOptions(year) {
  const scene = reportData?.scene || {};
  const yearRuns = scene.yearRuns || {};
  const activeYear = String(year || scene.activeYear || Object.keys(yearRuns)[0] || '');
  const run = yearRuns[activeYear] || {};
  return (run.topics || []).map((topic) => ({
    id: String(topic.id || ''),
    label: String(topic.shortLabel || topic.label || '未标注主题'),
  })).filter((item) => item.id);
}
