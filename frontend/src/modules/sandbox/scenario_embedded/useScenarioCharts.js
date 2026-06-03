import { getScenarioFilteredRunRows } from './useScenarioMetrics';

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function plainNumber(value, digits = 0) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return '0';
  return numeric.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function axisNumber(value, maxValue) {
  const max = Math.abs(Number(maxValue || 0));
  const digits = max < 2 ? 2 : max < 20 ? 1 : 0;
  return plainNumber(value, digits);
}

function chartAxisLabel(value, maxChars) {
  const text = String(value || '');
  return text.length > maxChars ? `${text.slice(0, Math.max(1, maxChars - 1))}...` : text;
}

function svgEmpty(message) {
  return `<svg class="chart-frame" viewBox="0 0 360 220"><text x="20" y="28" fill="#98a2b3" font-size="12">${escapeHtml(message)}</text></svg>`;
}

function barChartSvg(rows, metricKey, baselineKey) {
  const chartRows = rows
    .filter((row) => Math.abs(Number(row[metricKey] || 0)) > 1e-9)
    .sort((a, b) => Math.abs(Number(b[metricKey] || 0)) - Math.abs(Number(a[metricKey] || 0)))
    .slice(0, 10);
  if (!chartRows.length) return svgEmpty('当前筛选下没有变化项。');
  const values = [];
  chartRows.forEach((row) => {
    const baseline = Math.max(Number(row[baselineKey] || 0), 0);
    const scenario = Math.max(baseline + Number(row[metricKey] || 0), 0);
    values.push(baseline, scenario);
  });
  const maxValue = Math.max(...values, 1);
  const chartWidth = 360;
  const left = 42;
  const bottom = 158;
  const usableHeight = 128;
  const groupWidth = (chartWidth - left - 16) / chartRows.length;
  const barWidth = Math.max(8, (groupWidth - 8) / 2);
  const grid = [];
  const labels = [];
  const bars = [];
  for (let step = 0; step < 5; step += 1) {
    const y = bottom - (usableHeight * step) / 4;
    const value = (maxValue * step) / 4;
    grid.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${chartWidth - 10}" y2="${y.toFixed(1)}" stroke="#edf2f8" stroke-width="1"/>`);
    labels.push(`<text x="${left - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#98a2b3" font-size="11">${Math.round(value)}</text>`);
  }
  chartRows.forEach((row, index) => {
    const baseline = Math.max(Number(row[baselineKey] || 0), 0);
    const scenario = Math.max(baseline + Number(row[metricKey] || 0), 0);
    const groupX = left + index * groupWidth + 4;
    const baselineH = (usableHeight * baseline) / maxValue;
    const scenarioH = (usableHeight * scenario) / maxValue;
    bars.push(`<rect x="${groupX.toFixed(1)}" y="${(bottom - baselineH).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${baselineH.toFixed(1)}" rx="4" fill="#d9e2f1"/>`);
    bars.push(`<rect x="${(groupX + barWidth + 4).toFixed(1)}" y="${(bottom - scenarioH).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${scenarioH.toFixed(1)}" rx="4" fill="#3f7cff"/>`);
    const labelX = groupX + barWidth;
    labels.push(`<text x="${labelX.toFixed(1)}" y="${(bottom + 18).toFixed(1)}" text-anchor="end" transform="rotate(-38 ${labelX.toFixed(1)} ${(bottom + 18).toFixed(1)})" fill="#7a8699" font-size="11">${escapeHtml(chartAxisLabel(row.fullLabel, 12))}</text>`);
  });
  return `<svg class="chart-frame" viewBox="0 0 360 270" role="img" aria-label="批次对比柱状图">${grid.join('')}${bars.join('')}${labels.join('')}</svg>`;
}

function bubbleChartSvg(rows) {
  const chartRows = rows
    .filter((row) => Math.abs(Number(row.deltaFunding || 0)) > 1e-9)
    .sort((a, b) => Math.abs(Number(b.deltaFunding || 0)) - Math.abs(Number(a.deltaFunding || 0)))
    .slice(0, 8);
  if (!chartRows.length) return svgEmpty('当前批次没有经费变化。');
  const maxX = Math.max(...chartRows.map((row) => Number(row.baselineFunding || 0)), 1);
  const maxY = Math.max(...chartRows.map((row) => Number(row.baselineFunding || 0) + Number(row.deltaFunding || 0)), 1);
  const maxR = Math.max(...chartRows.map((row) => Math.abs(Number(row.deltaFunding || 0))), 1);
  const minX = Math.min(0, ...chartRows.map((row) => Number(row.baselineFunding || 0)));
  const minY = Math.min(0, ...chartRows.map((row) => Number(row.baselineFunding || 0) + Number(row.deltaFunding || 0)));
  const xSpan = Math.max(0.0001, maxX - minX);
  const ySpan = Math.max(0.0001, maxY - minY);
  const palette = ['#7aa5ff', '#69d2a6', '#ffb454', '#b18cff', '#ff8d7a', '#91d5ff', '#9be29b', '#ffd166'];
  const grid = [];
  const axes = [];
  const points = [];
  const legends = [];
  const left = 56;
  const right = 272;
  const top = 30;
  const bottom = 184;
  const width = right - left;
  const height = bottom - top;
  for (let step = 0; step < 5; step += 1) {
    const x = left + (width * step) / 4;
    const y = bottom - (height * step) / 4;
    const xValue = minX + (xSpan * step) / 4;
    const yValue = minY + (ySpan * step) / 4;
    grid.push(`<line x1="${x.toFixed(1)}" y1="${top}" x2="${x.toFixed(1)}" y2="${bottom}" stroke="#edf2f8"/>`);
    grid.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" stroke="#edf2f8"/>`);
    axes.push(`<text x="${x.toFixed(1)}" y="${bottom + 18}" text-anchor="middle" fill="#98a2b3" font-size="10">${axisNumber(xValue, maxX)}</text>`);
    axes.push(`<text x="${left - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#98a2b3" font-size="10">${axisNumber(yValue, maxY)}</text>`);
  }
  axes.push(`<line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}" stroke="#cad5e3" stroke-width="1.2"/>`);
  axes.push(`<line x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" stroke="#cad5e3" stroke-width="1.2"/>`);
  chartRows.forEach((row, index) => {
    const color = palette[index % palette.length];
    const x = left + (width * (Number(row.baselineFunding || 0) - minX)) / xSpan;
    const y = bottom - (height * ((Number(row.baselineFunding || 0) + Number(row.deltaFunding || 0)) - minY)) / ySpan;
    const sizeRatio = Math.abs(Number(row.deltaFunding || 0)) / maxR;
    const r = 7 + 15 * Math.sqrt(sizeRatio);
    points.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" fill-opacity="0.55" stroke="${color}" stroke-opacity="0.95" stroke-width="1.4"/>`);
    points.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.8" fill="#0f172a" fill-opacity="0.45"/>`);
    legends.push(`<text x="292" y="${28 + index * 18}" fill="#667085" font-size="11">${escapeHtml(chartAxisLabel(row.fullLabel, 16))}</text><circle cx="280" cy="${24 + index * 18}" r="4.5" fill="${color}" fill-opacity="0.85"/>`);
  });
  return `<svg class="chart-frame" viewBox="0 0 360 220" role="img" aria-label="批次经费气泡图"><text x="18" y="20" fill="#667085" font-size="11">调整后经费（万元）</text><text x="176" y="216" fill="#667085" font-size="11">基线经费（万元）</text>${grid.join('')}${axes.join('')}${points.join('')}${legends.join('')}</svg>`;
}

export function getScenarioChartPayload(year, selectedTopicIds = [], searchKeyword = '') {
  const rows = getScenarioFilteredRunRows(year, selectedTopicIds, searchKeyword);
  return {
    applicationTitle: '申报项目数变化 TOP10（个）',
    fundedTitle: '立项项目数变化 TOP10（个）',
    fundingTitle: '经费变化 TOP10（万元）',
    applicationSvg: barChartSvg(rows, 'deltaApplication', 'baselineApplication'),
    fundedSvg: barChartSvg(rows, 'deltaFunded', 'baselineFunded'),
    fundingSvg: bubbleChartSvg(rows),
  };
}
