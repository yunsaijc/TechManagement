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

### 1.1 按指南代码批量查库

**POST** `/api/v1/plagiarism/by-guide-codes`

用于真实项目批量查重。接口只接收 `guide_codes`，服务端先查项目库拿到 `id/year`，再定位正文 `docx`，最后按“单项目 vs 本地库”的方式逐个执行库查重。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `guide_codes` | String / String[] | 是 | 指南代码。推荐直接传 JSON 数组字符串，如 `["a","b"]` |
| `doc_type` | String | 否 | 文档类型，默认 `default` |
| `threshold` | Float | 否 | 相似度阈值，默认 `0.5` |
| `threshold_high` | Float | 否 | 高相似度阈值，默认 `0.8` |
| `threshold_medium` | Float | 否 | 中相似度阈值，默认 `0.5` |
| `debug` | Boolean | 否 | 是否生成调试文件，默认 `false` |
| `limit` | Integer | 否 | 只处理前 N 个项目，默认不限制 |

#### 数据来源

- 项目元数据查询条件：`zndm IN (...) AND isSubmit='1'`
- 远端正文标准路径：`/mnt/remote_corpus/{year}/sbs/{id}.docx`
- 在线接口默认只读取本地镜像文件，不直接扫描远端挂载目录

最简请求示例：

```bash
curl -X POST 'http://127.0.0.1:8888/api/v1/plagiarism/by-guide-codes' \
  -F 'guide_codes=["c2f3b7b1f9534463ad726e6936c91859","959c8e453dd942ddb72f0ef52c07342f","7581bc8d6d564153848fcb5d14b1942e"]'
```

说明：

- `threshold` / `threshold_high` / `threshold_medium` / `doc_type` 都有默认值
- 只有需要覆盖默认行为时才传

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "guide_codes": [
      "c2f3b7b1f9534463ad726e6936c91859"
    ],
    "selected_projects": 12,
    "available_docs": 10,
    "missing_docs": [
      {
        "id": "abc123",
        "year": "2025",
        "xmmc": "某项目",
        "expected_local_paths": [
          "/home/tdkx/workspace/tech/data/corpus_local/sbs_5000/abc123.docx",
          "/home/tdkx/workspace/tech/data/corpus_local/2025/sbs/abc123.docx"
        ]
      }
    ],
    "results": [
      {
        "project": {
          "id": "def456",
          "year": "2025",
          "xmmc": "某项目",
          "guide_name": "某指南"
        },
        "result": {
          "id": "plagiarism_123456",
          "effective_duplicate_rate": 0.245,
          "processing_time": 1.45
        }
      }
    ]
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

---

## 图片查重接口（Image Plagiarism）

### 基础路径

- `/api/v1/plagiarism/image`

### 1) 按指南代码批量图片查重（主入口）

**POST** `/api/v1/plagiarism/image/by-guide-codes`

说明：流程与正文库查重一致，先查项目，再抽取 primary 文档图片，最后在图片 corpus 中检索候选并验证；不做在线全量两两比。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `guide_codes` | String / String[] | 是 | - | 指南代码，推荐 JSON 数组字符串 |
| `limit` | Integer | 否 | `20` | 仅处理前 N 个项目 |
| `read_remote_if_missing` | Boolean | 否 | `true` | 本地缺失时是否回退读取远端 docx |
| `threshold_high` | Float | 否 | `0.82` | high 阈值 |
| `threshold_medium` | Float | 否 | `0.62` | medium 阈值 |
| `hash_hamming_max` | Integer | 否 | `18` | pHash Hamming 粗召回阈值 |
| `min_inliers_high` | Integer | 否 | `10` | high 的最小几何内点 |
| `include_low` | Boolean | 否 | `false` | 是否返回 low 结果 |
| `top_k_coarse` | Integer | 否 | `80` | 粗召回后参与精校验的候选上限 |
| `top_k_final` | Integer | 否 | `8` | 每张 query 图最终保留的匹配上限 |
| `verify_workers` | Integer | 否 | `0` | 几何验证进程数（`0`=自动） |
| `verify_backend` | String | 否 | `auto` | `auto/thread/process`，默认自动选 thread |
| `debug` | Boolean | 否 | `false` | 是否生成调试报告 |
| `max_pair_checks` | Integer | 否 | `120000` | 安全预算，防止单次任务失控 |

#### 响应字段（核心）

- `selected_projects`：符合 guide_codes 的项目数
- `resolved_projects`：成功定位并读取文档的项目数
- `missing_docs`：缺文档项目
- `failed_projects`：读取失败项目
- `results.matches`：全量匹配明细
- `per_project_results`：按 primary 项目聚合后的结果（推荐前端消费）

### 2) 图片库状态

**GET** `/api/v1/plagiarism/image/corpus/status`

说明：返回图片索引是否存在、已索引文档数、已索引图片数、更新时间。

### 3) 图片库批量构建

**POST** `/api/v1/plagiarism/image/corpus/build-batch`

说明：离线小批构建；每次只处理小批文档，写入 `data/plagiarism_image/index`，支持断点续跑。

### 4) 提交图片库构建任务

**POST** `/api/v1/plagiarism/image/corpus/build-jobs`

说明：推荐主入口。接口只提交任务并立即返回，后台 worker 串行执行，避免请求线程长时间阻塞。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `corpus_path` | String | 否 | 默认语料路径 | 语料目录 |
| `limit` | Integer | 否 | `20` | 本次批量处理文档数 |
| `reset_cursor` | Boolean | 否 | `false` | 是否从头开始 |

### 5) 查询图片库构建任务

**GET** `/api/v1/plagiarism/image/corpus/build-jobs/{job_id}`

说明：返回 `queued/running/completed/failed` 以及结果或错误信息。

---

图片查重的建库技术参考见：[图片查重库设计](06-image-corpus.md)。
