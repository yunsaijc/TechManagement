# baseline 与 scenario 设计

## 一、目标

沙盘推演层真正需要的不是“一个请求体”，而是两个稳定对象：

1. `baseline`
2. `scenario`

其中：

- `baseline` 负责固定被干预的参考世界
- `scenario` 负责表达对这个世界施加了哪些政策动作

## 二、baseline 的来源

第一版 `baseline` 不应人工拼装，而应直接来自趋势预判层的稳定输出。

推荐来源链路：

```text
topic_time_panel
  -> trend snapshot / ranking
  -> baseline_snapshot
```

也就是说：

- baseline 不是单独维护的一套世界
- baseline 是趋势层在某个时间点或某个预测窗口的冻结结果

## 三、baseline_snapshot 设计

### 1. 版本化

每个 baseline 必须带版本：

- `baseline_id`
- `source_run_id`
- `data_version`
- `feature_version`
- `forecast_version`

否则后续同一场景无法复算。

### 2. 字段建议

baseline 至少应包含：

- 项目规模状态
- 评审与立项状态
- 合同经费状态
- 图谱结构状态
- 风险状态

最低字段集合建议：

- `application_count`
- `funded_count`
- `funding_amount`
- `score_proxy`
- `collaboration_density`
- `topic_centrality`
- `migration_strength`
- `proxy_risk`

外部信息不写入 baseline 主状态，而应在 scenario 侧以 `external_shock` 或 `external_constraint` 挂载。

## 四、scenario 设计

### 1. scenario 的职责

一个 `scenario` 必须明确回答：

1. 基于哪个 baseline
2. 做了哪些动作
3. 这些动作有哪些约束
4. 存在哪些外生冲击
5. 用哪些指标评价结果

### 2. 最小结构

```json
{
  "baseline_id": "baseline_2026_y",
  "scenario_name": "priority_shift_a",
  "instruments": [],
  "external_shocks": [],
  "constraints": {},
  "evaluation_targets": []
}
```

## 五、instrument 在 scenario 中的组织方式

第一版建议：

- 一个 scenario 支持多个 instrument
- instrument 之间显式有顺序
- 每个 instrument 可单独启停

原因：

- 现实政策很少是单动作
- 需要支持“单独动作”和“组合动作”对比

## 六、外生冲击在 scenario 中的组织方式

建议：

- 外部政策导向变化作为 `policy_shock`
- 新闻/舆情事件作为 `event_shock`
- 产业变化作为 `industry_shock`

这些冲击不直接改变 baseline，而是在 rollout 时改变参数、约束或解释权重。

## 七、仿真窗口

每个 scenario 还必须定义推演窗口：

| 字段 | 含义 |
|---|---|
| `anchor_window` | 干预开始的时间点 |
| `forecast_windows` | 需要推演的未来窗口 |
| `rollout_mode` | 单期还是多期滚动 |

第一版建议优先支持：

- 单年度干预
- 未来 1-2 个窗口的比较

## 八、结果记录设计

建议最少沉淀三类结果：

### 1. run-level

记录一次场景运行的全局信息：

- `run_id`
- `scenario_id`
- `baseline_id`
- `engine_version`
- `status`

### 2. topic-level

记录每个主题在不同窗口下的结果：

- `baseline_application_count`
- `projected_application_count`
- `baseline_funded_count`
- `projected_funded_count`
- `baseline_funding_amount`
- `projected_funding_amount`
- `baseline_proxy_risk`
- `projected_proxy_risk`

### 3. explanation-level

记录变化原因：

- 哪条路径贡献最大
- 哪个 instrument 起主导作用
- 哪些结果主要来自数据估计
- 哪些结果主要来自结构假设

## 九、当前推荐场景

第一版不要追求全政策空间覆盖，建议只做以下 3 类：

1. `quota_adjustment`
2. `topic_priority_shift`
3. `collaboration_incentive`

原因：

- 作用对象清楚
- 容易落到 `topic × time_window` 状态空间
- 更适合作为结构仿真的第一批动作

## 十、停损线

如果以下任一条件不满足，scenario 引擎应限制功能而不是硬算：

1. baseline 版本不可追溯
2. instrument 参数无法结构化
3. evaluation target 未定义
4. baseline 与 forecast window 无法对齐

这四种情况下继续跑，只会得到不可审计的“伪推演”。
