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
| POST | `/api/v1/evaluation/chat/ask-stream` | 基于评审结果流式问答（SSE） |
| POST | `/api/v1/evaluation/chat/citation-highlight` | 按引用懒加载正文高亮 |
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
  "enable_industry_fit": false,
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
  "benchmark": {
    "novelty_level": "medium_high",
    "literature_position": "与近三年同类研究相比具备方法改进",
    "patent_overlap": "专利对比待接入",
    "conclusion": "当前公开论文对比显示技术方案具备一定比较优势"
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
- 当前建议：`enable_industry_fit=false`，因为指南正文尚未形成可靠可核验的数据源

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
- 当前批量真实评审建议默认关闭 `enable_industry_fit`

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
- `chat/ask` 主链路只返回 `answer + citations(file/page/snippet)`，以降低响应延迟
- 正文高亮通过 `/chat/citation-highlight` 懒加载补全，前端在用户点击具体证据时再请求 `packet_page/highlight_rects`

## 7. 搜索能力约束

- `guide_search`：当前未作为正式能力启用
- `tech_search`：当前先接 OpenAlex 公开论文检索
- 专利对比：暂未接入，相关字段会明确返回“专利对比待接入”，而不是输出误导性否定结论

## 6. 专家流式问答

### 请求

```http
POST /api/v1/evaluation/chat/ask-stream
Content-Type: application/json
Accept: text/event-stream
```

请求体与 `/chat/ask` 相同：

```json
{
  "evaluation_id": "EVAL_20260326_001",
  "question": "这项技术有可能量产吗？"
}
```

### 响应

响应类型：`text/event-stream`

事件约定：

- `event: status`
  - `data: {"message":"..."}`  
  - 表示当前后台阶段，例如“正在准备聊天索引”“正在检索相关正文片段”“正在生成专家回答”
- `event: delta`
  - `data: {"text":"..."}`  
  - 表示新增回答片段
- `event: done`
  - `data: {"answer":"...","citations":[...]}`  
  - 表示回答完成，并一次性返回 citation
- `event: error`
  - `data: {"message":"..."}`  
  - 表示流式问答失败

### 说明

- `ask-stream` 与 `chat/ask` 共用同一套聊天索引与证据检索逻辑
- 若当前模型提供商为 `qwen`，服务会优先走兼容接口直连，并显式关闭 `thinking`
- 为避免主链路再次变慢，流式阶段也不补齐 `highlight_rects`
- 建议前端优先使用 `ask-stream`，仅在浏览器或代理不支持 SSE 时回退到 `chat/ask`

## 7. 聊天引用高亮

### 请求

```http
POST /api/v1/evaluation/chat/citation-highlight
Content-Type: application/json
```

```json
{
  "evaluation_id": "EVAL_20260326_001",
  "file": "申报书.pdf",
  "page": 18,
  "snippet": "完成三轮中试验证..."
}
```

### 响应

```json
{
  "packet_page": 18,
  "highlight_rects": [
    { "x": 0.11, "y": 0.24, "w": 0.42, "h": 0.03 }
  ]
}
```

### 说明

- 该接口用于正式 HTML 工作台中的“查看原文”懒加载高亮
- 若无法精确定位，允许返回 `packet_page>0` 且 `highlight_rects=[]`，前端至少完成页级跳转

## 8. 权重与维度接口

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
