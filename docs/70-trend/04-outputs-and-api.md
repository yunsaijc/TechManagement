# 趋势预判输出与接口

## 一、输出结构

趋势预判建议输出统一结果结构：

```json
{
  "meta": {},
  "snapshot": {},
  "signals": [],
  "forecasts": [],
  "risks": [],
  "explanations": []
}
```

## 二、主要输出对象

### 1. snapshot

用于表达当前窗口的结构快照，例如：

- 主题规模
- 人才结构
- 转化效率
- 协作结构

### 2. signals

用于表达已经发生的变化，例如：

- 热点迁移
- 主题升温
- 结构断裂
- 转化下滑

### 3. forecasts

用于表达未来窗口预测，例如：

- 未来一年升温主题
- 未来一年高风险主题
- 未来窗口的转化压力

### 4. risks

用于表达对决策方有意义的前瞻风险，而不是简单统计波动。

## 三、建议 API

建议 API 不再按旧的步骤脚本命名，而按能力命名：

- `/api/v1/trend/snapshot`
- `/api/v1/trend/signals`
- `/api/v1/trend/migration`
- `/api/v1/trend/forecast`
- `/api/v1/trend/risks`

## 四、接口设计原则

1. 输入显式包含时间窗和主题口径
2. 输出区分“已发生变化”和“未来预测”
3. 结果必须可追溯到原始指标与证据
