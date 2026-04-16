# 趋势预判数据 Schema

## 一、设计原则

趋势模块的数据 Schema 不能再围绕单一 `topic_time_panel` 展开。

正确做法是：

- 先建立事实层
- 再建立关系层
- 再建立统计层
- 最后补充辅助信号层和输出层

其中：

- 项目库 + 图谱 是主数据底座
- 外部信息是辅助信号层，不是主数据层

## 二、事实层 Schema

事实层负责保存真实业务事件。

### 1. `fact_project`

项目主事实表，锚定 `Sb_Jbxx.id`。

主要来源：

- `Sb_Jbxx`
- `Sb_Sbzt`

建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` | 项目主键 |
| `application_year` | 申报年份 |
| `project_name` | 项目名称 |
| `guide_code_raw` | 原始指南代码 |
| `guide_name_raw` | 原始指南名称 |
| `program_name_raw` | 原始专项名称 |
| `status_flags` | 申报状态与公开状态 |

### 2. `fact_review`

评审事实表，对应评审过程与结果。

主要来源：

- `PS_XMPSXX`

建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` | 项目主键 |
| `review_year` | 评审发生年份 |
| `review_stage_flags` | 网评/复审/终评等阶段标记 |
| `review_score_raw` | 原始评分 |
| `review_rank_raw` | 原始排名 |
| `review_score_proxy` | 标准化评分代理 |

### 3. `fact_requested_funding`

申报阶段经费事实表。

主要来源：

- `Sb_Jfgs`

建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` | 项目主键 |
| `requested_special_funding` | 申报专项经费 |
| `requested_self_funding` | 申报自筹经费 |

### 4. `fact_award_contract`

立项与合同事实表。

主要来源：

- `Ht_XMLXXX`
- `Ht_Jbxx`
- `Ht_Jfgs`

建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` | 项目主键 |
| `award_project_no` | 立项项目编号 |
| `funded_flag` | 是否进入立项/合同 |
| `award_year` | 立项年份 |
| `contract_year` | 合同年份 |
| `contract_special_funding` | 合同专项经费 |
| `contract_self_funding` | 合同自筹经费 |

说明：

- 当前趋势模块的强支撑事实主要到合同层。
- 验收、转化等后续事实不能在此处假装已经完整存在。

## 三、关系层 Schema

关系层用于表达结构，而不是表达事件结果。

### 1. `rel_project_topic`

用于将项目映射到统一主题口径。

建议字段：

- `project_id`
- `topic_id`
- `topic_name`
- `topic_source`
- `mapping_confidence`
- `mapping_flags`

### 2. `rel_project_institution`

用于表达项目与机构关系。

建议字段：

- `project_id`
- `institution_id`
- `institution_name`
- `institution_role`
- `source_system`

### 3. `rel_project_person`

用于表达项目与人员关系。

建议字段：

- `project_id`
- `person_id`
- `person_name`
- `person_role`
- `source_system`

### 4. `rel_topic_topic`

用于表达主题之间的共现、相邻和迁移关系。

建议字段：

- `source_topic_id`
- `target_topic_id`
- `relation_type`
- `window`
- `weight`
- `evidence_count`
- `evidence_type`

### 5. `rel_institution_institution`

用于表达机构协作关系。

建议字段：

- `source_institution_id`
- `target_institution_id`
- `window`
- `collaboration_weight`
- `evidence_count`

说明：

- 关系层中的很多权重来自图谱或派生计算，应明确标注代理属性。

## 四、统计层 Schema

统计层是趋势模块的主要工作层。

### 1. `mart_topic_year_state`

这是 `topic × year` 分析宽表。

它的地位是“主分析 mart”，不是业务本体。

建议字段：

| 字段 | 说明 | 数据属性 |
|---|---|---|
| `topic_id` | 主题标识 | 观测+映射 |
| `topic_name` | 主题名称 | 观测+映射 |
| `year` | 自然年 | 观测 |
| `application_count` | 申报项目数 | 观测聚合 |
| `requested_special_funding` | 申报专项经费 | 观测聚合 |
| `funded_count` | 立项项目数 | 观测聚合 |
| `contract_special_funding` | 合同专项经费 | 观测聚合 |
| `avg_award_size` | 平均立项/合同规模 | 观测聚合 |
| `active_institution_count` | 活跃机构数 | 观测聚合 |
| `active_person_count` | 活跃人员数 | 部分观测 |
| `organization_concentration` | 机构集中度 | 观测聚合 |
| `institution_entry_share` | 新进入机构占比 | 观测聚合 |
| `person_entry_share` | 新进入人员占比 | 部分观测 |
| `review_score_proxy` | 评审强度代理 | 代理 |
| `topic_centrality` | 主题中心性 | 代理 |
| `collaboration_density` | 协作密度 | 代理 |
| `migration_inflow` | 迁入强度 | 代理 |
| `migration_outflow` | 迁出强度 | 代理 |
| `data_quality_flags` | 数据质量标记 | 元数据 |

### 2. `mart_topic_institution_year_state`

用于看机构格局和集中度变化。

建议字段：

- `topic_id`
- `institution_id`
- `year`
- `project_count`
- `funded_count`
- `contract_special_funding`
- `institution_share`
- `entry_flag`

### 3. `mart_topic_person_year_state`

用于看人才活跃和接续信号。

建议字段：

- `topic_id`
- `person_id`
- `year`
- `project_count`
- `funded_project_count`
- `bridge_score`
- `entry_flag`
- `exit_flag`

### 4. `mart_project_cohort_outcome`

用于将同一申报批次作为 cohort 观察。

建议字段：

- `application_year`
- `topic_id`
- `project_count`
- `funded_count`
- `contracted_count`
- `requested_special_funding`
- `contract_special_funding`

### 5. `mart_portfolio_year_state`

用于领导视角的全局组合状态。

建议字段：

- `year`
- `topic_count`
- `total_application_count`
- `total_funded_count`
- `total_contract_special_funding`
- `high_attention_topic_count`
- `high_risk_topic_count`

## 五、辅助信号层 Schema

外部信息不进入主事实层和主统计层，而进入独立辅助信号层。

### 1. `aux_topic_external_signal`

建议字段：

| 字段 | 说明 |
|---|---|
| `topic_id` | 主题标识 |
| `year` | 时间窗 |
| `signal_source` | 来源类型，如 policy/news/paper/patent/industry |
| `signal_label` | 信号标签 |
| `signal_strength` | 归一化强度 |
| `evidence_ref` | 来源引用 |
| `coverage_note` | 覆盖说明 |
| `confidence_note` | 可信度说明 |

作用边界：

- 只用于解释增强、排序校正、风险提示
- 不用于覆盖业务主事实

## 六、输出层 Schema

输出层保存结构化结果，供接口和领导页面消费。

### 1. `out_trend_signal`

建议字段：

- `signal_id`
- `topic_id`
- `signal_type`
- `window`
- `direction`
- `strength`
- `basis_metrics`
- `evidence_type`

### 2. `out_trend_forecast`

建议字段：

- `topic_id`
- `forecast_window`
- `baseline_direction`
- `attention_level`
- `supporting_signal_ids`
- `uncertainty_note`

### 3. `out_trend_risk`

建议字段：

- `topic_id`
- `risk_type`
- `risk_level`
- `trigger_signal_ids`
- `mechanism_summary`
- `evidence_boundary`

## 七、Schema 设计结论

趋势模块的数据 Schema 必须体现以下口径：

1. `topic × year` 只是统计 mart，不是业务本体
2. 项目库和图谱共同组成主底座
3. 外部信息只能作为辅助信号层
4. 所有预测与风险结论都必须回溯到事实层和关系层

这样，趋势模块才真正是在构建 `baseline world forecast`，而不是围绕一张宽表做演示。
