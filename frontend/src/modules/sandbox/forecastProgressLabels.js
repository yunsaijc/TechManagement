/** 与后端 orchestrator / job 状态对齐的简短中文阶段名 */
export const FORECAST_STEP_LABELS = {
  queue: '排队',
  queued: '排队',
  init: '初始化',
  step1_preflight: 'Step1 图预检',
  parallel_phase1: '并行：热点 / 宏观 / GraphRAG',
  step2_hotspot: '热点迁移（Step2）',
  step3_insight: '宏观洞察（Step3）',
  parallel_step4_step5: '并行：简报 + GraphRAG',
  step4_briefing: '领导简报（Step4）',
  step5_graphrag: 'GraphRAG 生成（Step5）',
  assemble: '组装报告',
  done: '完成',
  error: '出错',
};

export function forecastStepLabel(step) {
  const s = String(step || '');
  return FORECAST_STEP_LABELS[s] || (s ? s : '进行中');
}
