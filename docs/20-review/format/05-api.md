# 🌐 API 接口文档

## 概述

本文档描述当前已实现的**附件级形式审查**接口。该接口用于单附件检查，不直接承担完整项目级形式审查。

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

提交单个附件进行形式审查。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 上传的文件 |
| `document_type` | String | 是 | 文档类型，由调用方指定 |
| `check_items` | String | 否 | 检查项，逗号分隔 |
| `enable_llm_analysis` | Boolean | 否 | 是否启用 LLM 深度分析（默认 false，用于调试 OCR 效果） |
| `metadata` | String | 否 | 元数据 JSON 字符串 |

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
    "document_type_raw": "专利证书",
    "ocr_text": "九、主要完成人情况表\n姓名\n边亮\n...",
    "extracted_data": {
      "units": ["河北地质大学"],
      "work_units": ["河北地质大学"],
      "authors": ["xx"],
      "project_name": "",
      "stamps": [],
      "signatures": [{"page": 1, "bbox": {"x": 100, "y": 500, "width": 200, "height": 50}}],
      "pages": 1
    },
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

### 1.1 按 SMB 路径提交审查

**POST** `/api/v1/review/path`

按 SMB 路径提交单文件进行形式审查。

#### 当前已实现入参

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_type` | String | 是 | 文档类型；奖励平台约定使用字典类型值 |
| `file_path` | String | 是 | SMB/UNC 路径或 share 内相对路径 |
| `check_items` | Array[String] | 否 | 检查项列表 |
| `enable_llm_analysis` | Boolean | 否 | 是否启用 LLM 深度分析 |
| `metadata` | Object | 否 | 元数据 |

#### 当前请求示例

```bash
curl -X POST "http://localhost:8888/api/v1/review/path" \
  -H "Content-Type: application/json" \
  -d '{
    "doc_type": "wcr",
    "file_path": "FJCL\\static\\rpw\\gzy2025\\2025-103-2005\\1757576186465.pdf"
  }'
```

#### 奖励平台主线入参约定（待实现）

奖励平台签字盖章专项后续将以以下 3 个字段作为主入口：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_id` | String | 是 | 奖励项目编号，对应 `XMBH` |
| `file_path` | String | 是 | PDF 完整 SMB 路径 |
| `doc_type` | String | 是 | 奖励材料字典类型 |

建议 `doc_type` 取值：

| 值 | 中文名称 | 注释 |
|------|------|------|
| `tjdwyj` | 提名单位意见表 | 奖励项目提名单位出具的意见页，用于校验提名单位名称与盖章 |
| `gzdwyj` | 候选人工作单位意见 | 候选人所在工作单位出具的意见页，用于校验工作单位名称与盖章 |
| `wcr` | 主要完成人情况表 | 境内主要完成人签字盖章页，用于校验姓名、工作单位、完成单位 |
| `wjwcr` | 外籍主要完成人情况表 | 外籍主要完成人对应材料，校验逻辑与 `wcr` 类似 |
| `wcdw` | 主要完成单位情况表 | 完成单位签章页，用于校验单位名称、法定代表人、盖章 |
| `hzdw` | 河北省内主要合作单位情况表 | 合作单位签章页，用于校验合作单位名称与盖章 |

后续该主线将基于 `project_id + file_path + doc_type`：

- 定位 `xmsbnew.t_xm_gzy` 中的唯一附件记录
- 读取 SMB 远端文件
- 返回并落地保存：
  - 是否有签字
  - 是否有盖章
  - 识别的签字内容
  - 识别的印章内容
  - 与奖励库目标字段的比对结果

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

说明：

- 这里返回的是当前附件级接口支持的 `document_type`
- 它不等同于项目级的 `project_type`
- 项目级形式审查应在上层单独建模

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

---

## LLM 深度分析（可选）

当 `enable_llm_analysis=true` 时，响应中会增加 `llm_analysis` 字段，包含 LLM 对文档的深度分析结果。

### 分析内容

|| 字段 | 说明 |
||------|------|
|| `document_type_llm` | LLM 识别的文档类型 |
|| `extracted_fields` | LLM 提取的结构化字段（姓名、单位等） |
|| `stamps_description` | LLM 对印章区域的描述 |
|| `signatures_description` | LLM 对签字区域的描述 |
|| `tables` | LLM 识别的表格结构 |
|| `issues` | LLM 发现的问题列表 |

### 调用示例

```bash
curl -X POST "http://localhost:8888/api/v1/review" \
  -F "file=@/path/to/document.pdf" \
  -F "enable_llm_analysis=true"
```

### LLM 分析响应示例

```json
{
  "llm_analysis": {
    "document_type_llm": "奖励-主要完成人情况表",
    "extracted_fields": {
      "姓名": "董发勤",
      "工作单位": "西南科技大学",
      "完成单位": "西南科技大学"
    },
    "stamps_description": "页面右下角有一个红色印章，印章文字为'西南科技大学'",
    "signatures_description": "页面底部有手写签名，签名为'董发勤'",
    "tables": [
      {
        "title": "主要完成人情况表",
        "rows": 10,
        "columns": 5
      }
    ],
    "issues": [
      "工作单位填写为'西南科技大学'，与完成单位盖章'西南科技大学'一致"
    ]
  }
}
```

### 适用场景

- **OCR 效果调试**：对比 OCR 提取结果与 LLM 提取结果，定位识别问题
- **复杂版式处理**：LLM 可以理解表格结构、跨页内容等复杂情况
- **语义理解**：LLM 可以判断字段语义的合理性
