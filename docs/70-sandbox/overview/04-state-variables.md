# 70 状态变量与对象层次

## 一、目的

本清单用于统一趋势预判与沙盘推演共享的对象层次和状态变量定义。

本文件强调两点：

1. `topic × year` 是主分析层，不是业务本体
2. 所有变量必须区分“真实观测”与“代理”

## 二、对象层次

最终系统必须并存三层：

### 1. 事实层

围绕 `Project` 的生命周期事实：

- 申报
- 评审
- 立项
- 合同
- 经费
- 验收
- 转化

### 2. 关系层

围绕主题、机构、人员的结构关系：

- `Project -> Topic`
- `Project -> Institution`
- `Project -> Person`
- `Topic <-> Topic`
- `Institution <-> Institution`

### 3. 统计层

围绕可用于分析与推演的状态面板：

- `topic × year`
- `topic × institution × year`
- `topic × person × year`
- `project_cohort_outcome`

## 三、主分析粒度

第一主粒度定义为：

`topic × year`

理由：

- 足够支撑趋势预判
- 足够作为沙盘推演的核心状态层
- 能与预算、配额、评审阈值等政策动作对接

必要时下钻到：

- `topic × program × year`
- `topic × institution × year`
- `topic × person × year`

## 四、主题年度状态变量

主题年度层至少应包含以下变量：

| 变量 | 含义 | 数据性质 | 主要来源 | 角色 |
|---|---|---|---|---|
| `application_count` | 申报项目数 | 观测 | `Sb_Jbxx + Sb_Sbzt` | 基础状态 |
| `requested_funding_amount` | 申报专项经费 | 观测 | `Sb_Jfgs` | 基础状态 |
| `funded_count` | 立项项目数 | 观测 | `Ht_XMLXXX` | 基础状态 |
| `funded_ratio` | 立项率，优先 cohort 口径 | 观测聚合 | 项目生命周期事实 | 结构结果 |
| `contract_funding_amount` | 合同专项经费总额 | 观测 | `Ht_Jfgs` | 基础状态 |
| `avg_award_size` | 平均合同/立项规模 | 观测聚合 | `Ht_Jfgs / Ht_XMLXXX` | 结构结果 |
| `review_score_proxy` | 评审强度代理 | 代理 | `PS_XMPSXX` | 质量代理 |
| `active_institution_count` | 活跃承担单位数 | 观测聚合 | 项目-单位关系 | 结构状态 |
| `active_person_count` | 活跃 PI/人员数 | 部分观测 | 项目-人员/图谱 | 结构状态 |
| `organization_concentration` | 机构集中度 | 观测聚合 | 项目-单位关系 | 风险特征 |
| `entrant_share` | 新进入主体占比 | 观测聚合 | 单位/人员跨年状态 | 风险特征 |
| `collaboration_density` | 协作网络密度 | 代理 | 图谱 | 结构代理 |
| `topic_centrality` | 主题结构中心性 | 代理 | 图谱 | 结构代理 |
| `migration_strength` | 主题迁移强度 | 代理 | 图谱 | 迁移代理 |
| `structural_risk` | 结构性风险综合量 | 代理复合 | 观测 + 图谱 | 风险输出 |

## 五、项目生命周期核心变量

项目层至少应保留以下变量：

| 变量 | 含义 | 数据性质 |
|---|---|---|
| `project_id` | 项目主键，锚定 `Sb_Jbxx.id` | 观测 |
| `application_year` | 申报年份 | 观测 |
| `topic_id` | 项目所属主题 | 观测/映射 |
| `requested_special_funding` | 申报专项经费 | 观测 |
| `review_stage_flags` | 是否进入网评/复审/终评等阶段 | 观测 |
| `review_score_raw` | 原始评审分数 | 观测 |
| `review_score_percentile` | 评分分位 | 代理标准化 |
| `funded_flag` | 是否立项 | 观测 |
| `awarded_funding` | 立项经费 | 观测 |
| `contracted_special_funding` | 合同专项经费 | 观测 |
| `disbursed_amount` | 已拨付金额 | 观测 |

## 六、时间轴规则

系统中至少应并存以下时间轴：

- `application_year`
- `review_year`
- `award_year`
- `contract_year`
- `acceptance_year`
- `transformation_year`

默认提供两种分析视角：

1. `event_year`
   某年真实发生了什么
2. `application_cohort_year`
   某批申报项目后来走成了什么样

## 七、当前数据条件下的边界

当前项目库和图谱下，可以稳定使用的结果变量主要是：

- 申报
- 评审
- 立项
- 合同
- 经费
- 主题/机构/人员结构关系

以下指标只能作为弱代理或暂不进入领导级硬指标：

- `acceptance_rate`
- `transformation_rate`
- `ROI`
- 强人才供给判断

## 八、文档使用原则

后续任何 trend 或 simulation 设计，都必须基于本文件定义：

- 先选对象层次
- 再选口径
- 再声明观测/代理属性

否则不允许直接进入实现或领导表达层。
