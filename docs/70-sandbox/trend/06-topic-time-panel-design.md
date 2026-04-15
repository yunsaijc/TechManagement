# topic_time_panel 设计

## 一、目标

`topic_time_panel` 是趋势预判的核心底座。

它的职责很明确：

把项目库和图谱中的主题状态折叠到 `topic × year` 粒度，供后续完成：

- 当前状态快照
- 变化信号检测
- 热点迁移关联
- 趋势与风险排序

## 二、主键与粒度

### 1. 主键

建议主键：

- `topic_id`
- `year`

### 2. 粒度

固定为：

- `topic × year`

这里不再混用季度、周期、阶段口径。

## 三、topic 统一规则

当前系统中 topic 口径并不稳定，因此必须先统一。

### 1. 统一口径

建议采用“指南方向优先”的规则：

```text
topic_id   = normalized_guide_identifier
topic_name = normalized_guide_name
topic_type = guide
```

优先级：

1. `zndm`
2. `guideName`
3. `zxmc`

`department / office` 不进入主训练口径，只能作为映射失败时的回退展示字段。

### 2. 原则

- 同一主题在所有数据源中必须只落到一个 `topic_id`
- 不允许同一批结果同时混用 guide 主题和部门主题
- 无法稳定映射的记录必须打标，而不是静默归并

## 四、源字段映射

### 1. 项目业务库映射

基于 [03-project-db.md](/home/tdkx/workspace/tech/docs/15-data/03-project-db.md)，优先利用以下字段：

| 原始表 | 原始字段 | 目标字段 | 说明 |
|---|---|---|---|
| `Sb_Jbxx` | `id` | `project_id` | 项目标识 |
| `Sb_Jbxx` | `xmmc` | `project_name` | 项目名称 |
| `Sb_Jbxx` | `zndm` | `topic_id_raw` | 指南代码 |
| `Sb_Jbxx` | `zxmc` | `topic_name_raw` | 专项名称 |
| `Sb_Jbxx` | `year` | `year` | 年度 |
| `PS_XMPSXX` | `WPFS / FSFS` | `score_proxy` | 评审强度代理值 |
| `Sb_Jfgs` | `zxjf / zcjf` | `requested_funding_amount` | 申报阶段经费概算 |
| `Ht_XMLXXX` | `SFLX / LXBH` | `funded_flag / award_project_no` | 立项状态与立项编号 |
| `Ht_Jfgs` | `zxjf / zcjf` | `funding_amount / self_raised_amount` | 合同阶段最终经费 |

### 2. 图谱库映射

Neo4j `Project` 节点优先利用以下字段：

| 图谱字段 | 目标字段 | 说明 |
|---|---|---|
| `year_norm / period` | `year` | 时间归一 |
| `guideName` | `topic_name_raw` | 主 topic 口径来源 |
| `department` | `topic_fallback` | 回退展示 |
| `office` | `topic_fallback2` | 回退展示 |

图谱侧当前主要贡献的是：

- `collaboration_density`
- `topic_centrality`
- `migration_strength`

### 3. 外部信息映射

外部信息不直接进入 `topic_time_panel` 主字段，而是通过独立信号层接入。

推荐来源包括：

| 来源类型 | 建议输出字段 | 作用 |
|---|---|---|
| 政策文本 | `policy_signal_strength` | 识别政策导向变化 |
| 新闻舆情 | `news_heat` | 识别短中期热点波动 |
| 论文/专利 | `paper_heat / patent_heat` | 识别学术与技术热度 |
| 产业信息 | `industry_signal_strength` | 识别产业拉动与外部约束 |

这些字段应沉淀到 `topic_external_signals`，再用于 ranking 和 explanation。

## 五、生成流程

建议生成链路如下：

```text
Step A: 读取项目库和图谱原始数据
  -> Step B: 统一年份字段
  -> Step C: 统一 topic_id / topic_name
  -> Step D: 按 topic × year 聚合项目指标
  -> Step E: 按 topic × year 聚合图谱指标
  -> Step F: 生成外部 topic signals
  -> Step G: 合并为 topic_time_panel
  -> Step H: 打上 data_quality_flags
```

## 六、字段分组

### 1. 主键字段

- `topic_id`
- `year`

### 2. 主题字段

- `topic_name`
- `topic_type`
- `topic_source`

### 3. 项目状态字段

- `application_count`
- `funded_count`
- `funding_amount`
- `score_proxy`

### 4. 图谱状态字段

- `collaboration_density`
- `topic_centrality`
- `migration_strength`

### 5. 质量字段

- `data_quality_flags`

外部信息字段不进入本表主体，而通过 `topic_external_signals` 与本表并行存在。

## 七、校验规则

`topic_time_panel` 生成后必须完成以下校验：

1. 主键唯一
2. `topic_id` 非空比例达到阈值
3. `year` 可解析比例达到阈值
4. 同年内 `application_count >= funded_count`
5. 图谱字段缺失必须显式标记
6. 评审字段缺失必须显式标记

## 八、停损线

如果出现以下情况，`topic_time_panel` 不应继续作为下游输入：

1. `topic_id` 无法稳定统一
2. 年份映射错误率过高
3. `funded_count` 与 `funding_amount` 大面积失真
4. 图谱字段无法映射到相同 topic 口径

这时应先修数据口径，再推进 trend 计算。
