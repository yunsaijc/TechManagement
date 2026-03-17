# 🌐 API 接口文档

## 概述

查重服务提供 RESTful API 接口，支持多文件上传查重，输出重复位置及来源。

## 基础信息

|| 项目 | 值 |
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

|| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File | 是 | 上传的文件列表（支持多个） |
| `threshold` | Float | 否 | 相似度阈值（默认 0.5） |
| `threshold_high` | Float | 否 | 高相似度阈值（默认 0.8） |
| `threshold_medium` | Float | 否 | 中相似度阈值（默认 0.5） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/plagiarism" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "files=@/path/to/doc1.pdf" \
  -F "files=@/path/to/doc2.pdf" \
  -F "threshold=0.5"
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
            "text": "河北省中央引导地方科技发展资金项目申报书",
            "line_number": 1,
            "source_docs": ["相似组2-B.docx"],
            "source_lines": [1]
          },
          {
            "text": "专项名称：中央引导地方科技发展资金项目",
            "line_number": 5,
            "source_docs": ["相似组2-B.docx"],
            "source_lines": [5]
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

|| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String | 查重任务 ID |
| `total_pairs` | Int | 比对的对数（n*(n-1)/2） |
| `high_similarity` | List | 高相似度文档对（≥threshold_high） |
| `medium_similarity` | List | 中相似度文档对（threshold_medium ≤ similarity < threshold_high） |
| `low_similarity` | List | 低相似度文档对（< threshold_medium） |

#### 单个文档对字段说明

|| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_a` | String | 文档 A 文件名 |
| `doc_b` | String | 文档 B 文件名 |
| `similarity` | Float | 相似度（重复字数/总字数，0-1） |
| `type` | String | 类型：high/medium/low |
| `total_chars` | Int | 文档 A 总字符数 |
| `duplicate_chars` | Int | 重复字符数 |
| `duplicate_segments` | List | 重复片段列表 |

#### DuplicateSegment 字段说明

|| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | String | 重复的文本内容 |
| `line_number` | Int | 在文档 A 中的行号 |
| `source_docs` | List | 来源文档列表 |
| `source_lines` | List | 在来源文档中的行号 |

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

## 错误码

|| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 413 | 文件过大 |
| 500 | 服务内部错误 |

## 使用示例

### Python

```python
import requests

url = "http://localhost:8000/api/v1/plagiarism"
files = [
    ("files", open("doc1.pdf", "rb")),
    ("files", open("doc2.pdf", "rb")),
]
data = {"threshold": 0.5}

response = requests.post(url, files=files, data=data)
print(response.json())
```

### JavaScript

```javascript
const formData = new FormData();
formData.append("files", file1);
formData.append("files", file2);
formData.append("threshold", "0.5");

const response = await fetch("http://localhost:8000/api/v1/plagiarism", {
  method: "POST",
  headers: { "Authorization": "Bearer YOUR_API_KEY" },
  body: formData,
});

const result = await response.json();
console.log(result);
```
