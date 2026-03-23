# 🌐 API 接口文档

## 概述

绩效核验服务提供申报书与任务书的智能对齐和差异核验接口，输出结构化预警结果。

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1/perfcheck` |
| 认证方式 | API Key / Bearer Token |
| 请求格式 | `application/json` 或 `multipart/form-data` |
| 响应格式 | JSON |

---

## 接口列表

### 1. 单项目核验

**POST** `/api/v1/perfcheck/compare`

对单个项目的申报书与任务书执行核验。

#### 请求参数（JSON）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_id` | String | 是 | 项目唯一标识 |
| `declaration_text` | String | 否 | 申报书文本（与文件二选一） |
| `task_text` | String | 否 | 任务书文本（与文件二选一） |
| `declaration_file_id` | String | 否 | 申报书文件ID |
| `task_file_id` | String | 否 | 任务书文件ID |
| `strict_mode` | Boolean | 否 | 是否启用严格模式，默认 `true` |
| `budget_shift_threshold` | Number | 否 | 预算比例变动阈值，默认 `0.15` |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/perfcheck/compare" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_2026_001",
    "declaration_file_id": "file_dec_001",
    "task_file_id": "file_task_001",
    "strict_mode": true,
    "budget_shift_threshold": 0.15
  }'
```

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "message": "核验完成",
  "data": {
    "task_id": "pc_170000000001",
    "project_id": "proj_2026_001",
    "summary": {
      "overall_risk": "high",
      "critical_count": 1,
      "high_count": 2,
      "medium_count": 1
    },
    "findings": [
      {
        "rule_id": "R-IND-001",
        "category": "indicator",
        "risk_level": "critical",
        "title": "核心指标下降",
        "detail": "论文指标由 10 篇降至 6 篇，下降 40.0%",
        "evidence": {
          "declaration": "预期发表 SCI 论文 10 篇",
          "task": "计划发表 SCI 论文 6 篇",
          "declaration_location": "第4章-绩效目标-表2",
          "task_location": "第3章-考核指标-表1"
        }
      },
      {
        "rule_id": "R-BUD-001",
        "category": "budget",
        "risk_level": "high",
        "title": "预算大类比例异常变动",
        "detail": "设备费占比由 35% 降至 12%，管理费占比由 8% 升至 20%"
      }
    ]
  }
}
```

---

### 2. 批量核验

**POST** `/api/v1/perfcheck/batch-compare`

批量提交多个项目核验任务。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `items` | Array | 是 | 核验任务列表 |
| `items[].project_id` | String | 是 | 项目ID |
| `items[].declaration_file_id` | String | 是 | 申报书文件ID |
| `items[].task_file_id` | String | 是 | 任务书文件ID |
| `callback_url` | String | 否 | 异步回调地址 |

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "message": "批量任务已提交",
  "data": {
    "batch_id": "pcb_170000000002",
    "total": 50,
    "queued": 50
  }
}
```

---

### 3. 查询核验任务

**GET** `/api/v1/perfcheck/{task_id}`

查询任务状态与核验摘要。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | String | 任务ID |

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "task_id": "pc_170000000001",
    "state": "finished",
    "project_id": "proj_2026_001",
    "summary": {
      "overall_risk": "high",
      "critical_count": 1,
      "high_count": 2,
      "medium_count": 1
    }
  }
}
```

---

### 4. 获取核验报告

**GET** `/api/v1/perfcheck/{task_id}/report`

获取结构化核验报告，可用于审查归档。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `format` | String | 否 | `json`/`markdown`/`pdf`，默认 `json` |

---

## 错误码说明

| 错误码 | 含义 | 说明 |
|--------|------|------|
| `40001` | 请求参数错误 | 必填字段缺失或格式非法 |
| `40002` | 文件不可用 | 文件不存在或无读取权限 |
| `40003` | 文档解析失败 | 文档损坏或无法提取文本 |
| `40901` | 任务冲突 | 同一项目已有进行中任务 |
| `42201` | 对齐失败 | 无法建立有效对齐关系 |
| `50001` | 核验执行失败 | 系统内部错误 |

---

## 预警等级定义

| 等级 | 含义 | 处置建议 |
|------|------|----------|
| `critical` | 明显降标/删减/异常挪移 | 立即人工复核并冻结流转 |
| `high` | 高风险差异 | 进入复核队列优先处理 |
| `medium` | 中风险差异 | 常规复核 |
| `low` | 低风险差异 | 自动通过或抽检 |