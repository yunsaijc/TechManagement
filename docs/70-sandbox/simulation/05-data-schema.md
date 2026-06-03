# 推演数据 Schema

## 一、设计目标

simulation 需要的不是一堆临时请求字段，而是一套围绕真实数据链、场景合同和反事实结果的稳定对象模型。

本文件只定义 simulation 相关逻辑对象，不改写业务主表。

核心原则：

- 以真实项目链路为事实底座
- 以图谱关系为结构增强层
- 以 `baseline` 与 `scenario` 为运行入口
- 以阶段结果和组合结果为输出对象

## 二、数据底座分层

simulation 的数据底座应分三层，而不是把所有东西摊平成一个大表。

### 1. 事实层

来自项目业务链：

- `Sb_Jbxx`
- `Sb_Sbzt`
- `Sb_Jfgs`
- `PS_XMPSXX`
- `Ht_XMLXXX`
- `Ht_Jbxx`
- `Ht_Jfgs`

### 2. 关系层

来自图谱关系数据：

- `Project-Topic`
- `Project-Institution`
- `Project-Person`
- `Topic-Topic`
- `Institution-Institution`
- 其他已建图关系

### 3. 统计层

在事实层与关系层之上沉淀：

- `project_lifecycle_fact`
- `topic_year_state`
- `topic_graph_state`
- `baseline_snapshot`
- `scenario_contract`
- `simulation_run_result`

`topic × year` 只是统计层分析宽表，不是业务本体。

## 三、核心逻辑表

## 1. project_lifecycle_fact

以 `Sb_Jbxx.id` 为主键锚定项目全生命周期。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `project_id` | string | 锚定 `Sb_Jbxx.id` |
| `application_year` | int | 申报年份 |
| `topic_id` | string | 主题/指南映射结果 |
| `project_name` | string | 项目名称 |
| `requested_special_funding` | decimal | 申报专项经费，来自 `Sb_Jfgs` |
| `public_audit_flag` | string | 公开审核状态，来自 `Sb_Sbzt` |
| `review_stage_flags_json` | json | 各评审阶段进入情况，来自 `PS_XMPSXX` |
| `review_score_raw` | decimal | 原始评分 |
| `review_rank_raw` | decimal | 原始排名或排序信息 |
| `funded_flag` | bool | 是否形成立项事实，来自 `Ht_XMLXXX` |
| `award_year` | int | 立项年份 |
| `contract_id` | string | 合同标识，来自 `Ht_Jbxx` |
| `contract_special_funding` | decimal | 合同专项经费，来自 `Ht_Jfgs` |
| `contract_self_funding` | decimal | 合同自筹经费，来自 `Ht_Jfgs` |

作用：

- 统一申报、评审、立项、合同的证据链
- 支撑 cohort 观察与场景阶段传导

## 2. topic_year_state

按 `topic_id + year` 聚合的主题年度状态，用于 simulation 的主状态空间。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | string | 主题标识 |
| `year` | int | 年份 |
| `application_count` | int | 申报项目数 |
| `requested_funding_amount` | decimal | 申报专项经费 |
| `review_score_percentile_p50` | decimal | 评分分位代理 |
| `review_score_percentile_p80` | decimal | 高分段代理 |
| `funded_count` | int | 立项项目数 |
| `funded_ratio_proxy` | decimal | 立项率代理 |
| `contract_funding_amount` | decimal | 合同专项经费 |
| `avg_award_size` | decimal | 平均资助强度 |
| `active_institution_count` | int | 活跃机构数 |
| `active_person_count` | int | 活跃人员数或代理人数 |
| `organization_concentration` | decimal | 机构集中度 |

作用：

- 承接 baseline 状态
- 支撑申报响应、评审选择、合同配置三段推演

## 3. topic_graph_state

按 `topic_id + year` 或 `topic_pair + year` 保存图谱结构状态。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | string | 主题标识 |
| `year` | int | 年份 |
| `collaboration_density` | decimal | 协作密度代理 |
| `topic_centrality` | decimal | 主题中心性代理 |
| `migration_strength` | decimal | 主题迁移强度代理 |
| `bridging_score` | decimal | 桥接性代理 |
| `structural_risk_score` | decimal | 结构性风险综合代理 |
| `evidence_scope_json` | json | 指标计算所依赖的图谱范围 |

作用：

- 作为结构外溢阶段的输入与输出
- 明确这些字段都是图谱代理，不冒充业务事实

## 四、baseline 与 scenario 对象

## 1. baseline_snapshot

保存被 simulation 引用的基线世界快照。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `baseline_id` | string | 基线标识 |
| `anchor_year` | int | 基线锚点年份 |
| `forecast_years_json` | json | 预测窗口 |
| `scope_json` | json | 主题/专项/对象范围 |
| `data_version` | string | 数据版本 |
| `feature_version` | string | 特征口径版本 |
| `baseline_method` | string | 基线生成方法 |
| `topic_state_json` | json | 主题年度基线状态 |
| `graph_state_json` | json | 图谱结构基线状态 |
| `constraints_json` | json | 基线固有约束 |

说明：

- `baseline_snapshot` 可以来自 trend 的 baseline 输出，但在 simulation 侧必须冻结并可复算。

## 2. scenario_contract

保存正式政策场景。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `scenario_id` | string | 场景标识 |
| `scenario_name` | string | 场景名称 |
| `baseline_id` | string | 关联基线 |
| `intent_json` | json | 决策问题与意图 |
| `baseline_scope_json` | json | 基线范围 |
| `policy_package_json` | json | 政策动作包 |
| `constraints_json` | json | 预算/配额/合规约束 |
| `evaluation_goals_json` | json | 评估目标 |
| `assumptions_json` | json | 结构假设 |
| `validation_json` | json | 观测/代理/不支持声明 |
| `created_by` | string | 创建者 |
| `created_at` | datetime | 创建时间 |

不再单独以“临时冲击参数”作为一等对象。

## 五、运行与结果对象

## 1. simulation_run

保存一次正式运行。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `baseline_id` | string | 基线标识 |
| `scenario_id` | string | 场景标识 |
| `engine_version` | string | 引擎版本 |
| `status` | string | 运行状态 |
| `started_at` | datetime | 开始时间 |
| `finished_at` | datetime | 结束时间 |
| `run_config_json` | json | 内部引擎配置 |
| `disclosure_json` | json | 数据覆盖与限制说明 |

## 2. simulation_stage_result

按治理阶段记录结果。

建议主键：

- `run_id`
- `stage_name`
- `topic_id`
- `forecast_year`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `stage_name` | string | `application_response / review_selection / award_contract / structural_spillover` |
| `topic_id` | string | 主题标识 |
| `forecast_year` | int | 推演年份 |
| `baseline_value_json` | json | 基线阶段状态 |
| `scenario_value_json` | json | 场景阶段状态 |
| `delta_json` | json | 变化量 |
| `support_level` | string | 证据等级 |
| `driver_action_ids_json` | json | 主导动作 |

作用：

- 强制把结果按治理流程落盘
- 支撑领导页的变化路径展示

## 3. simulation_topic_result

按主题沉淀最终结果。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `topic_id` | string | 主题标识 |
| `forecast_year` | int | 推演年份 |
| `baseline_application_count` | int | 基线申报数 |
| `scenario_application_count` | int | 场景申报数 |
| `baseline_funded_count` | int | 基线立项数 |
| `scenario_funded_count` | int | 场景立项数 |
| `baseline_contract_funding` | decimal | 基线合同专项经费 |
| `scenario_contract_funding` | decimal | 场景合同专项经费 |
| `baseline_structural_risk` | decimal | 基线结构风险代理 |
| `scenario_structural_risk` | decimal | 场景结构风险代理 |
| `winners_losers_tag` | string | 受益/受损/被挤出标签 |

## 4. simulation_portfolio_result

组合级结果，不再只看单主题。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `forecast_year` | int | 推演年份 |
| `total_application_count` | int | 总申报数 |
| `total_funded_count` | int | 总立项数 |
| `total_contract_funding` | decimal | 总合同专项经费 |
| `budget_reallocation_json` | json | 预算流向变化 |
| `crowding_out_json` | json | 挤出效应 |
| `risk_shift_json` | json | 风险迁移 |
| `goal_satisfaction_json` | json | 评估目标达成情况 |

## 5. simulation_explanation

保存解释链路。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 运行标识 |
| `entity_type` | string | `topic / portfolio / stage` |
| `entity_id` | string | 主题或组合标识 |
| `explanation_type` | string | `evidence / assumption / limitation` |
| `message` | string | 解释文本 |
| `evidence_json` | json | 表、指标、规则引用 |
| `confidence_label` | string | 可信度标签 |

## 六、请求与持久化边界

接口请求体只应引用或内联：

- `baseline_id`
- `scenario_contract`

而不是把中间引擎参数直接暴露给外部。

像以下字段属于内部运行配置，不应作为领导输入：

- 相似度阈值
- 正则化权重
- 图算法惩罚参数
- 代理指标融合权重

## 七、当前实现优先级

在不改业务主库的前提下，simulation 优先需要沉淀的是：

1. `project_lifecycle_fact`
2. `topic_year_state`
3. `topic_graph_state`
4. `baseline_snapshot`
5. `scenario_contract`
6. `simulation_run`
7. `simulation_stage_result`
8. `simulation_topic_result`

这套对象已经足够支撑“基线-场景-比较-解释”的完整链路。

## 八、边界声明

本 schema 仅为 simulation 的逻辑对象设计，不意味着当前所有字段都已经在现网数据中完整具备。

任何字段进入领导页之前，都必须先标记：

- `observed`
- `proxy`
- `assumption-heavy`
- `unsupported`
