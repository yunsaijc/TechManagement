# 趋势预判数据 Schema

## 一、目标

趋势预判层不再预设一堆训练表和标签表，而是先建立两张能够稳定支撑分析的核心结构：

1. `topic_time_panel`
2. `topic_migration_edges`

这两张表足够支撑 snapshot、signals、migration 和 ranking。

## 二、核心表一：topic_time_panel

### 1. 主表定义

主表命名：

- `topic_time_panel`

主键：

- `topic_id`
- `year`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | string | 主题唯一标识 |
| `topic_name` | string | 主题名称 |
| `topic_type` | string | 主题口径类型 |
| `topic_source` | string | 主题来源口径 |
| `year` | int | 自然年 |
| `application_count` | float | 申报数量 |
| `funded_count` | float | 立项数量 |
| `funding_amount` | float | 资助金额 |
| `score_proxy` | float | 评审强度代理值 |
| `collaboration_density` | float | 协作密度 |
| `topic_centrality` | float | 主题中心性 |
| `migration_strength` | float | 主题迁移强度 |
| `data_quality_flags` | array/string | 数据质量标记 |

### 2. 角色

`topic_time_panel` 是趋势预判的分析底座，承担 3 个角色：

1. 当前状态快照
2. 同比变化计算基础
3. 排序与信号提取基础

## 三、核心表二：topic_migration_edges

### 1. 边表定义

边表命名：

- `topic_migration_edges`

主键建议：

- `source_topic_id`
- `target_topic_id`
- `from_year`
- `to_year`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_topic_id` | string | 来源主题 |
| `target_topic_id` | string | 目标主题 |
| `from_year` | int | 起始年份 |
| `to_year` | int | 目标年份 |
| `flow_strength` | float | 迁移流强度 |
| `evidence_count` | int | 支撑该边的证据量 |
| `data_quality_flags` | array/string | 数据质量标记 |

### 2. 角色

`topic_migration_edges` 只做一件事：

表达热点迁移网络，而不是承载所有图计算结果。

## 四、派生结果结构

趋势预判的派生结果不必先落为复杂训练表，但应有统一输出合同。

### 1. signal record

建议字段：

- `topic_id`
- `year`
- `signal_type`
- `metric_basis`
- `direction`
- `strength`
- `evidence`

### 2. ranking record

建议字段：

- `topic_id`
- `year`
- `ranking_type`
- `score`
- `basis`

## 五、设计原则

1. 先把可解释的状态表做实，再谈更复杂的预测
2. 只保留当前数据源能稳定支撑的核心字段
3. 所有缺失和口径问题都必须外显到 `data_quality_flags`
