# 70 实施顺序

## 一、目标

本文件用于把前面的概念定义、变量清单和 schema 落成真正的实施顺序，避免开发重新回到“先写接口、后补模型”的路径。

## 二、建议顺序

### Phase 1：统一数据底座

先完成以下内容：

1. 建立 `topic_time_panel`
2. 建立 `topic_graph_metrics`
3. 建立 `baseline_snapshot`

这一阶段的目标不是做预测，而是把所有后续模块共用的数据底座固定下来。

### Phase 2：搭建 Trend Engine

在 `trend` 层先做三类能力：

1. 热点迁移检测
2. 风险特征抽取
3. 基线预测

对应输入：

- `topic_time_panel`
- `topic_graph_metrics`
- `trend_feature_table`

对应输出：

- `snapshot`
- `signals`
- `forecasts`
- `risks`

### Phase 3：搭建 Simulation Engine

在 `simulation` 层先做三类能力：

1. 场景装配
2. 政策动作施加
3. 基线与反事实对比

对应输入：

- `baseline_snapshot`
- `policy_instrument`
- `scenario_definition`

对应输出：

- `counterfactual`
- `impact_assessment`
- `causal_paths`

### Phase 4：交付层

最后才接：

1. 简报
2. 对比报告
3. 问答

这些能力必须消费 `trend` 和 `simulation` 的结果，不得绕开分析层直接生成结论。

## 三、代码模块建议

建议未来代码模块按以下方式对应：

### 1. Feature / State Layer

- `state_builder`
- `feature_store`
- `graph_feature_builder`

### 2. Trend Layer

- `migration_detector`
- `risk_model`
- `baseline_forecaster`

### 3. Simulation Layer

- `scenario_service`
- `policy_translator`
- `counterfactual_engine`
- `impact_comparator`

### 4. Delivery Layer

- `briefing_service`
- `report_service`
- `qa_service`

## 四、第一版可开工清单

如果只做第一版 MVP，建议按下面顺序开工：

1. 定义 `topic_time_panel`
2. 定义 `baseline_snapshot`
3. 抽取热点迁移和图特征
4. 训练第一版风险 / baseline 预测模型
5. 实现 3 类政策动作
6. 实现第一版反事实比较

## 五、停损原则

如果某一步出现以下情况，应立即收缩范围：

1. 主题口径无法统一
2. 时间窗对不齐
3. 转化数据无法稳定关联
4. 政策动作无法参数化

这四种情况下，继续堆模型只会把系统重新推回 toy。
