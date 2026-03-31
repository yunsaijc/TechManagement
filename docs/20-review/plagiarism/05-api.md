# API 接口文档 (Plagiarism API)

## 概述

查重服务提供统一的检测入口，支持“上传文档 vs 系统库”或“多文件互查”模式。

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1/plagiarism` |
| 格式 | `multipart/form-data` |

## 核心接口

### 1. 提交查重任务

**POST** `/api/v1/plagiarism`

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File | 是 | 上传的文档（PDF/DOCX）。若只传1个，则必须启用 `use_corpus` |
| `use_corpus` | Boolean | 否 | 是否查比对库，默认 `true` |
| `corpus_id` | String | 否 | 指定查哪个库，不传则查默认库 |
| `doc_type` | String | 否 | 文档类型（用于加载 Section 配置），默认 `default` |
| `threshold` | Float | 否 | 相似度阈值，默认 `0.5` |
| `debug` | Boolean | 否 | 是否生成调试文件，默认 `false` |

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "plag_123456",
    "effective_duplicate_rate": 0.245,
    "effective_duplicate_chars": 3500,
    "primary_scope_chars": 14285,
    "source_rankings": [
      {
        "doc_id": "historical_report_2023.docx",
        "contribution_rate": 0.18,
        "max_similarity": 0.92
      }
    ],
    "match_groups": [
      {
        "group_id": "g001",
        "primary_start": 1200,
        "primary_end": 1500,
        "similarity": 0.95,
        "sources": [
          {"doc": "historical_report_2023.docx", "start": 800, "end": 1100}
        ]
      }
    ],
    "processing_time": 1.45
  }
}
```

### 2. 获取库索引状态

**GET** `/api/v1/plagiarism/corpus/status`

查询当前库索引的状态信息。

#### 响应示例
```json
{
  "status": "success",
  "data": {
    "document_count": 1250,
    "total_chars": 18500000,
    "last_updated": 1711785600.0
  }
}
```

### 3. 刷新库索引

**POST** `/api/v1/plagiarism/corpus/refresh`

触发远程挂载目录的增量扫描与预索引构建。

#### 响应示例
```json
{
  "status": "success",
  "data": {
    "scanned": 120,
    "new": 15,
    "updated": 3,
    "failed": 0
  }
}
```

## 错误码

| 状态码 | 说明 |
|------|------|
| 400 | 参数错误（如未上传文件或库不可用） |
| 500 | 服务器内部错误（如远程挂载丢失） |
