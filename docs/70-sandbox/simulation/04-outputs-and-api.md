# 推演输出与 API

## 一、输出目标

simulation 的输出不应只是“一张变化图”，而应是一套完整的反事实比较结果：

- `baseline 是什么`
- `scenario 做了什么`
- `治理流程各环节发生了什么变化`
- `哪些变化可信，哪些只是代理`
- `最终能给领导什么决策结论`

## 二、标准输出包

建议统一输出如下结构：

```json
{
  "meta": {},
  "baseline": {},
  "scenario": {},
  "stage_impacts": {},
  "counterfactual_comparison": {},
  "portfolio_assessment": {},
  "evidence_chain": [],
  "disclosures": {}
}
```

## 三、输出内容必须分层

### 1. baseline

描述未干预时的参考世界：

- 基线年份与预测窗口
- 主题结构
- 申报、评审、立项、合同的核心状态
- 图谱结构代理状态

### 2. scenario

描述本次政策场景本身：

- 政策包
- 生效时间
- 约束条件
- 评估目标
- 关键假设

### 3. stage_impacts

按治理流程展示变化，而不是直接只看最终结果：

- `application_response`
- `review_selection`
- `award_contract`
- `structural_spillover`

每一层都应能回答：

- 哪些主题变化最大
- 变化方向是什么
- 变化由哪条规则触发
- 该变化属于观测、代理还是结构假设

### 4. counterfactual_comparison

直接给出 baseline 与 scenario 的核心差值：

- 项目数变化
- 立项数变化
- 合同专项经费变化
- 主题份额变化
- 评审压力变化
- 风险变化

### 5. portfolio_assessment

面向领导的组合级结论：

- 谁受益
- 谁受损
- 谁被挤出
- 资源向哪里转移
- 风险是否迁移
- 是否满足既定约束与评估目标

### 6. evidence_chain

每个关键结论都必须能回溯：

- 依赖哪些业务表
- 依赖哪些图谱指标
- 经过了哪些规则
- 包含哪些关键假设

### 7. disclosures

必须强制披露：

- 数据覆盖年限
- 覆盖对象数
- 主题口径
- 样本不足项
- 代理指标清单
- 不支持结论清单

## 四、领导可见的核心结果对象

领导最终看到的不是数据库对象名，而是以下几类结果对象：

- `局势概览`
- `基线判断`
- `方案摘要`
- `变化路径`
- `受益与受损`
- `资源挤出`
- `结构风险`
- `证据与边界`

其中“变化路径”必须围绕治理流程展开，而不是只堆结果值。

## 五、结果表达边界

### 1. 可以作为硬结果展示

- 申报项目数及占比变化
- 评审边界代理变化
- 立项数量变化
- 合同专项经费变化
- 主题预算份额变化
- 图谱结构代理变化

### 2. 只能作为代理结果展示

- 协作增强或减弱
- 主题迁移增强或减弱
- 结构集中度风险变化
- 人员活跃度变化

这些结果必须显式打上 `proxy` 标签。

### 3. 不能直接生成的结论

- 真实验收率升降
- 真实成果转化率升降
- 全省人才断层是否被修复
- 某政策一定带来产业收益

这类内容如被领导提问，只能进入“当前数据不支持”或“仅能用代理解释”的响应。

## 六、API 设计原则

API 不应围绕旧的 `step1/step2` 或单个临时参数命名，而应围绕正式能力命名。

建议保留在：

- `/api/v1/sandbox/simulation/...`

之下。

## 七、建议接口

### 1. `POST /api/v1/sandbox/simulation/scenario/compose`

用途：

- 接收领导自然语言或半结构输入
- 输出标准化 `Scenario Contract`
- 返回不支持项与待确认项

输入应至少包含：

- `intent`
- `baseline_scope`
- `raw_policy_text` 或半结构动作

输出应至少包含：

- `scenario_contract`
- `validation`
- `normalization_notes`

### 2. `POST /api/v1/sandbox/simulation/run`

用途：

- 执行正式推演

输入：

- `baseline_id`
- `scenario_contract`
- `compare_to_baseline`

输出：

- `run_id`
- `stage_impacts`
- `counterfactual_comparison`
- `portfolio_assessment`
- `disclosures`

### 3. `GET /api/v1/sandbox/simulation/runs/{run_id}`

用途：

- 获取一次推演的完整结果与审计信息

### 4. `POST /api/v1/sandbox/simulation/compare`

用途：

- 比较多个场景

输入：

- `baseline_id`
- `scenario_ids`
或
- 多个内联 `scenario_contract`

输出：

- 多场景差异对照
- 共同受益项
- 共同代价项
- 约束满足情况

### 5. `POST /api/v1/sandbox/simulation/explain`

用途：

- 对已有 run 结果做追问解释

输入：

- `run_id`
- `question`

输出：

- 证据引用
- 规则链路
- 代理与限制说明

## 八、错误处理原则

以下情况应返回明确错误，而不是静默给图：

- `baseline_scope` 无法映射到真实数据范围
- 场景动作互相冲突
- 预算或配额约束不可满足
- 关键输出依赖的数据缺失
- 用户请求了当前数据不支持的硬结论

建议使用清晰的错误类型：

- `INVALID_SCENARIO_CONTRACT`
- `UNSUPPORTED_POLICY_ACTION`
- `INSUFFICIENT_EVIDENCE`
- `CONSTRAINT_VIOLATION`
- `UNSUPPORTED_CLAIM`

## 九、输出审计要求

每一次 run 至少要可追溯以下内容：

- 用了哪版 baseline
- 用了哪版数据
- 用了哪版规则
- 哪些结果受图谱代理驱动
- 哪些结果主要受假设驱动

没有这些审计信息，页面再好看也只是不可复算的展示层。
