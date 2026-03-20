# 🌐 API 接口文档

## 概述

智能分组与专家匹配服务提供 RESTful API 接口，支持项目语义分组、专家匹配、完整流程等功能。

## 基础信息

| 项目 | 值 |
|------|------|
| 基础路径 | `/api/v1/grouping` |
| 认证方式 | API Key |
| 请求格式 | `application/json` |
| 响应格式 | JSON |

---

## 接口列表

### 1. 项目分组

**POST** `/api/v1/grouping/projects`

对申报项目进行语义分组。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `year` | String | 是 | 年度，如 "2024" |
| `min_per_group` | Integer | 否 | 每组最小项目数（默认5） |
| `max_per_group` | Integer | 否 | 每组最大项目数（默认15） |
| `top_k_candidates` | Integer | 否 | 每个项目保留的候选组数（默认3） |
| `enable_embedding` | Boolean | 否 | 是否启用 embedding 召回（默认true） |
| `enable_llm` | Boolean | 否 | 是否启用 LLM 复核（默认true） |
| `needs_review_threshold` | Number | 否 | 低于该置信度标记复核（默认0.65） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/grouping/projects" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "year": "2024",
    "enable_embedding": true,
    "enable_llm": true,
    "min_per_group": 5,
    "max_per_group": 15
  }'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "group_1709280000001",
    "year": "2024",
    "groups": [
      {
        "group_id": 1,
        "group_name": "智能电网与故障预测",
        "group_reason": "研究对象、方法和应用场景高度一致",
        "projects": [
          {
            "project_id": "proj_001",
            "xmmc": "基于多尺度分析的智能电网故障预测系统",
            "project_reason": "主题聚焦电网故障预测",
            "confidence": 0.92
          },
          {
            "project_id": "proj_002",
            "xmmc": "新型石墨烯基传感器研发",
            "project_reason": "主题更接近传感器与检测方法",
            "confidence": 0.88
          }
        ],
        "count": 28,
        "needs_review": false
      }
    ],
    "statistics": {
      "total_projects": 147,
      "group_count": 15,
      "avg_projects_per_group": 9.8,
      "small_group_count": 4,
      "review_count": 6
    }
  },
  "message": "分组完成",
  "code": 200
}
```

---

### 2. 专家匹配

**POST** `/api/v1/grouping/match`

为指定分组匹配评审专家。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `group_id` | Integer | 是 | 分组ID（来自分组接口返回） |
| `experts_per_project` | Integer | 否 | 每个项目分配专家数（默认5） |
| `min_experts_per_group` | Integer | 否 | 每组最少懂行专家数（默认10） |
| `avoid_relations` | Boolean | 否 | 是否回避关系（默认true） |
| `max_reviews_per_expert` | Integer | 否 | 每位专家最大评审数（默认5） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/grouping/match" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": 1,
    "experts_per_project": 5,
    "min_experts_per_group": 10,
    "avoid_relations": true,
    "max_reviews_per_expert": 5
  }'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "match_1709280000002",
    "group_id": 1,
    "matches": [
      {
        "project_id": "proj_001",
        "experts": [
          {
            "expert_id": "zj_001",
            "xm": "张教授",
            "match_score": 92.5,
            "reason": "研究方向高度匹配：人工智能、电力系统",
            "avoidance": null
          }
        ]
      }
    ],
    "statistics": {
      "total_projects": 28,
      "total_experts": 45,
      "avg_match_score": 85.3,
      "avoidance_detected": 3,
      "experts_per_project": 5,
      "coverage_rate": 0.92
    },
    "warnings": []
  },
  "message": "匹配完成",
  "code": 200
}
```

---

### 3. 完整流程

**POST** `/api/v1/grouping/full`

一次性完成分组和匹配。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `year` | String | 是 | 年度 |
| `group_count` | Integer | 否 | 目标分组数 |
| `experts_per_project` | Integer | 否 | 每个项目分配专家数 |
| `min_experts_per_group` | Integer | 否 | 每组最少懂行专家数 |
| `avoid_relations` | Boolean | 否 | 是否回避关系 |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/grouping/full" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "year": "2024",
    "group_count": 15,
    "experts_per_project": 5,
    "avoid_relations": true
  }'
```

---

## 设计说明

- 输入以 `xmmc` 为主，`xmjj` 为辅
- 学科代码只作为辅助信息，不作为主分组依据
- 字母开头代码与 7 位数字代码不能混组
- 低置信度结果会标记为 `needs_review`

---

## 下游文档

- [智能分组与专家匹配服务概述](01-overview.md)
- [分组子服务设计](02-grouping.md)
- [数据模型](04-models.md)
