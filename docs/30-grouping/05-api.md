# 🌐 API 接口文档

## 概述

智能分组与专家匹配服务提供 RESTful API 接口，支持项目分组、专家匹配、完整流程等功能。

## 基础信息

|| 项目 | 值 |
|------|------|-----|
| 基础路径 | `/api/v1/grouping` |
| 认证方式 | API Key |
| 请求格式 | `application/json` |
| 响应格式 | JSON |

---

## 接口列表

### 1. 项目分组

**POST** `/api/v1/grouping/projects`

对申报项目进行智能分组。

#### 请求参数

|| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `year` | String | 是 | 年度，如 "2024" |
| `category` | String | 否 | 奖种类别 |
| `group_count` | Integer | 否 | 分组数量（省略则自动计算） |
| `max_per_group` | Integer | 否 | 每组最大项目数（默认30） |
| `strategy` | String | 否 | 分组策略：`balanced`（均衡）或 `quality`（质量优先） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/grouping/projects" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "year": "2024",
    "category": "自然科学",
    "strategy": "balanced"
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
        "projects": [
          {
            "project_id": "proj_001",
            "xmmc": "基于多尺度分析的智能电网故障预测系统",
            "quality_score": 85.5,
            "reason": "技术创新性强"
          },
          {
            "project_id": "proj_002",
            "xmmc": "新型石墨烯基传感器研发",
            "quality_score": 82.3,
            "reason": "材料创新突出"
          }
        ],
        "summary": {
          "count": 28,
          "avg_score": 82.3,
          "main_themes": ["人工智能", "电力系统", "新材料"]
        }
      },
      {
        "group_id": 2,
        "projects": [...],
        "summary": {
          "count": 25,
          "avg_score": 80.1,
          "main_themes": ["生物医药", "化学工程"]
        }
      }
    ],
    "statistics": {
      "total_projects": 147,
      "group_count": 5,
      "balance_score": 0.92,
      "avg_projects_per_group": 29.4,
      "avg_quality_per_group": 81.2
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

|| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
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
          },
          {
            "expert_id": "zj_002",
            "xm": "李教授",
            "match_score": 88.3,
            "reason": "熟悉学科匹配：电力系统",
            "avoidance": null
          },
          {
            "expert_id": "zj_003",
            "xm": "王教授",
            "match_score": 85.0,
            "reason": "研究领域相关：故障诊断",
            "avoidance": null
          },
          {
            "expert_id": "zj_004",
            "xm": "赵教授",
            "match_score": 82.1,
            "reason": "技术方向匹配",
            "avoidance": null
          },
          {
            "expert_id": "zj_005",
            "xm": "刘教授",
            "match_score": 78.5,
            "reason": "学科背景匹配",
            "avoidance": null
          }
        ]
      },
      {
        "project_id": "proj_002",
        "experts": [...]
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
    "warnings": [
      "专家张三与项目负责人李四存在师生关系，已回避",
      "专家王五与项目六存在历史合作关系，已回避"
    ]
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

|| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `year` | String | 是 | 年度 |
| `category` | String | 否 | 奖种类别 |
| `group_count` | Integer | 否 | 分组数量 |
| `experts_per_project` | Integer | 否 | 每个项目分配专家数（默认5） |
| `min_experts_per_group` | Integer | 否 | 每组最少懂行专家数（默认10） |
| `avoid_relations` | Boolean | 否 | 是否回避关系（默认true） |
| `max_reviews_per_expert` | Integer | 否 | 每位专家最大评审数（默认5） |

#### 请求示例

```bash
curl -X POST "http://localhost:8000/api/v1/grouping/full" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "year": "2024",
    "category": "自然科学",
    "group_count": 5,
    "experts_per_project": 5,
    "min_experts_per_group": 10,
    "avoid_relations": true
  }'
```

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "full_1709280000003",
    "year": "2024",
    "category": "自然科学",
    "groups": [
      {
        "group_id": 1,
        "projects": [...],
        "summary": {...}
      }
    ],
    "matches": {
      "1": {
        "group_id": 1,
        "matches": [...],
        "statistics": {...}
      }
    },
    "statistics": {
      "total_projects": 147,
      "total_groups": 5,
      "total_experts": 89,
      "avg_match_score": 84.7,
      "balance_score": 0.92
    },
    "report": "分组与匹配完成。共147个项目分成5组，每组平均29.4个项目。每项目分配5位专家，平均匹配度84.7分。检测到3对需要回避的专家-项目关系，已自动排除。"
  },
  "message": "完整流程完成",
  "code": 200
}
```

---

### 4. 查询分组结果

**GET** `/api/v1/grouping/{grouping_id}`

查询分组结果。

#### 路径参数

|| 参数 | 类型 | 说明 |
|------|------|------|------|
| `grouping_id` | String | 分组结果ID |

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "group_1709280000001",
    "year": "2024",
    "groups": [...],
    "statistics": {...}
  },
  "code": 200
}
```

---

### 5. 查询匹配结果

**GET** `/api/v1/grouping/match/{matching_id}`

查询匹配结果。

#### 路径参数

|| 参数 | 类型 | 说明 |
|------|------|------|------|
| `matching_id` | String | 匹配结果ID |

#### 响应示例

```json
{
  "status": "success",
  "data": {
    "id": "match_1709280000002",
    "group_id": 1,
    "matches": [...],
    "statistics": {...}
  },
  "code": 200
}
```

---

## 错误码说明

|| 错误码 | 说明 |
|--------|------|------|
| 200 | 成功 | 请求成功 |
| 400 | 参数错误 | 请求参数不正确 |
| 401 | 认证失败 | API Key 无效 |
| 404 | 不存在 | 指定的分组/匹配结果不存在 |
| 422 | 业务错误 | 业务逻辑错误，如项目数不足等 |
| 500 | 服务器错误 | 服务器内部错误 |

### 错误响应示例

```json
{
  "status": "error",
  "message": "分组数量计算失败：项目数太少",
  "code": 422
}
```

---

## 相关文档

- [服务概述 →](01-overview.md)
- [分组子服务 →](02-grouping.md)
- [专家匹配子服务 →](03-matching.md)
- [数据模型 →](04-models.md)
