# 70 状态变量清单

## 一、目的

本清单用于统一趋势预判与沙盘推演共享的状态变量定义。

没有统一状态变量，后续会出现以下问题：

1. 同一指标在不同模块中口径不一致
2. 趋势预判输出无法直接作为沙盘推演基线
3. 政策动作找不到明确的作用对象和结果变量

## 二、建模粒度

第一版建议统一采用 `topic × time_window` 作为主粒度，必要时再扩展到：

- `topic × organization × time_window`
- `topic × region × time_window`
- `topic × funding_program × time_window`

原因：

- `topic × time_window` 足够支撑热点迁移、结构变化和初版干预仿真
- 如果一开始就上更细粒度，数据缺失和口径不齐会把建模复杂度迅速放大

## 三、最小状态变量表

| 变量名 | 含义 | 建议粒度 | 时间频率 | 数据来源 | 可直接观测 | 模型角色 |
|---|---|---|---|---|---|---|
| `application_count` | 申报数量 | `topic × time` | 年 / 季 | 项目申报库 | 是 | 基础状态、预测特征、结果变量 |
| `funded_count` | 立项数量 | `topic × time` | 年 / 季 | 立项结果库 | 是 | 基础状态、结果变量 |
| `funding_amount` | 资助金额 | `topic × time` | 年 / 季 | 经费数据 | 是 | 基础状态、政策传导中间变量 |
| `project_active_count` | 在研项目数 | `topic × time` | 年 / 季 | 项目管理库 | 是 | 状态变量 |
| `talent_headcount` | 参与人才规模 | `topic × time` | 年 / 季 | 专家/项目人员数据 | 基本是 | 状态变量、机制变量 |
| `talent_senior_ratio` | 高层次人才占比 | `topic × time` | 年 / 季 | 人员职称数据 | 基本是 | 风险特征、机制变量 |
| `talent_backbone_ratio` | 中坚骨干占比 | `topic × time` | 年 / 季 | 人员角色数据 | 部分 | 风险特征、机制变量 |
| `collaboration_density` | 协作网络密度 | `topic × time` | 年 / 季 | 合作关系图谱 | 否，需计算 | 图特征、中间变量 |
| `cross_topic_mobility` | 人才跨主题流动强度 | `topic × time` | 年 / 季 | 人才-项目-主题图谱 | 否，需计算 | 迁移特征、机制变量 |
| `output_count` | 总产出数量 | `topic × time` | 年 / 季 | 论文/专利/成果库 | 是 | 状态变量、结果变量 |
| `high_value_output_count` | 高价值产出数量 | `topic × time` | 年 / 季 | 高价值成果标注 | 部分 | 结果变量 |
| `acceptance_rate` | 验收通过率 | `topic × time` | 年 / 季 | 项目验收库 | 是 | 结果变量 |
| `conversion_rate` | 转化率 | `topic × time` | 年 / 季 | 成果转化库 | 部分 | 核心结果变量 |
| `conversion_lag` | 从立项到转化的时滞 | `topic × time` | 年 / 季 | 项目与转化关联数据 | 否，需计算 | 效率特征、结果变量 |
| `topic_centrality` | 主题在动态图中的中心性 | `topic × time` | 年 / 季 | 主题关系图 | 否，需计算 | 迁移和演化特征 |
| `topic_embedding_shift` | 主题语义或结构漂移强度 | `topic × time` | 年 / 季 | 图嵌入/文本嵌入 | 否，需计算 | 迁移和预测特征 |

## 四、角色划分

这些状态变量在模型中应明确区分角色：

### 1. 预测目标

第一批建议作为预测目标的变量：

- `application_count`
- `funded_count`
- `output_count`
- `conversion_rate`

### 2. 风险特征

第一批建议作为风险建模特征的变量：

- `talent_senior_ratio`
- `talent_backbone_ratio`
- `collaboration_density`
- `conversion_lag`
- `topic_embedding_shift`

### 3. 干预中间变量

第一批建议作为政策作用中间变量的变量：

- `funding_amount`
- `talent_headcount`
- `collaboration_density`
- `application_count`
- `funded_count`

## 五、第一版取舍

第一版不要同时追求“全量变量完备”和“高复杂模型”。

建议先锁定以下最小变量集：

- `application_count`
- `funded_count`
- `funding_amount`
- `talent_headcount`
- `talent_senior_ratio`
- `collaboration_density`
- `output_count`
- `conversion_rate`

先把这些变量做稳，再逐步加入时滞、嵌入和图结构变量。
