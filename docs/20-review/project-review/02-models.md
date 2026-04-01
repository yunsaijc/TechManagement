# 🧱 输入输出模型

## 目标

项目级形式审查不再以“单文件 + 任意 metadata”为输入，而是以**批次查询结果 + 完整项目上下文**为输入。这样可以同时承载：

- 批次标识
- 项目基础字段
- 附件清单
- 附件级审查结果
- 外部系统校验结果

## 现有可复用模型

当前代码中已存在的单附件结果模型位于 `src/common/models/review.py`：

- `CheckStatus`
- `CheckResult`
- `ReviewResult`

这些模型继续用于**附件级形式审查**，不需要废弃。

## 新增模型建议

项目级形式审查建议新增以下模型。

## 批次入口模型

### `BatchReviewRequest`

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `zxmc` | `str` | 批次标识 |

### `ProjectIndexRow`

表示从数据库项目列表查询得到的一条记录。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | `str` | 对应 `sbxx.id` |
| `year` | `str` 或 `int` | 对应 `sbxx.year` |
| `project_name` | `str` | 对应 `sbxx.xmmc` |
| `guide_name` | `str` | 对应 `zn.name` |

### `ProjectInfo`

表示项目基础信息。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | `str` | 项目唯一标识 |
| `project_type` | `str` | 项目类型，例如 `regional_innovation` |
| `project_name` | `str` | 项目名称 |
| `applicant_unit` | `str` | 申报单位 |
| `applicant_unit_type` | `str` | 单位类型，例如企业、高校、科研院所 |
| `registered_date` | `date` 或 `str` | 注册时间 |
| `execution_period_years` | `float` | 执行期 |
| `fiscal_funding` | `float` | 申请财政资金 |
| `self_funding` | `float` | 自筹资金 |
| `has_clinical_research` | `bool` | 是否涉及临床研究 |
| `has_special_industry_requirement` | `bool` | 是否涉及安全生产等特种行业 |
| `has_biosafety_activity` | `bool` | 是否涉及生物安全相关活动 |
| `has_cooperation_unit` | `bool` | 是否存在合作单位 |

### `CooperationInfo`

表示合作单位信息。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `cooperation_units` | `list[str]` | 合作单位名称列表 |
| `cooperation_regions` | `list[str]` | 合作单位注册地区列表 |
| `has_formal_cooperation_agreement` | `bool` | 是否存在正式合作协议 |
| `has_management_recommendation_letter` | `bool` | 是否存在科技管理部门推荐函 |

### `ProjectAttachment`

表示项目中的一个附件。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `attachment_id` | `str` | 附件唯一标识 |
| `doc_kind` | `str` | 附件业务类型，无法识别时使用 `unknown_attachment` |
| `file_name` | `str` | 文件名 |
| `file_ref` | `str` | 文件引用，例如存储路径、对象键、上传标识 |
| `document_type` | `str \| None` | 供附件级审查使用的 `document_type` |
| `required` | `bool` | 是否为必需附件 |
| `recognition_confidence` | `float` | 附件类型识别置信度 |

说明：

- `doc_kind` 是项目级材料识别维度
- `document_type` 是附件级审查维度
- 两者应分离，不应混用
- 在附件文件名乱码且无元数据时，`doc_kind` 应允许退化为 `unknown_attachment`

### `ExternalChecks`

表示外部系统校验结果。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `integrity_status` | `str` | 科研失信检查结果 |
| `social_credit_status` | `str` | 社会失信检查结果 |
| `duplicate_submission_status` | `str` | 重复申报检查结果 |
| `applicant_region` | `str` | 申报单位注册地区 |
| `extra` | `dict` | 扩展字段 |

### `ProjectReviewContext`

项目级规则执行上下文。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_info` | `ProjectInfo` | 项目基础信息 |
| `cooperation_info` | `CooperationInfo \| None` | 合作单位信息 |
| `attachments` | `list[ProjectAttachment]` | 附件列表 |
| `attachment_results` | `dict[str, ReviewResult]` | 已跑过的附件级结果，以 `attachment_id` 为键 |
| `external_checks` | `ExternalChecks \| None` | 外部校验结果 |
| `project_index_row` | `ProjectIndexRow \| None` | 原始项目索引记录 |

## 结果模型建议

### `MissingAttachment`

表示缺失附件。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_kind` | `str` | 缺失的附件类型 |
| `reason` | `str` | 缺失原因 |

只有在附件类型识别可靠时，才应输出该模型。

### `ManualReviewItem`

表示待人工复核项。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `item` | `str` | 复核项编码 |
| `message` | `str` | 复核说明 |
| `evidence` | `dict` | 证据 |

### `ProjectReviewResult`

表示项目级形式审查结果。建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 项目审查 ID |
| `project_id` | `str` | 项目 ID |
| `project_type` | `str` | 项目类型 |
| `results` | `list[CheckResult]` | 项目级规则结果 |
| `missing_attachments` | `list[MissingAttachment]` | 缺失附件列表 |
| `attachment_results` | `list[ReviewResult]` | 附件级审查结果 |
| `manual_review_items` | `list[ManualReviewItem]` | 待人工复核项 |
| `summary` | `str` | 项目级总结 |
| `suggestions` | `list[str]` | 建议 |
| `processed_at` | `datetime` | 处理时间 |
| `processing_time` | `float` | 总耗时 |

## 关系说明

模型之间的关系应为：

```text
ProjectReviewContext
  -> project_index_row
  -> project_info
  -> cooperation_info
  -> attachments
  -> attachment_results
  -> external_checks

ProjectReviewResult
  -> 项目级 CheckResult 列表
  -> 缺失附件列表
  -> 附件级 ReviewResult 列表
  -> 待人工复核项
```

## 与现有实现的衔接

项目级模型不会替换现有 `ReviewResult`，而是包装它。

推荐做法：

- 现有 `/api/v1/review` 保持不变
- 批次入口只接收 `zxmc`
- 项目级编排先查库拿 `id/year/xmmc/guide_name`
- 再按 `/mnt/remote_corpus/{year}/sbs/{project_id}` 与 `/mnt/remote_corpus/{year}/sbsfj/{project_id}` 扫描目录
- 仅对可识别附件调用现有 `ReviewAgent.process(...)`
- `ProjectReviewResult.attachment_results` 直接承接现有 `ReviewResult`
