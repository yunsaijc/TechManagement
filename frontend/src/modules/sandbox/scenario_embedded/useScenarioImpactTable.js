import { getScenarioFilteredRunRows } from './useScenarioMetrics';

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

export function getScenarioImpactRows(year, selectedTopicIds = [], searchKeyword = '') {
  const rows = getScenarioFilteredRunRows(year, selectedTopicIds, searchKeyword);
  const tableRows = rows
    .filter((row) => row.majorDelta > 1e-9)
    .sort((a, b) => Number(b.majorDelta || 0) - Number(a.majorDelta || 0))
    .slice(0, 8);

  return tableRows.map((row) => {
    const deltaParts = [];
    if (row.isBacktestRun) {
      if (Math.abs(row.deltaFunding) > 1e-9) deltaParts.push(`经费 ${plainNumber(row.predictedFunding, 1)}，与真实值偏差 ${signedNumber(row.deltaFunding, 1)}`);
      if (Math.abs(row.deltaFunded) > 1e-9) deltaParts.push(`立项 ${plainNumber(row.predictedFunded, 0)}，与真实值偏差 ${signedNumber(row.deltaFunded, 0)}`);
      if (Math.abs(row.deltaApplication) > 1e-9) deltaParts.push(`申报 ${plainNumber(row.predictedApplication, 0)}，与真实值偏差 ${signedNumber(row.deltaApplication, 0)}`);
    } else {
      if (Math.abs(row.deltaFunding) > 1e-9) deltaParts.push(`经费 ${signedNumber(row.deltaFunding, 1)}`);
      if (Math.abs(row.deltaFunded) > 1e-9) deltaParts.push(`立项 ${signedNumber(row.deltaFunded, 0)}`);
      if (Math.abs(row.deltaApplication) > 1e-9) deltaParts.push(`申报 ${signedNumber(row.deltaApplication, 0)}`);
    }

    return {
      impactClass: row.direct ? 'direct' : 'spill',
      impactType: row.direct ? '直接影响' : '外溢影响',
      fullLabel: row.fullLabel,
      changeText: deltaParts.join('，') || '无明显变化',
      baselineText: `申报 ${plainNumber(row.baselineApplication, 0)}｜立项 ${plainNumber(row.baselineFunded, 0)}｜经费 ${plainNumber(row.baselineFunding, 1)}`,
    };
  });
}
