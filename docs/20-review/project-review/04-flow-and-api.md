# 🔄 执行流程与接口草案

## 执行流程

项目级形式审查建议采用以下执行顺序。

### 第一步：接收项目输入

接收：

- `project_info`
- `cooperation_info`
- `attachments`
- `external_checks`

并组装成 `ProjectReviewContext`。

### 第二步：材料齐套性预检查

根据 `project_type` 和 `PROJECT_CONFIG`，先判断：

- 必填项目字段是否缺失
- 必需附件类型是否缺失
- 条件满足时是否缺少条件性附件

这一阶段不依赖 OCR 和 LLM，可以快速发现明显问题。

### 第三步：附件分发审查

对已上传附件按 `doc_kind` 进行分发，并映射到附件级 `document_type`。

每个附件调用一次现有 `ReviewAgent.process(...)`，产出 `ReviewResult`。

这一阶段直接复用当前已实现的：

- `src/app/routes/review.py`
- `src/services/review/agent.py`
- `src/services/review/rules/config.py`

### 第四步：项目级规则执行

汇总：

- 项目基础字段
- 附件清单
- 附件级审查结果
- 外部校验结果

再执行项目级规则，生成项目级 `CheckResult` 列表。

### 第五步：结果聚合

输出 `ProjectReviewResult`，其中包含：

- 总体结论
- 项目级规则结果
- 缺失附件列表
- 附件级审查结果
- 建议和待人工复核项

## 参考流程图

```text
ProjectReviewRequest
  -> build ProjectReviewContext
  -> validate required fields
  -> validate required attachments
  -> dispatch attachments to ReviewAgent
  -> collect ReviewResult list
  -> run project rules
  -> build ProjectReviewResult
```

## 与现有接口的关系

### 当前已实现接口

当前已实现的附件级接口为：

- `POST /api/v1/review`
- `GET /api/v1/review/{review_id}`
- `GET /api/v1/review/document-types`
- `GET /api/v1/review/check-items`

这些接口继续保留，用于：

- 单附件调试
- 附件级能力复用
- 项目级编排内部调用

### 新增项目级接口建议

建议新增独立项目级入口，例如：

```text
POST /api/v1/review/projects
GET  /api/v1/review/projects/{project_review_id}
GET  /api/v1/review/project-types
```

说明：

- `POST /api/v1/review` 继续表示附件级入口
- `POST /api/v1/review/projects` 表示项目级入口
- 这样路径语义清晰，且对现有调用方影响最小

## 请求体草案

建议项目级接口使用 `application/json`。

```json
{
  "project_info": {
    "project_id": "2026-001",
    "project_type": "regional_innovation",
    "project_name": "示例项目",
    "applicant_unit": "某单位",
    "applicant_unit_type": "enterprise",
    "registered_date": "2020-05-01",
    "execution_period_years": 2,
    "fiscal_funding": 100,
    "self_funding": 200,
    "has_clinical_research": false,
    "has_special_industry_requirement": false,
    "has_biosafety_activity": false,
    "has_cooperation_unit": true
  },
  "cooperation_info": {
    "cooperation_units": ["某合作单位"],
    "cooperation_regions": ["北京"],
    "has_formal_cooperation_agreement": true,
    "has_management_recommendation_letter": true
  },
  "attachments": [
    {
      "attachment_id": "att-1",
      "doc_kind": "commitment_letter",
      "file_name": "承诺书.pdf",
      "file_ref": "object://bucket/commitment.pdf",
      "document_type": "acceptance_report",
      "required": true
    }
  ],
  "external_checks": {
    "integrity_status": "passed",
    "social_credit_status": "passed",
    "duplicate_submission_status": "passed",
    "applicant_region": "河北"
  }
}
```

## 响应体草案

```json
{
  "status": "success",
  "data": {
    "id": "project_review_001",
    "project_id": "2026-001",
    "project_type": "regional_innovation",
    "results": [
      {
        "item": "execution_period_limit",
        "status": "passed",
        "message": "执行期符合要求",
        "evidence": {},
        "confidence": 1.0
      }
    ],
    "missing_attachments": [],
    "attachment_results": [],
    "summary": "项目形式审查完成",
    "suggestions": [],
    "processing_time": 1.2
  }
}
```

## 模块建议

为尽量复用现有代码，建议新增项目级模块而不是改写附件级模块。

推荐新增：

- `src/services/review/project_agent.py`
- `src/services/review/project_rules/`
- `src/app/routes/project_review.py`

其中：

- `project_agent.py` 负责项目级编排
- `project_rules/` 负责项目级规则
- `project_review.py` 提供项目级 API

现有 `src/services/review/agent.py` 保持附件级职责。

## 最小改造原则

项目级形态的第一阶段实现应遵循以下原则：

- 不修改现有附件级接口语义
- 不把项目级逻辑塞进现有 `ReviewAgent`
- 项目级结果复用现有 `CheckResult`
- 附件级结果直接复用现有 `ReviewResult`

这样可以在最小风险下完成能力扩展，并保持文档和实现一致。
