# 趋势预判输出与接口

## 一、输出结构

趋势预判建议输出统一结果结构：

```json
{
  "meta": {},
  "snapshot": {},
  "signals": [],
  "migration": [],
  "ranking": []
}
```

## 二、主要输出对象

### 1. snapshot

用于表达当前窗口的主题状态快照，例如：

- 申报规模
- 立项规模
- 经费强度
- 协作结构
- 主题中心性

### 2. signals

用于表达已经发生的变化。

每条 signal 至少应包含：

- `topic_id`
- `window`
- `signal_type`
- `metric_basis`
- `direction`
- `strength`
- `evidence`

### 3. migration

用于表达主题之间的迁移关系。

每条 migration 至少应包含：

- `source_topic_id`
- `target_topic_id`
- `from_year`
- `to_year`
- `flow_strength`
- `evidence_count`

### 4. ranking

用于表达需要关注的主题排序。

建议至少提供 4 类 ranking：

- `heating`
- `cooling`
- `risk`
- `migration_active`

## 三、建议 API

建议 API 按能力命名：

- `/api/v1/trend/snapshot`
- `/api/v1/trend/signals`
- `/api/v1/trend/migration`
- `/api/v1/trend/ranking`

## 四、接口设计原则

1. 输入必须显式包含时间窗和主题口径
2. 输出必须带证据字段，不允许只返回结论文本
3. 输出必须区分“当前状态”“已发生变化”“迁移关系”“综合排序”
4. 缺失或低质量数据必须通过 `data_quality_flags` 暴露
