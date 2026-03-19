# 🌐 API 接口文档

## 概述

查重服务提供 RESTful API 接口，支持多文件上传查重，输出重复位置及来源。

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1/plagiarism` |
| 认证方式 | API Key |
| 请求格式 | `multipart/form-data` |
| 响应格式 | JSON |

## 接口列表

### 1. 提交查重

**POST** `/api/v1/plagiarism`

提交文件进行查重检测。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File | 是 | 上传的文件列表（支持多个，最少2个） |
| `threshold` | Float | 否 | 相似度阈值（默认 0.5） |
| `threshold_high` | Float | 否 | 高相似度阈值（默认 0.8） |
| `threshold_medium` | Float | 否 | 中相似度阈值（默认 0.5） |
| `doc_type` | String | 否 | 文档类型，用于加载 section 配置（默认 "default"） |
| `section_config` | String | 否 | 自定义 section 配置（JSON 字符串），优先级高于 doc_type |
| `debug` | Boolean | 否 | 是否保存 debug 结果（默认 false） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/plagiarism" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "files=@/path/to/doc1.pdf" \
  -F "files=@/path/to/doc2.pdf" \
  -F "threshold=0.5" \
  -F "debug=true"
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "plagiarism_1709280000000",
    "total_pairs": 15,
    "high_similarity": [
      {
        "doc_a": "相似组2-A.docx",
        "doc_b": "相似组2-B.docx",
        "similarity": 0.85,
        "type": "high",
        "total_chars": 25000,
        "duplicate_chars": 21250,
        "duplicate_segments": [
          {
            "primary_line": 48,
            "primary_text": "本项目组织及参与单位拥有成熟的科学家团队，从事相关研究多年，取得了丰硕的成果，具有良好的研究基础和试验条件。",
            "sources": [
              {
                "doc": "相似组2-B.docx",
                "line": 210,
                "text": "本项目组织及参与单位拥有成熟的科学家团队，从事相关研究多年，取得了丰硕的成果，具有良好的研究基础和试验条件。"
              }
            ]
          }
        ]
      }
    ],
    "medium_similarity": [
      {
        "doc_a": "相似组1-A.docx",
        "doc_b": "相似组5-A.docx",
        "similarity": 0.55,
        "type": "medium",
        "total_chars": 28000,
        "duplicate_chars": 15400,
        "duplicate_segments": [...]
      }
    ],
    "low_similarity": [
      {
        "doc_a": "相似组3-A.docx",
        "doc_b": "相似组4-B.docx",
        "similarity": 0.30,
        "type": "low",
        "total_chars": 22000,
        "duplicate_chars": 6600,
        "duplicate_segments": [...]
      }
    ],
    "processing_time": 2.35
  }
}
```

#### 响应字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String | 查重任务 ID |
| `total_pairs` | Int | 比对的对数（n*(n-1)/2） |
| `high_similarity` | List | 高相似度文档对（≥threshold_high） |
| `medium_similarity` | List | 中相似度文档对（threshold_medium ≤ similarity < threshold_high） |
| `low_similarity` | List | 低相似度文档对（< threshold_medium） |

#### 单个文档对字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_a` | String | 文档 A 文件名 |
| `doc_b` | String | 文档 B 文件名 |
| `similarity` | Float | 相似度（重复字数/总字数，0-1） |
| `type` | String | 类型：high/medium/low |
| `total_chars` | Int | 文档 A 总字符数 |
| `duplicate_chars` | Int | 重复字符数 |
| `duplicate_segments` | List | 重复片段列表 |

#### DuplicateSegment 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `primary_line` | Int | 在文档 A 中的行号 |
| `primary_text` | String | 在文档 A 中的文本内容 |
| `sources` | List | 来源文档列表 |
| `sources[].doc` | String | 来源文档文件名 |
| `sources[].line` | Int | 在来源文档中的行号 |
| `sources[].text` | String | 在来源文档中的文本内容 |

### 2. 获取支持的文档类型

**GET** `/api/v1/plagiarism/types`

获取查重服务支持的文档类型。

#### 响应示例

```json
{
  "status": "success",
  "data": ["pdf", "docx"]
}
```

### 3. 获取 Section 配置列表

**GET** `/api/v1/plagiarism/section-configs`

获取所有支持的 section 配置。

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "default": {
      "name": "默认配置",
      "description": "适用于项目申报书类文档",
      "sections": [
        {
          "name": "项目立项背景及意义",
          "start_pattern": "项目立项背景及意义",
          "end_pattern": "项目简介"
        },
        {
          "name": "项目简介",
          "start_pattern": "项目简介",
          "end_pattern": "第一部分\\s*项目实施内容及目标"
        }
      ]
    }
  }
}
```

## 错误码

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误（如未上传文件、文件数不足） |
| 413 | 文件过大 |
| 500 | 服务内部错误 |

## Debug 输出

当 `debug=true` 时，系统会在 `debug_plagiarism/` 目录下保存详细的调试信息。

### 文件列表

```
debug_plagiarism/
├── {doc_id}_parse.json          # 单个文档解析结果
├── plagiarism_debug.json         # 查重详细结果
└── ...
```

### 单文档解析结果 ({doc_id}_parse.json)

```json
{
  "doc_id": "相似组2-A.docx",
  "is_primary": true,
  "metadata": {},
  "full_text_preview": "河北省中央引导地方科技发展资金项目申报书\n\n专项名称：...",
  "sections": [
    {
      "name": "项目立项背景及意义",
      "char_count": 1200,
      "text": "项目立项背景及意义..."
    }
  ]
}
```

### 查重详细结果 (plagiarism_debug.json)

```json
{
  "primary_doc": "相似组2-A.docx",
  "total_docs": 2,
  "text_lengths": {
    "相似组2-A.docx": 8181,
    "相似组2-B.docx": 14854
  },
  "processing": {
    "total_sentences": 120,
    "filtered_sentences": 85,
    "filter_reason": {
      "heading_lines": 15,
      "short_lines": 10,
      "template_phrases": 10
    }
  },
  "sections_info": [
    {
      "name": "第一部分 项目实施内容及目标",
      "start_line": 40,
      "end_line": 80,
      "char_count": 3500
    }
  ],
  "duplicate_segments": [
    {
      "type": "continuous",
      "start_pos": 150,
      "end_pos": 280,
      "char_count": 130,
      "primary_location": {
        "line": 48,
        "paragraph": "项目组织与参与团队",
        "section": "第一部分"
      },
      "source_location": {
        "doc": "相似组2-B.docx",
        "line": 210,
        "paragraph": "项目组织与参与团队"
      },
      "matched_content": "本项目组织及参与单位拥有成熟的科学家团队...",
      "ngram_count": 25
    }
  ]
}
```

## 使用示例

### Python

```python
import requests

url = "http://localhost:8000/api/v1/plagiarism"
files = [
    ("files", open("doc1.pdf", "rb")),
    ("files", open("doc2.pdf", "rb")),
]
data = {
    "threshold": 0.5,
    "debug": "true"
}

response = requests.post(url, files=files, data=data)
print(response.json())
```

### JavaScript

```javascript
const formData = new FormData();
formData.append("files", file1);
formData.append("files", file2);
formData.append("threshold", "0.5");
formData.append("debug", "true");

const response = await fetch("http://localhost:8000/api/v1/plagiarism", {
  method: "POST",
  headers: { "Authorization": "Bearer YOUR_API_KEY" },
  body: formData,
});

const result = await response.json();
console.log(result);
```
