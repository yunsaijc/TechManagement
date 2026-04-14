# 趋势预判对象与指标

## 一、核心对象

趋势预判不再铺开很多抽象对象，而是围绕 5 个核心对象组织：

- `Topic`
- `TopicYearState`
- `MigrationEdge`
- `TrendSignal`
- `TrendRanking`

## 二、对象说明

### 1. Topic

趋势预判中的主题口径固定为“指南方向优先”。

第一顺位使用项目库中的 `zndm / guide name`；
只有在无法映射时，才允许回退到 `zxmc`，并且必须显式标记口径来源。

关键属性：

- `topic_id`
- `topic_name`
- `topic_type`
- `topic_source`

### 2. TopicYearState

`TopicYearState` 是趋势预判的核心状态单元，对应一行 `topic × year`。

关键属性：

- `topic_id`
- `year`
- `application_count`
- `funded_count`
- `funding_amount`
- `score_proxy`
- `collaboration_density`
- `topic_centrality`
- `migration_strength`
- `data_quality_flags`

### 3. MigrationEdge

`MigrationEdge` 用于表达主题之间的迁移关系，而不是静态属性。

关键属性：

- `source_topic_id`
- `target_topic_id`
- `from_year`
- `to_year`
- `flow_strength`
- `evidence_count`

### 4. TrendSignal

`TrendSignal` 用于表达“已经发生的变化”。

关键属性：

- `topic_id`
- `signal_type`
- `window`
- `metric_basis`
- `direction`
- `strength`
- `evidence`

### 5. TrendRanking

`TrendRanking` 用于表达需要被关注的主题排序。

关键属性：

- `topic_id`
- `ranking_type`
- `score`
- `basis`
- `window`

## 三、指标层

趋势预判建议只保留三类指标：

1. 状态指标
2. 变化指标
3. 排序指标

### 1. 状态指标

- `application_count`
- `funded_count`
- `funding_amount`
- `score_proxy`
- `collaboration_density`
- `topic_centrality`
- `migration_strength`

### 2. 变化指标

- 同比变化
- 增速变化
- 结构变化
- 排名变化

### 3. 排序指标

- 升温排序
- 降温排序
- 风险排序
- 迁移活跃排序

## 四、时间设计

趋势预判统一使用自然年作为时间窗：

- `year`
- `previous_year`
- `comparison_window`

后续如需季度分析，应建立单独口径，不与年度结果混用。
