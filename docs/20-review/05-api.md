# 🌐 API 接口文档

## 概述

形式审查服务提供 RESTful API 接口，支持文件上传、审查执行、结果查询等功能。

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1/review` |
| 认证方式 | API Key |
| 请求格式 | `multipart/form-data` |
| 响应格式 | JSON |

## 接口列表

### 1. 提交审查

**POST** `/api/v1/review`

提交文件进行形式审查。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 上传的文件 |
| `document_type` | String | 否 | 文档类型（自动识别时省略） |
| `check_items` | String | 否 | 检查项，逗号分隔 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/review" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@/path/to/document.pdf" \
  -F "document_type=patent_certificate" \
  -F "check_items=signature,stamp,prerequisite"
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "review_1709280000000",
    "document_type": "patent_certificate",
    "results": [
      {
        "item": "signature",
        "status": "passed",
        "message": "检测到 1 个签字区域",
        "evidence": {
          "region_count": 1,
          "regions": [
            {"bbox": {"x": 100, "y": 500, "width": 200, "height": 50}, "confidence": 0.92}
          ]
        },
        "confidence": 0.92
      },
      {
        "item": "stamp",
        "status": "passed",
        "message": "检测到 1 个印章",
        "evidence": {
          "region_count": 1
        },
        "confidence": 0.88
      },
      {
        "item": "prerequisite",
        "status": "passed",
        "message": "前置条件满足"
      }
    ],
    "summary": "审查完成：通过 3 项，失败 0 项",
    "suggestions": [],
    "processed_at": "2024-03-01T10:00:00Z",
    "processing_time": 2.5
  },
  "message": "审查完成",
  "code": 200
}
```

---

### 2. 查询审查结果

**GET** `/api/v1/review/{review_id}`

根据 ID 查询审查结果。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `review_id` | String | 审查 ID |

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "review_1709280000000",
    "document_type": "patent_certificate",
    "results": [...],
    "summary": "审查完成：通过 3 项，失败 0 项",
    "suggestions": [],
    "processed_at": "2024-03-01T10:00:00Z",
    "processing_time": 2.5
  },
  "message": "成功",
  "code": 200
}
```

---

### 3. 文档类型列表

**GET** `/api/v1/review/document-types`

获取支持的文档类型列表。

#### 响应示例

```json
{
  "status": "success",
  "data": [
    {
      "value": "patent_certificate",
      "label": "专利证书",
      "check_items": ["signature", "stamp", "consistency"]
    },
    {
      "value": "acceptance_report",
      "label": "验收报告",
      "check_items": ["signature", "stamp", "prerequisite"]
    },
    {
      "value": "retrieval_report",
      "label": "检索报告",
      "check_items": ["completeness"]
    }
  ],
  "code": 200
}
```

---

### 4. 检查项列表

**GET** `/api/v1/review/check-items`

获取所有可用的检查项。

#### 响应示例

```json
{
  "status": "success",
  "data": [
    {
      "value": "signature",
      "label": "签字检查",
      "description": "检查文档中是否存在签字"
    },
    {
      "value": "stamp",
      "label": "盖章检查",
      "description": "检查文档中是否存在印章"
    },
    {
      "value": "prerequisite",
      "label": "前置条件",
      "description": "检查前置条件文档是否上传"
    },
    {
      "value": "consistency",
      "label": "一致性检查",
      "description": "检查填写信息与证书是否一致"
    },
    {
      "value": "completeness",
      "label": "完整性检查",
      "description": "检查文档是否完整"
    }
  ],
  "code": 200
}
```

---

## 错误响应

### 错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 413 | 文件过大 |
| 415 | 不支持的文件类型 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |

### 错误示例

```json
{
  "status": "error",
  "message": "不支持的文件类型: exe",
  "code": 415
}
```

```json
{
  "status": "error",
  "message": "文件大小超过限制 (最大 10MB)",
  "code": 413
}
```

---

## 使用 SDK

### Python SDK

```python
from tech import ReviewClient

client = ReviewClient(api_key="YOUR_API_KEY")

# 提交审查
result = await client.review.submit(
    file_path="/path/to/document.pdf",
    document_type="patent_certificate",
    check_items=["signature", "stamp"]
)

print(result.summary)
```

### JavaScript SDK

```javascript
import { ReviewClient } from 'tech-sdk';

const client = new ReviewClient({ apiKey: 'YOUR_API_KEY' });

const result = await client.review.submit({
  filePath: '/path/to/document.pdf',
  documentType: 'patent_certificate',
  checkItems: ['signature', 'stamp']
});

console.log(result.summary);
```

---

## 集成 LangServe

形式审查服务也提供 LangServe 接口：

```
POST /review/chain
```

```bash
curl -X POST "http://localhost:8000/review/chain" \
  -H "Content-Type: application/json" \
  -d '{
    "file": "<base64 encoded file>",
    "file_type": "pdf"
  }'
```
