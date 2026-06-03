# 70 Sandbox 总纲

## 一、系统定位

`docs/70-sandbox/` 承载的不是“高级报表”或“聊天问答”，而是一个面向省级科技治理的政策研判系统。

系统统一回答两类问题：

1. `趋势预判`
   如果什么都不改，未来 1-2 个年度周期，省内科研主题、机构、人员和资金结构会怎么演化。
2. `沙盘推演`
   如果调整指南、准入、评审、配额、预算、协作支持等政策，未来结构会怎样不同，谁受益，谁受损，代价是什么。

一句话概括：

`真实数据驱动的政策研判系统 + 在必要环节引入 LLM 做理解、归纳、解释和交互`

## 二、顶层方法论

本系统采用统一方法论：

`Data-first, Rule-and-Model-driven, LLM-assisted`

含义如下：

- `Data-first`
  一切结论先受现有项目库和图谱数据约束，不能由 LLM 编故事补空缺。
- `Rule-and-Model-driven`
  指标、口径、状态转移、推演约束都先由规则、统计和图算法定义。
- `LLM-assisted`
  LLM 用于理解领导问题、生成结构化方案、归纳证据、组织解释和支持追问，不直接替代核心业务计算。

## 三、现有数据底座

当前系统的真实底座来自两部分：

### 1. 项目库

- `Sb_Jbxx`：申报主表
- `Sb_Sbzt`：申报状态/公开状态
- `Sb_Jfgs`：申报经费
- `PS_XMPSXX`：评审过程、评分、排名、是否进入各阶段
- `Ht_XMLXXX`：立项事实
- `Ht_Jbxx`：合同事实
- `Ht_Jfgs`：合同经费

项目库的主业务链应视为：

`申报 -> 评审 -> 立项 -> 合同 -> 经费兑现`

### 2. 图谱

图谱提供以下结构增强能力：

- `Project / Topic / Institution / Person / Output / Fund` 等节点关系
- 主题迁移
- 协作密度
- 主题中心性
- 人员桥接性
- 主题间结构关联强度

图谱结果默认是“结构代理”，不能直接冒充业务事实。

## 四、业务本体

不能把整个系统压成一个 `topic × year` 报表。

`topic × year` 只是统计层宽表，不是业务本体。

最终底座必须分三层：

### 1. 事实层

只存真实业务事实，不做解释。

- `Project`
- `Review`
- `Funding(requested / awarded / contracted / disbursed)`
- `Contract`
- `Acceptance`
- `Transformation`

### 2. 关系层

承载主题、机构、人员在图谱中的连接。

- `Topic`
- `Institution`
- `Person`
- `Topic-Topic`
- `Institution-Institution`
- `Person-Project`
- `Project-Topic`

### 3. 统计层

在事实层与关系层之上构建面板。

- `topic × year`
- `topic × institution × year`
- `topic × person × year`
- `project_cohort_outcome`

## 五、系统对象

最终系统围绕以下核心对象展开：

- `Topic`
  政策/指南方向，优先使用 `zndm / guide_name` 等稳定口径。
- `Project`
  全生命周期主实体，主键锚定 `Sb_Jbxx.id`。
- `Institution`
  承担单位/合作单位。
- `Person`
  负责人/参与人，区分 PI 与参与人员。
- `Review`
  评审事件，而不是项目静态属性。
- `Funding`
  经费事件，必须拆分申报、立项、合同、拨付。
- `Contract`
  立项后的合同事实。
- `Acceptance / Transformation`
  保留为一级对象，但在当前数据条件下不能假装已经完整可用。

## 六、项目在系统中的角色

项目不是领导最终看的主对象，但它是所有结论的证据颗粒。

正确链路为：

`项目事实 -> 主题状态 -> 组合结构 -> 趋势判断 / 风险预警 / 政策推演`

因此：

- 领导页不直接围绕“单项目”组织
- 所有结论都必须能追溯回项目层证据

## 七、Trend 与 Simulation 的关系

两者不是两个孤立模块，而是同一底座上的两种推理模式。

### 1. Trend

`Trend = Baseline World Forecast`

它回答：

- 不干预时，未来会怎么演化
- 哪些主题在升温、回落、迁移、空心化、风险累积

### 2. Simulation

`Simulation = Counterfactual Policy Scenario`

它回答：

- 如果施加某组政策动作，未来会怎样不同
- 谁受益、谁受损、谁被挤出、代价是什么

关系如下：

```text
项目事实 + 图谱关系
  -> Trend：形成 baseline world
  -> Simulation：在 baseline 上施加政策动作
  -> 领导简报 / 追问交互 / 决策支持
```

## 八、政策沙盘的正式定义

沙盘不是页面，也不是动画，而是一份严格的情景合同：

`Sandbox = Baseline World + Policy Package + Constraints + Evaluation Goals + Assumptions`

其中：

- `Baseline World`
  当前真实状态及其自然延续
- `Policy Package`
  结构化政策动作集合
- `Constraints`
  预算、配额、风险、合规边界
- `Evaluation Goals`
  领导这次要优化什么
- `Assumptions`
  哪些是观测、哪些是代理、哪些是结构假设

## 九、证据边界

系统必须显式区分三层表达：

1. `事实层`
   已观测到的真实变化
2. `解释层`
   基于规则、统计和图结构的机制解释
3. `推演层`
   在明确政策假设下的条件性结果

必须避免：

- 把相关性说成因果
- 把条件推演说成确定预测
- 把代理变量说成真实结果
- 把内部项目数据等同于全省全社会现实

## 十、LLM 的职责边界

LLM 必须使用，但职责要受限。

### 1. 应使用的场景

- 领导自然语言问题解析
- 政策语言 -> 结构化 `Scenario Contract`
- 多指标、多证据结果归纳
- 领导简报生成
- 多轮追问与可追溯解释

### 2. 不应使用的场景

- 直接计算核心业务指标
- 编造缺失数据
- 替代 cohort、统计与图算法
- 直接下强因果结论

## 十一、文档组织

- `overview/`
  顶层定位、术语、状态变量、政策动作、结果边界
- `trend/`
  趋势预判的对象、输入输出、分析链路与交付
- `simulation/`
  沙盘推演的政策输入、状态转移、输出与边界
- `archive/`
  历史探索材料，不再作为主设计入口
