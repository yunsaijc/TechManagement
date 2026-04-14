# topic_time_panel 设计

## 一、目标

`topic_time_panel` 是趋势预判层的第一张核心表。

它的职责不是复刻原始业务库，而是把分散在业务库、图谱和派生计算中的信息，统一折叠到 `topic × time_window` 粒度，供后续：

- 热点迁移检测
- 生命周期识别
- 风险预测
- baseline forecast

共同使用。

## 二、主键与粒度

### 1. 主键

建议主键：

- `topic_id`
- `time_window`

### 2. 粒度

第一版固定为：

- `topic × time_window`

其中：

- `topic` 是统一后的主题口径
- `time_window` 建议先使用自然年，后续可扩展到季度

## 三、topic 的统一规则

当前系统里“主题”并不稳定，至少存在三套口径：

1. 项目库中的 `Sb_Jbxx.zndm / zxmc`
2. Neo4j `Project` 节点中的 `guideName`
3. Neo4j `Project` 节点中的 `department / office`

因此必须先定义统一 topic 映射规则。

### 1. 第一版推荐

第一版建议采用“指南方向优先”的口径：

```text
topic_id   = normalized_guide_code_or_name
topic_name = normalized_guide_name
topic_type = guide
```

优先级建议：

1. `zndm`
2. `guideName`
3. `zxmc`
4. `department`
5. `office`

### 2. 原则

- 同一主题在所有表中必须只对应一个 `topic_id`
- `department / office` 只能作为回退口径，不能和 `guide` 口径混在同一版模型里训练
- 任何“混合主题口径”的训练集都必须显式标记版本

## 四、源字段映射

## 1. 项目业务库映射

基于 [03-project-db.md](/home/tdkx/workspace/tech/docs/15-data/03-project-db.md)，第一版可直接利用的字段包括：

| 原始表 | 原始字段 | 建议目标字段 | 说明 |
|---|---|---|---|
| `Sb_Jbxx` | `id` | `project_id` | 项目标识 |
| `Sb_Jbxx` | `xmmc` | `project_name` | 项目名称 |
| `Sb_Jbxx` | `zndm` | `topic_id_raw` | 指南代码 |
| `Sb_Jbxx` | `zxmc` | `topic_name_raw` | 专项名称 |
| `Sb_Jbxx` | `year` | `time_window` | 年度 |
| `Sb_Jbxx` | `cddwMc` / `dwmc` | `organization_name` | 组织维度 |
| `Sb_Jbxx` | `xmFzr` | `project_leader` | 负责人 |
| `PGPS_XMPSXX` | `SFLX` | `funded_flag` | 是否立项 |
| `PGPS_XMPSXX` | `LXJF` | `funding_amount` | 立项经费 |
| `PGPS_XMPSXX` | `WPFS` / `FSFS` | `score_proxy` | 阶段评分代理特征 |

### 2. 图谱库映射

基于当前 sandbox 原型代码，Neo4j `Project` 节点第一版已显式使用以下字段：

| 图谱字段 | 建议目标字段 | 来源说明 |
|---|---|---|
| `period` | `time_window_raw` | 当前 Step2/Step3 已使用 |
| `guideName` | `topic_name_raw` | 当前主主题口径之一 |
| `department` | `topic_name_fallback` | 回退口径 |
| `office` | `topic_name_fallback2` | 回退口径 |
| `projectName` | `project_name` | 展示/映射字段 |

对应代码可见：

- [hotspot_migration_step2.py](/home/tdkx/workspace/tech/src/services/sandbox/hotspot_migration_step2.py)
- [macro_insight_step3.py](/home/tdkx/workspace/tech/src/services/sandbox/macro_insight_step3.py)

## 五、生成流程

建议 ETL 流程如下：

```text
Step A: 读取项目业务库与图谱库原始数据
  -> Step B: 统一 year / period 到 time_window
  -> Step C: 统一 topic_id / topic_name
  -> Step D: 聚合到 topic × time_window
  -> Step E: 左连接 funding / output / talent / conversion 指标
  -> Step F: 产出 topic_time_panel
```

## 六、字段分组

建议将字段按 5 组管理：

### 1. 主键字段

- `topic_id`
- `time_window`

### 2. 主题元字段

- `topic_name`
- `topic_type`
- `topic_version`

### 3. 规模字段

- `application_count`
- `funded_count`
- `funding_amount`
- `project_active_count`

### 4. 能力字段

- `talent_headcount`
- `talent_senior_ratio`
- `talent_backbone_ratio`
- `collaboration_density`

### 5. 成效字段

- `output_count`
- `high_value_output_count`
- `acceptance_rate`
- `conversion_rate`
- `conversion_lag`

## 七、校验规则

`topic_time_panel` 生成后必须跑以下校验：

1. 主键唯一
2. `topic_id` 非空比例达到阈值
3. `time_window` 可解析比例达到阈值
4. 同一时间窗内的 `application_count >= funded_count`
5. `conversion_rate` 落在合理区间
6. 高缺失字段必须单独标记，不允许静默丢弃

## 八、第一版停损线

如果出现以下情况，`topic_time_panel` 不应继续向下游提供训练输入：

1. `topic_id` 无法稳定统一
2. `year / period` 映射错误率过高
3. `funding_amount` 与 `funded_count` 大面积错位
4. `conversion` 数据无法和项目或主题稳定关联

这时应先修数据口径，而不是继续推进模型。
