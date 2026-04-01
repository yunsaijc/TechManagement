# 🧩 规则与配置设计

## 基线

项目级形式审查的规则基线以：

- `/home/tdkx/workspace/data/2026年度中央引导地方形式审查要点.docx`

为准。

当前实现不推翻既有批次审查、附件分类、调试输出和项目级规则链，只做兼容增量：

- 保留现有 `DOCUMENT_CONFIG` 和附件级 `ReviewAgent`
- 保留现有 `PROJECT_CONFIG` 主结构
- 把 `docx` 中四类项目的形式审查要点完整补齐到项目级配置
- 能自动判定的继续自动判定
- 缺数据源或当前不适合自动化的，明确输出待人工复核项

## 分层原则

### 附件级规则

附件级规则继续沿用现有 `review` 子服务，适用于少量明确需要单附件签字、盖章或完整性检查的材料。

当前保留：

- `signature`
- `stamp`
- `prerequisite`
- `retrieval_report_completeness`
- `work_unit_consistency`

但项目级形式审查不再默认把所有附件送入附件级规则链。

### 项目级规则

项目级规则直接对照 `docx` 的形式审查要点组织，按项目类型执行，输出统一的 `CheckResult` 与 `ManualReviewItem`。

项目级规则分为三类：

- `auto`
  说明：当前代码已支持自动判定
- `requires_data`
  说明：规则可自动化，但当前项目上下文或数据源还没补齐
- `manual`
  说明：当前阶段保留人工复核

## docx 规则矩阵

以下矩阵按 `docx` 原文整理，不改写业务含义。

### `regional_innovation`

对应 `区域创新体系建设项目`。

| code | 审查要点 | 当前处理方式 |
|------|------|------|
| `registered_date_limit` | 单位注册时间在 2025 年 1 月 1 日后 | `requires_data` |
| `funding_ratio_check` | 申请财政资金与自筹资金比例不符合申报通知要求 | `requires_data` |
| `external_status_check` | 项目存在科研失信、社会失信 | `auto` |
| `ethics_approval_required` | 涉及开展临床研究，未提交伦理审查意见 | `auto` |
| `industry_permit_required` | 涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料 | `auto` |
| `biosafety_commitment_required` | 涉及生物技术研究、开发、应用以及人类遗传资源相关活动，未提交生物安全承诺书 | `auto` |
| `commitment_letter_required` | 未按要求提交承诺书 | `auto` |
| `cooperation_agreement_required` | 涉及合作单位，承担单位与合作单位未签订正式合作协议（合同）或合作协议不完整不规范 | `requires_data` |
| `cooperation_region_check` | 合作单位非巴州、第二师铁门关市或阿里地区注册的企事业单位 | `requires_data` |
| `recommendation_letter_required` | 申报项目未提供合作方科技管理部门推荐函 | `requires_data` |
| `execution_period_limit` | 执行期超过 2 年 | `auto` |
| `duplicate_submission_check` | 项目重复申报、多头申报 | `auto` |
| `other_policy_compliance` | 其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题 | `manual` |

### `innovation_base`

对应 `科技创新基地项目`。

| code | 审查要点 | 当前处理方式 |
|------|------|------|
| `registered_date_limit` | 单位注册时间在 2025 年 1 月 1 日后 | `requires_data` |
| `funding_ratio_check` | 申请财政资金与自筹资金比例不符合申报通知要求 | `requires_data` |
| `external_status_check` | 项目存在科研失信、社会失信 | `auto` |
| `ethics_approval_required` | 涉及开展临床研究，未提交伦理审查意见 | `auto` |
| `industry_permit_required` | 涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料 | `auto` |
| `biosafety_commitment_required` | 涉及生物技术研究、开发、应用以及人类遗传资源相关活动，未提交生物安全承诺书 | `auto` |
| `commitment_letter_required` | 未按要求提交承诺书 | `auto` |
| `cooperation_agreement_required` | 涉及合作单位，合作协议不完整不规范 | `requires_data` |
| `platform_scope_check` | 依托平台不在申报通知支持范围 | `requires_data` |
| `base_staff_proof_required` | 未将单位出具的基地固定人员证明作为附件上传 | `auto` |
| `joint_application_check` | 主办单位为高校、科研院所等事业单位的，未与企业联合申报 | `requires_data` |
| `execution_period_limit` | 执行期超过 2 年 | `auto` |
| `duplicate_submission_check` | 项目重复申报、多头申报 | `auto` |
| `other_policy_compliance` | 其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题 | `manual` |

### `achievement_transformation`

对应 `科技成果转化项目`。

| code | 审查要点 | 当前处理方式 |
|------|------|------|
| `registered_date_limit` | 单位注册时间在 2025 年 1 月 1 日后 | `requires_data` |
| `funding_ratio_check` | 申请财政资金与自筹资金比例不符合申报通知要求 | `requires_data` |
| `external_status_check` | 项目存在科研失信、社会失信 | `auto` |
| `ethics_approval_required` | 涉及开展临床研究，未提交伦理审查意见 | `auto` |
| `industry_permit_required` | 涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料 | `auto` |
| `biosafety_commitment_required` | 涉及生物技术研究、开发、应用以及人类遗传资源相关活动，未提交生物安全承诺书 | `auto` |
| `commitment_letter_required` | 未按要求提交承诺书 | `auto` |
| `cooperation_agreement_required` | 涉及合作单位，合作协议不完整不规范 | `requires_data` |
| `applicant_unit_type_check` | 申报单位非企业 | `auto` |
| `beijing_tianjin_partner_check` | 京津冀重点产业成果转化项目未有北京或天津合作单位 | `requires_data` |
| `cluster_region_check` | 特色产业集群成果转化与技术攻关项目申报单位注册地非集群所在区域 | `requires_data` |
| `execution_period_limit` | 执行期超过 2 年 | `auto` |
| `duplicate_submission_check` | 项目重复申报、多头申报 | `auto` |
| `other_policy_compliance` | 其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题 | `manual` |

### `basic_research`

对应 `基础研究项目`。

| code | 审查要点 | 当前处理方式 |
|------|------|------|
| `external_status_check` | 项目存在科研失信、社会失信 | `auto` |
| `duplicate_submission_check` | 项目重复申报、多头申报 | `auto` |
| `registered_date_limit` | 单位注册时间在 2025 年 1 月 1 日后 | `requires_data` |
| `ethics_approval_required` | 涉及开展临床研究，未提交伦理审查意见 | `auto` |
| `industry_permit_required` | 涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料 | `auto` |
| `biosafety_commitment_required` | 涉及生物技术研究、开发、应用以及人类遗传资源相关活动，未提交生物安全承诺书 | `auto` |
| `commitment_letter_required` | 未按要求提交承诺书 | `auto` |
| `cooperation_agreement_required` | 涉及合作单位，合作协议不完整不规范 | `requires_data` |
| `execution_period_limit` | 执行期超过 3 年 | `auto` |
| `other_policy_compliance` | 其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题 | `manual` |

## 配置落点

### `PROJECT_CONFIG`

继续作为项目级主配置，保留既有结构：

```python
PROJECT_CONFIG = {
    "regional_innovation": {
        "required_project_fields": [...],
        "required_doc_kinds": [...],
        "conditional_doc_rules": [...],
        "project_rules": [...],
        "constraints": {...},
        "guide_names": [...],
    },
}
```

在此基础上新增：

- `policy_review_points`
  说明：完整承接 `docx` 的逐项规则矩阵
- `constraints.registered_after`
  说明：注册时间红线
- `constraints.allowed_cooperation_regions`
  说明：合作区域限制
- `constraints.requires_beijing_tianjin_partner`
  说明：成果转化项目北京/天津合作方要求
- `constraints.requires_cluster_region_match`
  说明：特色产业集群地域匹配要求
- `constraints.requires_enterprise_joint_application`
  说明：创新基地项目事业单位主办时企业联合申报要求

### `DOCUMENT_CONFIG`

继续保留附件级职责，不以 `docx` 为主配置入口。

## 当前自动化边界

当前代码已经自动覆盖：

- 必填项目字段
- 必需附件
- 条件性附件
- 执行期限制
- 申报单位类型限制
- 失信 / 重复申报等外部状态

当前仍缺数据源或待补实现：

- 单位注册时间
- 财政资金 / 自筹资金比例
- 合作单位注册地区
- 推荐函是否应提交
- 依托平台是否在支持范围
- 高校 / 科研院所主办时的企业联合申报
- 北京 / 天津合作单位要求
- 特色产业集群注册地区要求

这些规则不会被忽略，而应在项目结果中明确标记为：

- 当前未自动核验
- 需要补充字段或外部数据源
- 现阶段建议人工复核

## 兼容原则

文档与代码都遵循以下兼容原则：

- 不移除现有批次入口
- 不移除现有附件 LLM 分类
- 不移除现有 debug 输出
- 不把所有附件重新塞回旧 `ReviewAgent`
- 仅在 `PROJECT_CONFIG` 与项目级规则层补齐 `docx` 对齐能力

这样可以在不浪费现有成果的前提下，把规则基线校正到 `docx`。
