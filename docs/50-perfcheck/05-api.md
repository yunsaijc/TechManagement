# API 接口文档

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | /api/v1/perfcheck |
| 请求格式 | multipart/form-data 或 application/json |
| 响应格式 | JSON（ApiResponse） |

## 已实现接口

### 1. 同步文件比对

POST /api/v1/perfcheck/compare

表单参数：

- declaration_file（必填）
- task_file（必填）
- project_id（必填）
- budget_shift_threshold（默认 0.10）
- strict_mode（默认 true）
- enable_llm_enhancement（默认 false）
- enable_table_vision_extraction（默认 true）
- enable_llm_entailment（默认 true）

返回 PerfCheckResult。

请求示例：

```bash
curl -X POST "http://localhost:8000/api/v1/perfcheck/compare" \
	-F "declaration_file=@tests/申报书/demo.docx" \
	-F "task_file=@tests/任务书/demo.docx" \
	-F "project_id=perfcheck_demo" \
	-F "budget_shift_threshold=0.10"
```

响应示例：

```json
{
	"status": "success",
	"code": 200,
	"message": "核验完成",
	"data": {
		"project_id": "perfcheck_demo",
		"task_id": "abcd1234",
		"metrics_risks": [],
		"content_risks": [],
		"budget_risks": [],
		"other_risks": [],
		"unit_budget_risks": [],
		"warnings": [],
		"summary": ""
	}
}
```

### 2. 异步文件比对

POST /api/v1/perfcheck/compare-async

参数同 compare，返回 PerfCheckTask（state=running）。

### 3. 同步文本比对

POST /api/v1/perfcheck/compare-text

请求体模型 PerfCheckRequest：

- declaration_text
- task_text
- project_id
- budget_shift_threshold
- strict_mode
- enable_llm_enhancement
- enable_table_vision_extraction
- enable_llm_entailment

返回 PerfCheckResult。

请求示例：

```json
{
	"project_id": "perfcheck_demo",
	"declaration_text": "...",
	"task_text": "...",
	"budget_shift_threshold": 0.10,
	"strict_mode": true,
	"enable_llm_enhancement": false,
	"enable_table_vision_extraction": true,
	"enable_llm_entailment": true
}
```

### 4. 异步文本比对

POST /api/v1/perfcheck/compare-text-async

请求体同 compare-text，返回 PerfCheckTask。

### 5. 默认样例异步比对

POST /api/v1/perfcheck/compare-default-async

用于本地默认 PDF 样例调试。

### 6. 任务状态查询

GET /api/v1/perfcheck/{task_id}

返回 PerfCheckTask。

### 7. 报告获取

GET /api/v1/perfcheck/{task_id}/report?format=markdown|json

- format=markdown：返回 PerfCheckReporter 生成的 Markdown
- format=json：返回 PerfCheckResult 的 JSON 文本

## 主要响应模型

### PerfCheckResult

- project_id
- task_id
- metrics_risks
- content_risks
- budget_risks
- other_risks
- unit_budget_risks
- warnings
- summary

### PerfCheckTask

- task_id
- project_id
- state（running/finished/failed）
- progress
- stage
- error_code
- message
- summary
- result

## 错误处理

路由层使用 HTTPException 返回错误；异步任务内部将异常归一为 error_code。

常见 error_code：

- LLM_TIMEOUT
- TASK_CANCELLED
- UNKNOWN_ERROR

## 错误码说明

| 场景 | HTTP 状态码 | 说明 |
|------|-------------|------|
| 参数错误 | 400 | 文件为空、format 非法等 |
| 资源不存在 | 404 | task_id 不存在、默认样例文件不存在 |
| 业务校验失败 | 422 | 解析或输入校验失败 |
| 服务异常 | 500 | compare 执行失败或任务提交失败 |