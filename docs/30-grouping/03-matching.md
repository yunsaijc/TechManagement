# 👥 专家匹配子服务设计（V1）

## 概述

本篇文档按 [API 接口文档](05-api.md) 的当前口径维护，描述 `POST /api/v1/grouping/match` 的输入、处理流程与输出结构。

专家匹配子服务目标是：为指定分组分配评审专家，并返回可解释的匹配结果与统计信息。

---

## V1 范围

当前版本聚焦以下能力：

1. 按 `group_id` 对指定分组执行匹配
2. 基于语义相似度生成项目-专家匹配分
3. 支持关系回避开关（`avoid_relations`）
4. 返回项目级专家列表、统计与警告信息

当前版本不在本文承诺以下能力：

1. 严格意义上的全局最优求解（如匈牙利/线性规划完整约束解）
2. 复杂关系网络（师承图谱、论文合作图谱）全量接入
3. 完整的历史评审行为建模

---

## API 对齐

### 1) 专家匹配接口

- 方法与路径：`POST /api/v1/grouping/match`
- 基础路径：`/api/v1/grouping`

### 2) 请求参数（与 05-api 一致）

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `group_id` | Integer | 是 | - | 分组ID（来自分组接口返回） |
| `experts_per_project` | Integer | 否 | 5 | 每个项目分配专家数 |
| `min_experts_per_group` | Integer | 否 | 10 | 每组最少懂行专家数 |
| `avoid_relations` | Boolean | 否 | true | 是否启用关系回避 |
| `max_reviews_per_expert` | Integer | 否 | 5 | 每位专家最大评审数 |

请求示例：

```json
{
  "group_id": 1,
  "experts_per_project": 5,
  "min_experts_per_group": 10,
  "avoid_relations": true,
  "max_reviews_per_expert": 5
}
```

### 3) 响应结构（与 05-api 一致）

顶层响应：

- `status`
- `data`
- `message`
- `code`

`data` 字段结构：

- `id`: 匹配任务ID（示例：`match_1709280000002`）
- `group_id`: 分组ID
- `matches`: 项目匹配列表
- `statistics`: 统计信息
- `warnings`: 警告信息

`matches` 单项结构：

- `project_id`
- `experts[]`
  - `expert_id`
  - `xm`
  - `match_score`
  - `reason`
  - `avoidance`

`statistics` 结构：

- `total_projects`
- `total_experts`
- `avg_match_score`
- `avoidance_detected`
- `experts_per_project`
- `coverage_rate`

---

## 处理流程（V1）

```text
输入 group_id + 匹配参数
  -> 加载分组项目
  -> 按学科代码/条件召回候选专家
  -> 专家画像构建（研究方向、关键词等）
  -> 项目与专家向量化
  -> 计算项目-专家匹配分矩阵
  -> 按参数执行分配（含关系回避与容量限制）
  -> 汇总统计与 warnings
  -> 输出 MatchingResult
```

---

## 模块职责

### MatchingAgent

编排流程入口，负责：

1. 组装输入参数
2. 调用画像、打分、优化组件
3. 生成 `MatchingResult`

### ExpertProfiler

负责专家画像构建，输入专家原始字段（如熟悉学科、擅长专业、研究领域、论文论著），输出结构化研究方向和关键词，供后续匹配计算使用。

### MatchScorer

负责项目-专家评分：

1. 计算语义相似度
2. 融合学科一致性信号
3. 生成匹配分矩阵（0-100）

### MatchingOptimizer

负责把评分矩阵转换为最终分配结果，处理：

1. `experts_per_project`
2. `avoid_relations`
3. `max_reviews_per_expert`
4. `min_experts_per_group`（作为分组侧目标约束）

---

## 回避策略（V1）

`avoid_relations=true` 时，匹配阶段启用关系回避检查。回避结果通过 `avoidance` 返回：

- `avoided`: 是否回避
- `reason`: 回避原因
- `severity`: 严重级别（`low/medium/high/none`）

V1 约定：

1. `high/medium`：优先不分配
2. `low`：允许分配但进入 `warnings`
3. `none`：正常分配

---

## 统计口径（V1）

- `total_projects`: 本次参与匹配的项目数
- `total_experts`: 本次实际涉及的唯一专家数
- `avg_match_score`: 全部分配记录的平均匹配分
- `avoidance_detected`: 检测到的回避关系数量
- `experts_per_project`: 请求中的目标值
- `coverage_rate`: 唯一专家覆盖率

---

## 与完整流程接口关系

- `POST /api/v1/grouping/match`: 对单个分组执行专家匹配
- `POST /api/v1/grouping/full`: 先分组，再对所有组执行匹配并聚合结果

`/full` 的匹配参数与本篇文档保持一致，便于单组调试后无缝切换到全流程执行。

---

## 错误与降级约定

常见错误场景：

1. `group_id` 无效或分组不存在
2. 候选专家不足，无法满足目标分配数
3. 数据源或模型调用失败

处理原则：

1. 能返回部分结果时，返回 `warnings` 并保留可用分配
2. 无法形成有效结果时，返回明确错误信息供上层重试或人工介入

---

## 相关文档

- [服务概述 →](01-overview.md)
- [分组子服务 →](02-grouping.md)
- [数据模型 →](04-models.md)
- [API 接口 →](05-api.md)
