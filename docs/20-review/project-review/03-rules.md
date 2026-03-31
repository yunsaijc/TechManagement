# 🧩 规则与配置设计

## 目标

项目级形式审查的规则体系需要同时承载两类规则：

- 附件级规则
- 项目级规则

两者都属于“形式审查”，但作用对象不同，不能混在同一套配置里。

## 现有规则体系

当前代码中的规则体系位于：

- `src/services/review/rules/base.py`
- `src/services/review/rules/registry.py`
- `src/services/review/rules/config.py`
- `src/services/review/rules/checkers/`

当前 `DOCUMENT_CONFIG` 的作用是：

- 为单附件 `document_type` 指定规则列表
- 指定 LLM 提取字段

它适合继续服务于附件级审查。

## 分层规则设计

### 1. 附件级规则

附件级规则继续使用现有 `CheckResult` 作为输出。

当前已存在或已规划的附件级规则包括：

- `signature`
- `stamp`
- `prerequisite`
- `retrieval_report_completeness`
- `work_unit_consistency`

附件级规则的输入对象仍然是单文件上下文，例如现有 `ReviewContext`。

### 2. 项目级规则

项目级规则的输入对象应为 `ProjectReviewContext`。输出仍建议复用现有 `CheckResult`，这样聚合与展示方式可以统一。

项目级规则建议按以下类别组织：

#### 基础资格类

- 注册时间要求
- 申报单位类型要求
- 依托平台范围要求

#### 材料齐套类

- 承诺书是否上传
- 伦理审查意见是否上传
- 行业准入许可是否上传
- 生物安全承诺书是否上传
- 合作协议是否上传
- 推荐函是否上传

#### 条件性附件类

- 涉及临床研究时必须上传伦理审查意见
- 涉及特种行业时必须上传行业准入许可
- 涉及生物安全活动时必须上传生物安全承诺书
- 存在合作单位时必须上传合作协议

#### 项目属性类

- 执行期是否超限
- 财政资金与自筹资金比例是否合规
- 合作单位地区是否符合要求
- 是否存在北京或天津合作单位

#### 外部校验类

- 科研失信
- 社会失信
- 重复申报

## 配置建议

建议新增 `PROJECT_CONFIG`，与现有 `DOCUMENT_CONFIG` 并行存在。

### `DOCUMENT_CONFIG`

继续用于附件级检查，保留当前职责：

- `document_type`
- 附件级规则列表
- LLM 抽取字段

### `PROJECT_CONFIG`

新增用于项目级检查。建议结构如下：

```python
PROJECT_CONFIG = {
    "regional_innovation": {
        "required_project_fields": [...],
        "required_doc_kinds": [...],
        "conditional_doc_rules": [...],
        "project_rules": [...],
        "constraints": {...},
    },
}
```

建议包含以下字段：

| 字段 | 说明 |
|------|------|
| `required_project_fields` | 必填项目字段 |
| `required_doc_kinds` | 必需附件类型 |
| `conditional_doc_rules` | 条件性附件规则 |
| `project_rules` | 项目级规则列表 |
| `constraints` | 执行期、单位类型、地域等约束 |

## 规则命名建议

为了与现有 checker 风格保持一致，项目级规则建议使用稳定英文 code。

例如：

- `registered_date_limit`
- `funding_ratio_check`
- `integrity_check`
- `ethics_material_required`
- `industry_permit_required`
- `biosafety_commitment_required`
- `commitment_letter_required`
- `cooperation_agreement_required`
- `cooperation_region_check`
- `recommendation_letter_required`
- `execution_period_limit`
- `duplicate_submission_check`
- `applicant_unit_type_check`

## 2026 审查要点映射方式

以项目类型为主维度进行映射。

### `regional_innovation`

重点规则：

- 注册时间限制
- 资金比例
- 失信检查
- 条件性伦理材料
- 条件性行业许可
- 条件性生物安全承诺
- 承诺书要求
- 合作协议要求
- 合作单位地区要求
- 推荐函要求
- 执行期上限 2 年
- 重复申报检查

### `innovation_base`

重点规则：

- 注册时间限制
- 资金比例
- 失信检查
- 条件性材料规则
- 承诺书要求
- 合作协议要求
- 依托平台范围
- 基地固定人员证明
- 高校/科研院所与企业联合申报要求
- 执行期上限 2 年
- 重复申报检查

### `achievement_transformation`

重点规则：

- 注册时间限制
- 资金比例
- 失信检查
- 条件性材料规则
- 承诺书要求
- 合作协议要求
- 申报单位必须为企业
- 北京或天津合作单位要求
- 特色产业集群地域要求
- 执行期上限 2 年
- 重复申报检查

### `basic_research`

重点规则：

- 失信检查
- 注册时间限制
- 条件性材料规则
- 承诺书要求
- 合作协议要求
- 执行期上限 3 年
- 重复申报检查

## 复用策略

推荐复用现有规则框架的方式如下：

- 附件级规则继续用现有 `RuleRegistry`
- 项目级规则新增独立 `ProjectRuleRegistry`
- 两类规则都复用 `CheckResult`
- 项目级编排负责调用两套规则并聚合结果

这样可以保持现有风格一致，同时避免把项目级逻辑塞进附件级 checker。
