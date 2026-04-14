# 沙盘推演输出与接口

## 一、输出结构

沙盘推演建议输出统一结果结构：

```json
{
  "meta": {},
  "baseline": {},
  "scenario": {},
  "counterfactual": {},
  "impact_assessment": {},
  "causal_paths": [],
  "side_effects": []
}
```

## 二、核心输出对象

### 1. baseline

用于表达不干预时的参考世界。

### 2. counterfactual

用于表达施加政策动作后的模拟世界。

### 3. impact_assessment

建议至少覆盖：

- 相对基线的变化量
- 受影响对象
- 受益对象与受损对象
- 生效时间滞后

### 4. causal_paths

用于解释“为什么会产生这些变化”，而不是只给结论。

## 三、建议 API

建议 API 不再围绕旧的 `stepX` 命名，而按能力命名：

- `/api/v1/simulation/scenarios`
- `/api/v1/simulation/run`
- `/api/v1/simulation/compare`
- `/api/v1/simulation/explain`

## 四、接口设计原则

1. 输入显式包含基线引用和政策动作定义
2. 输出显式区分基线、反事实和差异
3. 结果必须支持多场景比较
4. 结论必须能追溯到机制假设与关键证据
