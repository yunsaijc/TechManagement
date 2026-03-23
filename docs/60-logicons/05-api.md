# 🌐 API 接口文档

## 概述

逻辑自洽校验服务提供 RESTful API，用于执行全局逻辑一致性检查、查询结果与读取规则配置。

## 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `/api/v1/logicons` |
| 认证方式 | API Key |
| 请求格式 | `multipart/form-data` 或 `application/json` |
| 响应格式 | JSON |

---

## 接口列表

### 1. 提交逻辑一致性校验

**POST** `/api/v1/logicons/check`

上传申报书/任务书并触发全局一致性校验。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 文档文件（DOCX/PDF） |
| `project_id` | String | 否 | 项目标识 |
| `budget_tolerance` | Float | 否 | 预算容差比例，默认 `0.01` |
| `timeline_grace_days` | Integer | 否 | 时间宽限天数，默认 `0` |
| `enable_semantic_check` | Boolean | 否 | 是否启用语义冲突检查，默认 `true` |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/logicons/check" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@/path/to/declaration.docx" \
  -F "project_id=project_2026_001" \
  -F "budget_tolerance=0.01" \
  -F "enable_semantic_check=true"
```

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "message": "校验完成",
  "data": {
    "check_id": "logicons_1773809001001",
    "project_id": "project_2026_001",
    "summary": {
      "high": 2,
      "medium": 1,
      "low": 0,
      "total": 3
    },
    "conflicts": [
      {
        "conflict_id": "C001",
        "rule_code": "T001",
        "severity": "high",
        "message": "项目执行期为2年，但详细进度跨越4年",
        "evidences": [
          {
            "section": "一、项目基本信息",
            "page": 2,
            "quote": "项目执行期：2025年1月-2026年12月"
          },
          {
            "section": "四、详细任务进度安排",
            "page": 9,
            "quote": "2028年Q2完成系统联调"
          }
        ],
        "suggestion": "将进度节点调整至执行期内，或同步修改项目执行期"
      },
      {
        "conflict_id": "C002",
        "rule_code": "B001",
        "severity": "high",
        "message": "资金申请总额与分项合计不一致",
        "evidences": [
          {
            "section": "二、经费预算总表",
            "page": 5,
            "quote": "资金申请总额：50万元"
          },
          {
            "section": "五、资金安排明细",
            "page": 11,
            "quote": "分项合计：70万元"
          }
        ],
        "suggestion": "核对分项金额与总额，确保预算口径一致"
      }
    ]
  }
}
```

---

### 2. 查询校验结果

**GET** `/api/v1/logicons/{check_id}`

根据校验 ID 查询结果。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `check_id` | String | 校验任务 ID |

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "check_id": "logicons_1773809001001",
    "summary": {
      "high": 2,
      "medium": 1,
      "low": 0,
      "total": 3
    },
    "conflicts": []
  }
}
```

---

### 3. 获取规则配置

**GET** `/api/v1/logicons/rules`

获取当前可用规则、阈值与默认配置。

#### 响应示例

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "rules": [
      {"code": "T001", "name": "执行期与进度跨度一致"},
      {"code": "B001", "name": "资金总额与分项合计一致"},
      {"code": "I001", "name": "总体指标与阶段指标一致"}
    ],
    "defaults": {
      "budget_tolerance": 0.01,
      "timeline_grace_days": 0,
      "semantic_confidence": 0.75
    }
  }
}
```

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 认证失败 |
| 413 | 文件过大 |
| 415 | 不支持的文件格式 |
| 422 | 逻辑校验处理失败 |
| 500 | 服务器内部错误 |

### 错误响应示例

```json
{
  "status": "error",
  "code": 415,
  "message": "不支持的文件格式: xls"
}
```
