# 沙盘推演政策模型

## 一、为什么先定义政策模型

如果没有统一的政策动作模型，所谓“推演”最终只会退化成口头建议或 LLM 改写，无法形成结构化比较。

因此沙盘推演的第一步不是做问答，而是定义 `PolicyInstrument`。

## 二、PolicyInstrument

建议统一如下结构：

```json
{
  "instrument_id": "quota_reduce",
  "instrument_type": "quota_adjustment",
  "target_scope": {},
  "parameters": {},
  "effective_window": {},
  "constraints": {}
}
```

## 三、关键字段

### 1. instrument_type

至少应覆盖：

- `quota_adjustment`
- `eligibility_change`
- `evaluation_weight_change`
- `topic_priority_shift`
- `talent_support`
- `collaboration_incentive`

### 2. target_scope

用于表达作用对象，例如：

- 某类主题
- 某类人才群体
- 某部门或某资金计划

### 3. parameters

用于表达动作强度，例如：

- 配额增加或减少比例
- 权重变化幅度
- 人才支持强度

### 4. constraints

用于表达不能突破的条件，例如：

- 总预算不变
- 总项目数不变
- 某类主题最小保障比例

## 四、政策动作分类

从机制上看，政策动作可分为三类：

1. 入口侧动作
   影响申报和准入
2. 分配侧动作
   影响立项、配额和资源配置
3. 能力侧动作
   影响人才、协作和转化能力

这三类动作的传导路径不同，不能混用一套简单规则。
