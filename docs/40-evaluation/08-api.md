# 🌐 API 接口文档

## 接口概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/evaluation` | 按 `project_id` 执行融合评审 |
| POST | `/api/v1/evaluation/evaluate` | 同上（别名） |
| POST | `/api/v1/evaluation/evaluate/file` | 上传文件执行融合评审 |
| POST | `/api/v1/evaluation/by-guide` | 按 `zndm` 查询真实项目并批量评审 |
| POST | `/api/v1/evaluation/batch` | 批量评审 |
| POST | `/api/v1/evaluation/chat/ask` | 基于评审结果问答（附页码证据） |
| GET | `/api/v1/evaluation/{project_id}` | 获取最新评审结果 |
| GET | `/api/v1/evaluation/history/{project_id}` | 获取历史结果 |
| GET | `/api/v1/evaluation/dimensions` | 获取评审维度 |
| POST | `/api/v1/evaluation/weights/validate` | 验证权重 |

## 1. 融合评审（project_id）

### 请求

```http
POST /api/v1/evaluation
Content-Type: application/json
```

```json
{
  "project_id": "202520014",
  "dimensions": ["feasibility", "innovation", "team"],
  "weights": {
    "feasibility": 0.2,
    "innovation": 0.2,
    "team": 0.1
  },
  "include_sections": ["技术路线", "创新点"],
  "enable_highlight": true,
  "enable_industry_fit": true,
  "enable_benchmark": true,
  "enable_chat_index": true
}
```

### 响应（示例）

```json
{
  "project_id": "202520014",
  "project_name": "示例项目",
  "overall_score": 8.35,
  "grade": "B",
  "dimension_scores": [],
  "summary": "综合评审意见...",
  "recommendations": [],
  "highlights": {
    "research_goals": ["目标1"],
    "innovations": ["创新点1"],
    "technical_route": ["路线步骤1"]
  },
  "industry_fit": {
    "fit_score": 0.78,
    "matched": ["指南条目A"],
    "gaps": ["缺少产业化路径量化指标"],
    "suggestions": ["补充产线验证数据和时间表"]
  },
  "benchmark": {
    "novelty_level": "medium_high",
    "literature_position": "与近三年同类研究相比具备方法改进",
    "patent_overlap": "存在部分交叉，需要进一步规避设计",
    "conclusion": "技术水平处于国内前列"
  },
  "evidence": [
    {
      "source": "document",
      "file": "申报书.pdf",
      "page": 18,
      "snippet": "关键试验数据..."
    }
  ],
  "chat_ready": true,
  "partial": false,
  "errors": [],
  "created_at": "2026-03-26T10:30:00"
}
```

## 2. 上传文件评审

### 请求

```http
POST /api/v1/evaluation/evaluate/file
Content-Type: multipart/form-data
```

表单字段：

- `file`：Word/PDF 文件
- `project_id`：项目 ID
- `dimensions`：逗号分隔
- `weights`：JSON 字符串
- `enable_highlight` / `enable_industry_fit` / `enable_benchmark` / `enable_chat_index`

### 说明

适用于项目库无文档或临时评审场景，不依赖固定测试目录。

## 3. 批量评审

### 请求

```http
POST /api/v1/evaluation/batch
Content-Type: application/json
```

```json
{
  "project_ids": ["202520014", "202520036"],
  "weights": null,
  "concurrency": 3
}
```

### 响应

返回 `total/success/failed/results/summary/errors`。

## 4. 按指南代码批量评审

### 请求

```http
POST /api/v1/evaluation/by-guide
Content-Type: application/json
```

```json
{
  "zndm": "c2f3b7b1f9534463ad726e6936c91859",
  "limit": 10,
  "enable_highlight": true,
  "enable_industry_fit": false,
  "enable_benchmark": false,
  "enable_chat_index": true,
  "concurrency": 3
}
```

### 说明

- 服务端先按 `zndm` 查询 `Sb_Jbxx + Sb_Sbzt + sys_guide`
- 仅评审 `isSubmit='1'` 的项目
- `limit` 为可选参数；不传则全量，传入时仅处理前 N 个项目
- 正文固定读取：
  - `/mnt/remote_corpus/{year}/sbs/{id}/{id}.docx`

### 响应

返回：
- `zndm`
- `guide_name`
- `total/success/failed`
- `results`
- `errors`

## 5. 专家问答（带证据）

### 请求

```http
POST /api/v1/evaluation/chat/ask
Content-Type: application/json
```

```json
{
  "evaluation_id": "EVAL_20260326_001",
  "question": "验证数据有吗？技术能量产吗？"
}
```

### 响应

```json
{
  "answer": "有验证数据，主要在中试阶段。",
  "citations": [
    {
      "file": "申报书.pdf",
      "page": 18,
      "snippet": "完成三轮中试验证..."
    },
    {
      "file": "申报书.pdf",
      "page": 25,
      "snippet": "量产条件与产线改造计划..."
    }
  ]
}
```

### 说明

- 若该 `evaluation_id` 尚未落盘聊天索引，服务会先自动尝试重建（优先使用 `debug_eval` 中的页切片，其次回源项目文档）
- 仅当自动重建仍失败时，接口返回 `422`（错误信息包含“未构建聊天索引，且无法自动重建”）

## 6. 权重与维度接口

- `GET /api/v1/evaluation/dimensions`
- `POST /api/v1/evaluation/weights/validate`
- `GET /api/v1/evaluation/weights/default`
- `GET /api/v1/evaluation/weights/templates`

## 错误码（建议）

| 错误码 | HTTP状态码 | 说明 |
|--------|-----------|------|
| PROJECT_NOT_FOUND | 404 | 项目不存在 |
| DOCUMENT_NOT_FOUND | 422 | 未找到项目申报文档 |
| INVALID_WEIGHT | 400 | 权重配置无效 |
| PARSE_ERROR | 422 | 文档解析失败 |
| TOOL_UNAVAILABLE | 503 | 搜索工具不可用 |
| INTERNAL_ERROR | 500 | 服务内部错误 |

## 工具调用说明

- 该服务使用模型 API，不会自动执行搜索工具。
- 文献/专利/指南检索由服务端 `ToolGateway` 调度执行。
- 当工具不可用时返回降级结果，并在 `partial/errors` 标记。
