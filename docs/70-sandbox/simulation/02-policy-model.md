# 反事实政策场景模型

## 一、定位

`Simulation` 的正式定义是：

`在同一 baseline world 上，对比不同政策场景下未来治理结果会如何改变`

因此这里建模的不是零散参数，也不是 `funding_boost` 一类的玩具式参数游戏，而是一份正式的 `Scenario Contract`。

一份可执行的政策场景，必须同时包含：

- `policy_package`
- `constraints`
- `evaluation_goals`
- `assumptions`
- `validation`

缺少其中任一部分，都不能称为正式推演输入。

## 二、Scenario Contract

建议统一采用如下结构：

```json
{
  "scenario_id": "sim_2026_priority_rebalance",
  "scenario_name": "收紧过热主题并向重点方向重配",
  "intent": {
    "question": "如果明年压缩过热低效主题，并把额度向重点方向倾斜，结构会怎样变化",
    "decision_context": "年度指南与预算统筹"
  },
  "baseline_scope": {
    "anchor_year": 2025,
    "forecast_years": [2026, 2027],
    "topic_scope": ["guide_topics"],
    "program_scope": ["province_plan"],
    "population_scope": "公开申报且能关联评审与合同链路的项目"
  },
  "basis_documents": [],
  "policy_package": [],
  "constraints": [],
  "evaluation_goals": [],
  "assumptions": [],
  "validation": {
    "observed_metrics": [],
    "proxy_metrics": [],
    "unsupported_claims": []
  }
}
```

这里的 `basis_documents` 不是第六个治理对象，而是对 `policy_package / constraints / assumptions / validation` 的统一证据支撑层。

如果没有这层，系统就会退回：

- 用口头描述代替正式指南
- 用主观理解代替管理办法约束
- 用页面文案代替可追溯证据

建议 `basis_documents` 结构至少包括：

```json
[
  {
    "document_id": "article_326",
    "document_type": "guide",
    "title": "关于印发2022年度河北省省级科技计划基础研究专项（自然科学基金）项目申报指南的通知",
    "publish_date": "2022-01-28",
    "source_system": "sys_article",
    "support_scope": ["policy_package", "constraints"],
    "link_keys": {
      "year": 2022,
      "program_name": "基础研究专项（自然科学基金）",
      "guide_code_hint": "1010101"
    }
  }
]
```

## 三、正式文本依据层

正式文本依据层的作用不是把文章原文直接送进引擎，而是先把原始文本归一化为可引用对象。

建议来源先包括：

- `sys_article` 中标题命中“指南”的正式通知与指南文本
- `sys_menu` 为“政策 / 管理办法”相关栏目下的正式规则文本

进入 `Scenario Contract` 前，至少应完成：

1. 文档分型
   区分 `guide / policy / management_rule / notice / interpretation`
2. 内容分型
   区分 `html / external_url / pdf_embed / image_only`
3. 关联键抽取
   抽取年份、专项、项目类型、指南代码、阶段词、约束词
4. 去重
   解决同标题在多个栏目重复挂载的问题

如果跳过这一步，直接把 raw 文本或 SQL 结果塞进 `Scenario Contract`，那只是把 toy prompt 包装成正式输入。

## 四、政策动作的最小语义单元

`policy_package` 由多个政策动作组成，但动作本身不再单独作为系统主叙事对象。动作只是 `Scenario Contract` 中的组成件。

每个动作至少需要以下字段：

```json
{
  "action_id": "review_threshold_raise_battery",
  "stage": "review_selection",
  "action_type": "threshold_adjustment",
  "target_scope": {
    "topic_ids": ["solid_state_battery"]
  },
  "rule": {
    "operator": "raise_to_percentile",
    "value": 0.85
  },
  "effective_window": {
    "start_year": 2026,
    "end_year": 2026
  },
  "support_level": "proxy_supported",
  "basis_document_ids": ["article_326"],
  "evidence_requirement": [
    "PS_XMPSXX score distribution",
    "historical funded boundary"
  ]
}
```

核心字段说明：

- `stage`
  动作作用于治理流程的哪个环节。
- `action_type`
  动作属于哪类治理抓手。
- `target_scope`
  明确作用主题、指南、专项、主体群体或项目范围。
- `rule`
  用规则表达动作内容，而不是写主观描述。
- `support_level`
  标记当前数据下是强支持、代理支持还是不支持。
- `basis_document_ids`
  标记该动作引用了哪些正式指南、政策或管理办法。
- `evidence_requirement`
  指明动作成立需要哪些历史证据或规则依据。

## 五、政策动作必须围绕治理流程定义

所有动作都必须落到真实治理流程上，而不是直接改最终结果变量。

### 1. 申报响应

影响“谁来报、报多少、报多大”的动作，例如：

- 指南范围收紧或放宽
- 申报资格门槛变化
- 单项目申报额度上限
- 某类主题的优先申报导向

### 2. 评审选择

影响“谁过线、谁入选、谁被挤出”的动作，例如：

- 评审阈值调整
- 排序规则调整
- 主题保底/限额
- 分数段门槛

### 3. 立项/合同配置

影响“立项后资源如何分配”的动作，例如：

- 主题预算重分配
- 单项目资助强度调整
- 配额增减
- 合同经费上限/下限

### 4. 结构外溢

影响“组合结构如何再演化”的动作或后果，例如：

- 协作导向增强
- 主题间迁移加强或减弱
- 头部集中度变化

这一层只能作为前面三层传导后的派生结果，不能跳过前序流程单独硬算。

## 六、当前真实数据下的政策动作支持边界

当前可用主链路为：

`Sb_Jbxx -> Sb_Sbzt -> Sb_Jfgs -> PS_XMPSXX -> Ht_XMLXXX -> Ht_Jbxx -> Ht_Jfgs`

并辅以图谱关系数据与正式文本依据层。

这里的正式文本依据层主要提供：

- 指南收紧、放宽、优先导向的文本依据
- 管理办法中的预算、配额、资助强度、适用范围约束
- 当前政策 regime 的边界披露

基于这套数据，动作支持程度应明确分层。

### 1. 强支持

可直接进入正式推演：

- `quota_adjustment`
- `budget_reallocation`
- `budget_cap / budget_floor`
- `priority_shift`
- `review_threshold_adjustment`
- `score_band_gate`

原因是这些动作都能直接映射到申报、评审、立项或合同配置链路。

### 2. 代理支持

可以进入场景，但必须披露代理性质：

- `collaboration_guidance`
- `topic_linkage_strengthen`
- `institution_diversification_guidance`
- `review_quality_preference`

这类动作往往依赖图谱结构、评分分位或结构规则，而非完整业务事实。

### 3. 当前不支持

不能作为领导级硬推演结论来源：

- 真实验收规则调整后的结果
- 真实转化激励后的经济产出
- 全省人才供给断层的直接判断
- 区域定向政策的真实效果
- 外部产业/舆情冲击导致的强因果结果

可以把这些内容写进 `assumptions` 或 `unsupported_claims`，但不能假装已被当前数据严格识别。

## 七、evaluation_goals 不是装饰字段

没有明确的评估目标，推演无法判断方案优劣。

建议 `evaluation_goals` 至少覆盖以下几类之一：

- 提升重点主题的立项份额
- 压缩过热低效主题的预算占比
- 降低结构集中度风险
- 控制挤出效应
- 保持总预算或总项目数约束下的结构优化

示例：

```json
[
  {
    "metric": "priority_topic_funded_share",
    "direction": "maximize"
  },
  {
    "metric": "structural_concentration_risk",
    "direction": "minimize"
  },
  {
    "metric": "total_contract_funding",
    "direction": "hold"
  }
]
```

## 八、assumptions 必须显式化

当前数据无法把所有机制都识别成强因果，因此 `assumptions` 是正式输入的一部分，不是备注。

典型假设包括：

- 指南收紧会抑制部分边缘申报进入
- 评审阈值上移会优先挤出低分尾部项目
- 预算重分配会改变不同主题的合同经费占比
- 项目组合变化会通过图谱关系带来协作密度和主题迁移的二阶变化

每条假设都必须标记：

- `assumption_type`
- `mechanism_scope`
- `confidence_level`
- `supported_by`

其中 `supported_by` 可以引用：

- 历史事实指标
- 图谱代理指标
- `basis_documents` 中的正式文本对象

## 九、LLM 在政策建模中的职责

LLM 可以做：

- 把领导自然语言意图解析成 `Scenario Contract`
- 补全动作说明、约束和评估目标的结构化字段
- 检查动作之间是否互相冲突

LLM 不能做：

- 直接生成不存在的数据
- 直接决定动作效果大小
- 把弱代理包装成强证据
- 直接把原始文章正文改写成引擎规则

## 十、建模纪律

后续任何 simulation 设计都必须遵守以下顺序：

1. 先定义 `baseline_scope`
2. 再归一化 `basis_documents`
3. 再定义 `policy_package`
4. 再定义 `constraints`
5. 再定义 `evaluation_goals`
6. 再定义 `assumptions`
7. 最后定义 `validation`

如果一开始就只给一组松散参数，那么得到的只会是不可审计的“参数游戏”，不是政策推演。
