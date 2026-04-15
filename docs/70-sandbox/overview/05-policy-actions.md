# 70 政策动作清单

## 一、目的

本清单用于统一沙盘推演中的 `PolicyInstrument` 定义。

没有政策动作清单，系统很容易退化成：

- 对历史趋势做口头建议
- 用 LLM 生成“如果这样做可能会更好”的文本

这两者都不是可执行的政策仿真。

## 二、第一版政策动作范围

第一版建议只覆盖可参数化、可比较、可解释的动作，不追求政策文本的全覆盖。

建议优先纳入以下 5 类：

1. 配额调整
2. 准入门槛调整
3. 评审权重调整
4. 重点方向倾斜
5. 人才 / 协作支持

## 三、最小政策动作表

| 动作类型 | 说明 | 作用对象 | 可调参数 | 生效周期 | 主要影响路径 | 历史可识别性 |
|---|---|---|---|---|---|---|
| `quota_adjustment` | 调整某类主题或计划的资助配额 | `topic` / `program` | 配额比例、绝对数量 | 年度 | `P -> funded_count -> output/conversion` | 中 |
| `eligibility_change` | 调整申报资格或准入条件 | `topic` / `organization` / `applicant_type` | 门槛强度、约束条件 | 年度 | `P -> application_count -> funded_count` | 中高 |
| `evaluation_weight_change` | 调整评审维度权重 | `topic` / 全局评审体系 | 权重向量、阈值 | 年度 | `P -> selection_structure -> output/conversion` | 低到中 |
| `topic_priority_shift` | 对重点方向实施倾斜支持 | `topic` | 优先级、资源倾斜比例 | 年度 | `P -> funding_amount/talent_flow -> output` | 中 |
| `talent_support` | 提供人才专项支持 | `topic` / `organization` | 支持强度、人数、经费 | 年度 / 多年 | `P -> talent_headcount/quality -> output/conversion` | 低到中 |
| `collaboration_incentive` | 鼓励跨团队或跨主题协作 | `topic` / `organization_pair` | 激励强度、覆盖范围 | 年度 / 多年 | `P -> collaboration_density -> output/conversion` | 低 |

## 四、动作字段建议

每个动作至少应具备以下字段：

| 字段 | 含义 |
|---|---|
| `instrument_id` | 动作唯一标识 |
| `instrument_type` | 动作类型 |
| `target_scope` | 作用对象范围 |
| `parameters` | 强度、阈值、比例等参数 |
| `effective_window` | 生效窗口 |
| `constraints` | 预算、总量、资格等约束 |
| `assumptions` | 未被数据识别、需外显的假设 |

## 五、识别与假设边界

不同政策动作的“历史可识别性”差异很大：

### 1. 相对可识别

- 配额调整
- 准入门槛变化

这类动作通常能在历史制度变化中找到较明确的事件点，适合后续做：

- DID
- Event Study
- Synthetic Control

### 2. 主要依赖结构假设

- 评审权重变化
- 人才支持
- 协作激励

这类动作在历史中往往没有足够干净的识别条件，第一版应明确标注：

- 哪些效果来自历史估计
- 哪些效果来自专家参数化

## 六、第一版推荐优先级

如果要尽快做出可运行的沙盘推演 MVP，建议优先实现：

1. `quota_adjustment`
2. `topic_priority_shift`
3. `talent_support`

原因：

- 作用对象清晰
- 参数化简单
- 容易和趋势预判层状态变量对接
