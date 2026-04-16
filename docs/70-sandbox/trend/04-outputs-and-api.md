# 趋势预判输出与接口

## 一、输出目标

趋势模块的输出不是单个榜单，也不是单张热点迁移图。

领导视角下，完整输出必须同时覆盖四件事：

1. 看现在
2. 看变化
3. 看未来
4. 看风险

并且每类输出都要携带证据边界。

## 二、领导视角的标准输出合同

建议趋势模块统一输出如下结构：

```json
{
  "meta": {},
  "current_state": {},
  "change_view": {},
  "baseline_forecast": {},
  "risk_view": {},
  "evidence": {},
  "limitations": {}
}
```

### 1. `meta`

描述本次趋势分析的口径与边界。

至少包含：

- `time_window`
- `topic_scope`
- `portfolio_scope`
- `data_sources`
- `topic_mapping_policy`
- `generated_at`

### 2. `current_state`

回答“现在是什么局面”。

至少包含：

- 当前主题格局
- 当前资源配置
- 当前主导机构与活跃主体
- 当前经费与立项结构

典型对象：

- `topic_snapshots`
- `portfolio_summary`
- `institution_landscape`

### 3. `change_view`

回答“最近几年发生了什么变化”。

至少包含：

- 升温和回落主题
- 结构变化最大的主题
- 热点迁移通道
- 机构格局变化
- 人员活跃变化

典型对象：

- `signals`
- `migration`
- `change_rankings`

### 4. `baseline_forecast`

回答“如果什么都不改，接下来会怎样”。

至少包含：

- 下一个年度周期的升温/回落方向
- 资源结构可能继续扩张或收缩的领域
- 结构延续风险
- 重点关注主题清单

典型对象：

- `forecast_topics`
- `forecast_portfolio`
- `attention_ranking`

### 5. `risk_view`

回答“哪里值得提前管”。

至少包含：

- 过热扩张风险
- 结构空心化风险
- 集中度风险
- 协作衰减风险
- 迁移外流风险
- 人才接续风险信号

典型对象：

- `risk_alerts`
- `risk_rankings`
- `risk_mechanisms`

### 6. `evidence`

这是趋势模块不能缺的部分。

至少包含：

- 指标取值
- 时间窗
- 数据源
- 样本量
- 观测/代理标签
- 支撑该结论的项目或聚合证据引用

### 7. `limitations`

必须显式告知当前结论的边界。

至少包含：

- 数据覆盖缺口
- 低样本主题
- 代理指标说明
- 当前不支持的判断项

## 三、结果对象设计

### 1. `topic_snapshot`

用于承载单个主题当前状态。

建议字段：

- `topic_id`
- `topic_name`
- `year`
- `application_count`
- `funded_count`
- `contract_special_funding`
- `active_institution_count`
- `active_person_count`
- `topic_centrality`
- `collaboration_density`
- `evidence_tags`

### 2. `trend_signal`

用于表达已发生的结构变化。

建议字段：

- `signal_id`
- `topic_id`
- `signal_type`
- `window`
- `direction`
- `strength`
- `basis_metrics`
- `evidence_type`
- `confidence_note`

### 3. `migration_record`

用于表达主题迁移或联动变化。

建议字段：

- `source_topic_id`
- `target_topic_id`
- `window`
- `flow_direction`
- `flow_strength`
- `evidence_basis`
- `evidence_type`

### 4. `forecast_record`

用于表达基线世界下的未来方向判断。

建议字段：

- `topic_id`
- `forecast_window`
- `baseline_direction`
- `attention_level`
- `supporting_signals`
- `uncertainty_note`
- `evidence_boundary`

### 5. `risk_alert`

用于表达领导级风险提醒。

建议字段：

- `topic_id`
- `risk_type`
- `risk_level`
- `trigger_signals`
- `mechanism_summary`
- `evidence_boundary`

## 四、接口设计

趋势模块应属于统一 `sandbox` 体系，而不是独立平行服务。

建议接口命名如下：

- `/api/v1/sandbox/trend/briefing`
- `/api/v1/sandbox/trend/snapshot`
- `/api/v1/sandbox/trend/changes`
- `/api/v1/sandbox/trend/forecast`
- `/api/v1/sandbox/trend/risks`
- `/api/v1/sandbox/trend/evidence`
- `/api/v1/sandbox/trend/debug/html`

### 1. `/briefing`

直接返回领导页所需的整包结果。

适用场景：

- 领导首页
- 一次完整主题分析
- 会议简报生成

### 2. `/snapshot`

只返回当前状态，不含未来判断。

适用场景：

- 当前局势看板
- 横向对比多个主题

### 3. `/changes`

返回变化信号和迁移记录。

适用场景：

- 看近几年变化
- 看热点迁移

### 4. `/forecast`

返回基线世界下的未来方向判断。

适用场景：

- 不改政策时的明年走势
- 形成 simulation 的 baseline 输入

### 5. `/risks`

返回风险列表和风险排序。

适用场景：

- 领导预警
- 重点研判专题

### 6. `/evidence`

返回任一结论对应的证据链。

适用场景：

- 追问解释
- 审计复核
- 页面 drill-down

## 五、接口输入原则

所有趋势接口都必须显式输入：

- 时间窗
- 主题范围
- 对象范围
- 统计口径
- 是否启用外部辅助信号

不允许默认隐式改口径。

建议输入结构：

```json
{
  "window": {
    "history_years": [2020, 2021, 2022, 2023, 2024, 2025],
    "forecast_horizon_years": 1
  },
  "scope": {
    "topic_ids": [],
    "program_ids": [],
    "institution_ids": []
  },
  "options": {
    "topic_mapping_policy": "guide_first",
    "include_external_signals": true
  }
}
```

## 六、输出边界要求

所有接口返回都必须显式包含以下披露项：

- `coverage_years`
- `sample_size`
- `data_gaps`
- `evidence_boundary`
- `unsupported_claims`

如果某结论主要依赖代理或辅助信号，接口必须明确标注，不能在领导页里伪装成硬事实。
