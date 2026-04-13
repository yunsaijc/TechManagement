# LogicOn API 接口文档

## 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/logicon/check` | POST | 上传文件并进行逻辑一致性核验（同步） |
| `/api/v1/logicon/check-text` | POST | 传入文本并进行逻辑一致性核验（同步） |
| `/api/v1/logicon/check-async` | POST | 上传文件并进行逻辑一致性核验（异步） |
| `/api/v1/logicon/{task_id}` | GET | 查询异步任务状态 |

## 1) 同步核验：上传文件

### 请求

`POST /api/v1/logicon/check`

FormData：

- `file`: 文件（PDF/DOCX）
- `doc_kind`: `declaration | task | auto`（可选，默认 auto）
- `enable_llm`: `true | false`（可选，默认 false）
- `return_graph`: `true | false`（可选，默认 false）

### 响应示例

```json
{
  "status": "success",
  "data": {
    "doc_id": "logicon_1740000000000",
    "doc_kind": "declaration",
    "partial": false,
    "conflicts": [
      {
        "conflict_id": "C1",
        "severity": "RED",
        "category": "BUDGET_SUM",
        "title": "预算总额与明细求和不一致",
        "description": "预算总额为 50 万元，但明细求和为 70 万元，差额 20 万元。",
        "evidence": [
          {
            "page": 12,
            "section_title": "项目预算表",
            "snippet": "资金申请总额：50 万元"
          },
          {
            "page": 13,
            "section_title": "资金安排明细",
            "snippet": "设备费 30 万元；材料费 20 万元；劳务费 20 万元……"
          }
        ],
        "related_entities": ["E3", "E7"],
        "rule_id": "R-BUDGET-01"
      }
    ],
    "warnings": [],
    "rule_snapshot": {
      "version": "v1",
      "enabled_rules": [],
      "thresholds": {
        "amount_tolerance": "0.01万",
        "date_tolerance_days": 30
      }
    }
  },
  "message": ""
}
```

## 2) 同步核验：文本直传

### 请求

`POST /api/v1/logicon/check-text`

JSON Body：

```json
{
  "doc_kind": "auto",
  "text": "......",
  "enable_llm": false,
  "return_graph": false
}
```

## 3) 异步核验：上传文件

### 请求

`POST /api/v1/logicon/check-async`

参数同 `/check`，返回 `task_id`。

### 响应示例

```json
{
  "status": "success",
  "data": {
    "task_id": "8f23a1c2",
    "state": "running",
    "progress": 0.01,
    "stage": "received",
    "message": "已接收请求",
    "summary": "",
    "result": null
  }
}
```

## 4) 查询任务状态

`GET /api/v1/logicon/{task_id}`

返回结构与 perfcheck 的任务查询保持一致：若完成则 `result` 为核验结果。

## 错误码

| 错误码 | 说明 |
|------|------|
| `INVALID_INPUT` | 输入非法（缺文件/缺文本/参数不合法） |
| `PARSE_FAILED` | 文档解析失败 |
| `LLM_TIMEOUT` | LLM 调用超时 |
| `UNKNOWN_ERROR` | 未分类错误 |
