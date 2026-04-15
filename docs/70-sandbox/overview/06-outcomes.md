# 70 结果变量清单

## 一、目的

本清单用于统一趋势预判和沙盘推演最终关注的结果变量。

没有明确的结果变量，系统容易陷入两个误区：

1. 只做中间指标展示，不知道优化目标是什么
2. 将“模型预测得准”误当成“决策上有价值”

## 二、结果变量分层

建议将结果变量拆为三层：

1. 结构结果
2. 能力结果
3. 成效结果

## 三、最小结果变量表

| 结果变量 | 含义 | 建议粒度 | 时间窗口 | 主要用途 |
|---|---|---|---|---|
| `topic_share` | 某主题在申报或资助中的占比 | `topic × time` | 年 / 季 | 结构变化、政策倾斜结果 |
| `funded_structure_index` | 立项结构分布指数 | `topic × time` | 年 / 季 | 结构优化评估 |
| `talent_quality_index` | 人才质量综合指数 | `topic × time` | 年 / 季 | 能力建设评估 |
| `collaboration_strength_index` | 协作强度综合指数 | `topic × time` | 年 / 季 | 机制评估 |
| `output_efficiency` | 单位资源产出效率 | `topic × time` | 年 / 季 | 绩效评估 |
| `conversion_rate` | 转化率 | `topic × time` | 年 / 季 | 核心成效指标 |
| `conversion_lag` | 转化时滞 | `topic × time` | 年 / 季 | 时效性评估 |
| `risk_score` | 综合风险得分 | `topic × time` | 年 / 季 | 趋势预判与干预比较 |
| `opportunity_score` | 潜在机会得分 | `topic × time` | 年 / 季 | 资源倾斜和策略选择 |

## 四、不同层的关注重点

### 1. 趋势预判关注

趋势预判更关注：

- `risk_score`
- `opportunity_score`
- `topic_share`
- `conversion_rate`

原因是它要回答“未来会变成什么样”。

### 2. 沙盘推演关注

沙盘推演更关注：

- `topic_share` 的变化量
- `talent_quality_index` 的变化量
- `output_efficiency` 的变化量
- `conversion_rate` 的变化量
- `risk_score` 的下降幅度

原因是它要回答“政策动作带来了多大变化”。

## 五、评估方式

### 1. Baseline 评估

对趋势预判，建议重点看：

- 预测误差
- 排序稳定性
- 高风险主题命中率
- 解释一致性

### 2. Intervention 评估

对沙盘推演，建议重点看：

- 相对基线变化量
- 方案间排序差异
- 对目标主题的增益
- 对其他主题的副作用
- 结果对关键假设的敏感性

## 六、第一版主目标

第一版不建议同时优化所有结果变量。

建议优先锁定以下 4 个：

- `topic_share`
- `talent_quality_index`
- `conversion_rate`
- `risk_score`

这四个指标已经足以支撑第一版：

- 热点迁移与结构变化分析
- 高增低转风险预判
- 人才支持类政策仿真
- 重点方向倾斜类政策比较
