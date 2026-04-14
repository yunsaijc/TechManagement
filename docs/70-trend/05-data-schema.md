# 趋势预判数据 Schema

## 一、目标

趋势预判层需要的不只是原始表，而是一组可稳定复用的分析层数据结构。

第一版建议固定为三类：

1. `panel table`
2. `graph-derived table`
3. `feature table`

## 二、Panel Table

### 1. 主表定义

主表建议命名为：

- `topic_time_panel`

主键建议为：

- `topic_id`
- `time_window`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | string | 主题唯一标识 |
| `topic_name` | string | 主题名称 |
| `topic_type` | string | 主题类型 |
| `time_window` | string | 时间窗标识，如 `2025Q4` / `2025Y` |
| `application_count` | float | 申报数量 |
| `funded_count` | float | 立项数量 |
| `funding_amount` | float | 资助金额 |
| `project_active_count` | float | 在研项目数 |
| `talent_headcount` | float | 人才规模 |
| `talent_senior_ratio` | float | 高层次人才占比 |
| `talent_backbone_ratio` | float | 中坚骨干占比 |
| `output_count` | float | 产出数量 |
| `high_value_output_count` | float | 高价值产出数量 |
| `acceptance_rate` | float | 验收通过率 |
| `conversion_rate` | float | 转化率 |
| `conversion_lag` | float | 转化时滞 |

### 2. 时间窗要求

第一版必须统一时间窗编码规则，避免模型训练时出现错位：

- 年度：`YYYY`
- 季度：`YYYYQn`

不允许同一张表混用自然年、申报周期和验收周期而不做显式映射。

## 三、Graph-Derived Table

图谱相关信息不建议直接在运行时重复计算，建议落成派生表。

### 1. topic_graph_metrics

主键：

- `topic_id`
- `time_window`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | string | 主题标识 |
| `time_window` | string | 时间窗 |
| `topic_centrality` | float | 中心性 |
| `community_id` | string | 所属社区 |
| `community_size` | float | 社区规模 |
| `inflow_strength` | float | 流入强度 |
| `outflow_strength` | float | 流出强度 |
| `cross_topic_mobility` | float | 跨主题流动强度 |
| `embedding_shift` | float | 嵌入漂移强度 |

### 2. topic_migration_edges

主键建议：

- `source_topic_id`
- `target_topic_id`
- `from_window`
- `to_window`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_topic_id` | string | 来源主题 |
| `target_topic_id` | string | 目标主题 |
| `from_window` | string | 起始时间窗 |
| `to_window` | string | 目标时间窗 |
| `project_flow` | float | 项目流量 |
| `talent_flow` | float | 人才流量 |
| `semantic_shift_score` | float | 语义漂移强度 |
| `migration_strength` | float | 综合迁移强度 |

## 四、Feature Table

模型训练不应直接使用原始 panel，需要显式生成特征表。

### 1. trend_feature_table

主键建议：

- `topic_id`
- `anchor_window`

建议字段分为 4 组：

1. 当前水平特征
2. 环比/同比变化特征
3. 图结构特征
4. 滞后特征

示例字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `application_count_t` | float | 当前申报数 |
| `application_growth_qoq` | float | 环比增长 |
| `funded_growth_yoy` | float | 同比增长 |
| `conversion_rate_t` | float | 当前转化率 |
| `conversion_rate_delta` | float | 转化率变化 |
| `topic_centrality_t` | float | 当前中心性 |
| `embedding_shift_t` | float | 当前漂移 |
| `talent_senior_ratio_t` | float | 当前人才结构 |
| `collaboration_density_t` | float | 当前协作密度 |
| `output_count_lag1` | float | 上一窗口产出 |

## 五、标签表

如果要做监督预测，还需要显式标签表。

### 1. trend_label_table

主键建议：

- `topic_id`
- `anchor_window`
- `target_window`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `future_application_count` | float | 未来窗口申报数 |
| `future_conversion_rate` | float | 未来窗口转化率 |
| `future_risk_score` | float | 未来窗口风险分 |
| `future_state_label` | string | 未来生命周期状态 |

## 六、第一版建议

第一版先落地以下三张表即可：

1. `topic_time_panel`
2. `topic_graph_metrics`
3. `trend_feature_table`

这三张表一旦稳定，后续的迁移检测、风险预测和生命周期预测都可以在同一数据底座上推进。
