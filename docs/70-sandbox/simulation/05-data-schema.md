# 沙盘推演数据 Schema

## 一、目标

沙盘推演层需要的不是单次请求参数，而是一套可审计、可复算、可比较的场景数据结构。

第一版建议固定为四类：

1. `baseline snapshot`
2. `policy instrument`
3. `scenario definition`
4. `simulation result`

## 二、Baseline Snapshot

### 1. baseline_snapshot

该表用于保存某一时间点被沙盘推演引用的基线状态。

主键建议：

- `baseline_id`
- `topic_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `baseline_id` | string | 基线版本标识 |
| `topic_id` | string | 主题标识 |
| `time_window` | string | 基线所属时间窗 |
| `application_count` | float | 基线申报数 |
| `funded_count` | float | 基线立项数 |
| `funding_amount` | float | 基线资助额 |
| `talent_headcount` | float | 基线人才规模 |
| `talent_quality_index` | float | 基线人才质量 |
| `collaboration_strength_index` | float | 基线协作强度 |
| `output_efficiency` | float | 基线产出效率 |
| `conversion_rate` | float | 基线转化率 |
| `risk_score` | float | 基线风险得分 |

## 三、Policy Instrument

### 1. policy_instrument

主键建议：

- `instrument_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `instrument_id` | string | 动作标识 |
| `instrument_type` | string | 动作类型 |
| `target_scope_json` | json | 作用对象 |
| `parameters_json` | json | 动作参数 |
| `effective_window_json` | json | 生效窗口 |
| `constraints_json` | json | 约束条件 |
| `assumptions_json` | json | 结构假设 |

## 四、Scenario Definition

### 1. scenario_definition

主键建议：

- `scenario_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `scenario_id` | string | 场景标识 |
| `baseline_id` | string | 关联基线 |
| `scenario_name` | string | 场景名称 |
| `objective_json` | json | 目标函数或优化目标 |
| `constraints_json` | json | 全局约束 |
| `evaluation_targets_json` | json | 评估重点 |
| `created_by` | string | 创建者 |
| `created_at` | datetime | 创建时间 |

### 2. scenario_instruments

该表用于表达一个场景包含多个政策动作。

主键建议：

- `scenario_id`
- `instrument_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `scenario_id` | string | 场景标识 |
| `instrument_id` | string | 动作标识 |
| `priority_order` | int | 执行顺序 |
| `enabled` | bool | 是否启用 |

## 五、Simulation Result

### 1. simulation_run

主键建议：

- `run_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `scenario_id` | string | 场景标识 |
| `baseline_id` | string | 基线标识 |
| `engine_version` | string | 仿真引擎版本 |
| `status` | string | 运行状态 |
| `started_at` | datetime | 开始时间 |
| `finished_at` | datetime | 结束时间 |

### 2. simulation_topic_result

主键建议：

- `run_id`
- `topic_id`
- `forecast_window`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `topic_id` | string | 主题标识 |
| `forecast_window` | string | 推演窗口 |
| `baseline_topic_share` | float | 基线占比 |
| `counterfactual_topic_share` | float | 反事实占比 |
| `baseline_conversion_rate` | float | 基线转化率 |
| `counterfactual_conversion_rate` | float | 反事实转化率 |
| `baseline_risk_score` | float | 基线风险 |
| `counterfactual_risk_score` | float | 反事实风险 |
| `delta_output_efficiency` | float | 产出效率变化 |
| `delta_talent_quality_index` | float | 人才质量变化 |

### 3. simulation_explanation

主键建议：

- `run_id`
- `topic_id`
- `path_id`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `topic_id` | string | 主题标识 |
| `path_id` | string | 路径标识 |
| `path_type` | string | 因果路径类型 |
| `weight` | float | 路径贡献强度 |
| `evidence_json` | json | 证据与假设 |

## 六、请求 Payload 建议

推演 API 的请求体建议直接围绕 `scenario_definition` 组织，而不是裸传一堆临时字段。

最小请求体建议：

```json
{
  "baseline_id": "baseline_2026q1",
  "scenario_name": "priority_shift_a",
  "instruments": [],
  "constraints": {},
  "evaluation_targets": []
}
```

## 七、第一版建议

第一版先落地以下四张表即可：

1. `baseline_snapshot`
2. `policy_instrument`
3. `scenario_definition`
4. `simulation_topic_result`

有了这四张表，场景创建、运行记录和结果对比就都能稳定沉淀下来。
