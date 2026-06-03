import reportData from './reportData.json';

function runRoleLabel(run) {
  const role = String((run || {}).role || '');
  if (role === 'current') return '当前推演';
  if (role === 'backtest') return '历史回测';
  if (role === 'future') return '未来延伸';
  return '对照批次';
}

function plainNumber(value, digits = 0) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return '0';
  return numeric.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedNumber(value, digits = 0) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return '+0';
  const sign = numeric >= 0 ? '+' : '';
  return `${sign}${numeric.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function topicBacktest(topic) {
  const backtest = (topic || {}).backtest || null;
  if (!backtest || typeof backtest !== 'object') return null;
  const predicted = backtest.predicted || null;
  const actual = backtest.actual || null;
  const error = backtest.error || null;
  if (!predicted || !actual || !error) return null;
  return backtest;
}

function metricValue(topic, key) {
  return Number(((topic || {}).metrics || {})[key] || 0);
}

function runRows(topics) {
  return (topics || []).map((topic) => {
    const backtest = topicBacktest(topic);
    if (backtest) {
      const predicted = backtest.predicted || {};
      const actual = backtest.actual || {};
      const error = backtest.error || {};
      const majorDelta = Math.max(
        Math.abs(Number(error.application || 0)),
        Math.abs(Number(error.funded || 0)) * 4,
        Math.abs(Number(error.funding || 0)) / 20,
      );
      return {
        majorDelta,
        deltaApplication: Number(error.application || 0),
        deltaFunded: Number(error.funded || 0),
        deltaFunding: Number(error.funding || 0),
        predictedApplication: Number(predicted.application || 0),
        predictedFunded: Number(predicted.funded || 0),
        predictedFunding: Number(predicted.funding || 0),
        actualApplication: Number(actual.application || 0),
        actualFunded: Number(actual.funded || 0),
        actualFunding: Number(actual.funding || 0),
      };
    }
    const deltaApplication = metricValue(topic, 'deltaApplication');
    const deltaFunded = metricValue(topic, 'deltaFunded');
    const deltaFunding = metricValue(topic, 'deltaFunding');
    return {
      majorDelta: Math.max(Math.abs(deltaFunding), Math.abs(deltaFunded), Math.abs(deltaApplication)),
      deltaApplication,
      deltaFunded,
      deltaFunding,
    };
  });
}

function applyTopicFilters(rows, selectedTopicIds = [], searchKeyword = '') {
  const selectedSet = new Set((selectedTopicIds || []).map((item) => String(item)));
  const hasSelection = selectedSet.size > 0;
  const keyword = String(searchKeyword || '').trim().toLowerCase();
  return (rows || []).filter((row) => {
    if (hasSelection && !selectedSet.has(String(row.topicId || ''))) return false;
    if (keyword) {
      const text = String(row.fullLabel || '').toLowerCase();
      if (!text.includes(keyword)) return false;
    }
    return true;
  });
}

export function getScenarioMetricCards(year, selectedTopicIds = [], searchKeyword = '') {
  const scene = reportData?.scene || {};
  const yearRuns = scene.yearRuns || {};
  const activeYear = String(year || scene.activeYear || Object.keys(yearRuns)[0] || '');
  const run = yearRuns[activeYear] || {};
  const rows = applyTopicFilters(getScenarioRunRows(year), selectedTopicIds, searchKeyword);
  const sum = (key) => rows.reduce((total, row) => total + Number(row[key] || 0), 0);
  const changedCount = rows.filter((row) => row.majorDelta > 1e-9).length;
  const isBacktestRun = String(run.role || '') === 'backtest';

  if (isBacktestRun) {
    return [
      { label: '当前批次', value: run.year || activeYear || '-', delta: runRoleLabel(run), cls: 'neutral' },
      { label: '研究方向', value: String(changedCount), delta: '有变化对象', cls: 'neutral' },
      {
        label: '申报变化',
        value: plainNumber(sum('predictedApplication'), 0),
        delta: `与真实值偏差 ${signedNumber(sum('deltaApplication'), 0)} 项`,
        cls: 'warn',
      },
      {
        label: '立项变化',
        value: plainNumber(sum('predictedFunded'), 0),
        delta: `与真实值偏差 ${signedNumber(sum('deltaFunded'), 0)} 项`,
        cls: 'warn',
      },
      {
        label: '经费变化',
        value: plainNumber(sum('predictedFunding'), 1),
        delta: `与真实值偏差 ${signedNumber(sum('deltaFunding'), 1)} 万元`,
        cls: 'warn',
      },
    ];
  }

  return [
    { label: '当前批次', value: run.year || activeYear || '-', delta: runRoleLabel(run), cls: 'neutral' },
    { label: '研究方向', value: String(changedCount), delta: '有变化对象', cls: 'neutral' },
    {
      label: '申报变化',
      value: signedNumber(sum('deltaApplication'), 0),
      delta: '项目数',
      cls: sum('deltaApplication') < 0 ? 'down' : 'up',
    },
    {
      label: '立项变化',
      value: signedNumber(sum('deltaFunded'), 0),
      delta: '项目数',
      cls: sum('deltaFunded') < 0 ? 'down' : 'up',
    },
    {
      label: '经费变化',
      value: signedNumber(sum('deltaFunding'), 1),
      delta: '万元',
      cls: sum('deltaFunding') < 0 ? 'down' : 'up',
    },
  ];
}

export function getScenarioRunRows(year) {
  const scene = reportData?.scene || {};
  const yearRuns = scene.yearRuns || {};
  const activeYear = String(year || scene.activeYear || Object.keys(yearRuns)[0] || '');
  const run = yearRuns[activeYear] || {};
  const rows = runRows(run.topics || []);
  const topics = run.topics || [];

  return rows.map((row, index) => {
    const topic = topics[index] || {};
    return {
      ...row,
      topicId: String(topic.id || ''),
      fullLabel: topic.label || topic.shortLabel || '未标注主题',
      direct: Boolean(topic.direct),
      isBacktestRun: String(run.role || '') === 'backtest',
    };
  });
}

export function getScenarioFilteredRunRows(year, selectedTopicIds = [], searchKeyword = '') {
  return applyTopicFilters(getScenarioRunRows(year), selectedTopicIds, searchKeyword);
}
