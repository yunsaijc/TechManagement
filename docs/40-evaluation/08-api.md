# 🌐 API 接口文档

## 接口概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/evaluation` | 单项目评审 |
| POST | `/api/v1/evaluation/batch` | 批量评审 |
| GET | `/api/v1/evaluation/{project_id}` | 获取评审结果 |
| GET | `/api/v1/evaluation/dimensions` | 获取评审维度列表 |
| GET | `/api/v1/evaluation/weights/templates` | 获取权重模板 |
| POST | `/api/v1/evaluation/weights/validate` | 验证自定义权重 |

---

## 详细接口

### 1. 单项目评审

对单个项目进行正文评审。

**请求**

```http
POST /api/v1/evaluation
Content-Type: application/json
```

**请求体**

```json
{
  "project_id": "202520014",
  "dimensions": ["feasibility", "innovation", "team"],
  "weights": {
    "feasibility": 0.20,
    "innovation": 0.25,
    "team": 0.15
  },
  "include_sections": [],
  "options": {
    "skip_cache": false,
    "detail_level": "full"
  }
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| project_id | string | 是 | 项目ID |
| dimensions | string[] | 否 | 评审维度列表，默认全部9个维度 |
| weights | object | 否 | 自定义权重，未指定的维度使用默认权重 |
| include_sections | string[] | 否 | 指定解析的章节，默认全部 |
| options | object | 否 | 附加选项 |

**响应**

```json
{
  "project_id": "202520014",
  "project_name": "基于深度学习的智能诊断系统研究",
  "overall_score": 8.35,
  "grade": "B",
  "dimension_scores": [
    {
      "dimension": "feasibility",
      "dimension_name": "技术可行性",
      "score": 8.5,
      "weight": 0.15,
      "weighted_score": 1.275,
      "confidence": 0.85,
      "opinion": "技术路线清晰，采用主流深度学习框架，具有较好的可行性。核心算法选择合理，有相关前期研究基础支撑。",
      "issues": [
        "技术风险部分描述不够详细",
        "缺少关键技术难点的攻克方案"
      ],
      "highlights": [
        "技术方案有创新性",
        "团队有相关研究经验"
      ],
      "items": [
        {
          "name": "技术路线清晰度",
          "score": 9,
          "weight": 0.30,
          "comment": "技术路线图清晰，步骤明确"
        },
        {
          "name": "技术成熟度",
          "score": 8,
          "weight": 0.30,
          "comment": "核心技术成熟，有验证案例"
        },
        {
          "name": "实施条件完备性",
          "score": 8,
          "weight": 0.20,
          "comment": "设备人员基本到位"
        },
        {
          "name": "技术风险控制",
          "score": 8,
          "weight": 0.20,
          "comment": "风险识别较全面，应对措施需加强"
        }
      ]
    },
    {
      "dimension": "innovation",
      "dimension_name": "创新性",
      "score": 8.0,
      "weight": 0.15,
      "weighted_score": 1.20,
      "confidence": 0.80,
      "opinion": "项目具有一定的创新性，提出了新的诊断算法框架。",
      "issues": ["创新点数量偏少"],
      "highlights": ["算法架构有原创性"],
      "items": []
    }
  ],
  "summary": "本项目综合评审等级为良好（B级）。优势维度包括：技术可行性、创新性、预期成果。建议加强风险控制措施和完善进度安排。",
  "recommendations": [
    "【风险控制】建议补充技术风险的具体应对措施",
    "【进度安排】里程碑设置需要更加量化",
    "【团队结构】建议增加一名工程师"
  ],
  "created_at": "2026-03-25T10:30:00",
  "model_version": "gpt-4o-2024-08-06"
}
```

---

### 2. 批量评审

对多个项目进行批量评审。

**请求**

```http
POST /api/v1/evaluation/batch
Content-Type: application/json
```

**请求体**

```json
{
  "project_ids": ["202520014", "202520036", "202520058"],
  "weights": null,
  "concurrency": 3
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| project_ids | string[] | 是 | 项目ID列表，最多50个 |
| weights | object | 否 | 统一权重配置 |
| concurrency | int | 否 | 并发数，默认3，最大10 |

**响应**

```json
{
  "total": 3,
  "success": 3,
  "failed": 0,
  "results": [
    {
      "project_id": "202520014",
      "project_name": "项目名称1",
      "overall_score": 8.35,
      "grade": "B"
    },
    {
      "project_id": "202520036",
      "project_name": "项目名称2",
      "overall_score": 7.20,
      "grade": "C"
    },
    {
      "project_id": "202520058",
      "project_name": "项目名称3",
      "overall_score": 8.80,
      "grade": "B"
    }
  ],
  "summary": {
    "avg_score": 8.12,
    "median_score": 8.35,
    "grade_distribution": {
      "A": 0,
      "B": 2,
      "C": 1,
      "D": 0,
      "E": 0
    },
    "dimension_avg_scores": {
      "feasibility": 8.3,
      "innovation": 7.8,
      "team": 7.5
    }
  },
  "errors": []
}
```

---

### 3. 获取评审结果

获取已有项目的评审结果（从缓存或数据库）。

**请求**

```http
GET /api/v1/evaluation/{project_id}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| project_id | string | 项目ID |

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| refresh | boolean | 是否强制重新评审，默认false |

**响应**

```json
{
  "project_id": "202520014",
  "project_name": "项目名称",
  "overall_score": 8.35,
  "grade": "B",
  "dimension_scores": [],
  "summary": "综合评审意见...",
  "recommendations": [],
  "created_at": "2026-03-25T10:30:00",
  "model_version": "gpt-4o-2024-08-06"
}
```

---

### 4. 获取评审维度列表

获取系统支持的所有评审维度。

**请求**

```http
GET /api/v1/evaluation/dimensions
```

**响应**

```json
{
  "dimensions": [
    {
      "code": "feasibility",
      "name": "技术可行性",
      "category": "核心维度",
      "description": "评估技术路线的合理性和可行性",
      "default_weight": 0.15,
      "check_items": [
        {
          "name": "技术路线清晰度",
          "weight": 0.30,
          "description": "技术路线图是否清晰、步骤是否明确"
        },
        {
          "name": "技术成熟度",
          "weight": 0.30,
          "description": "核心技术是否成熟、是否有验证"
        },
        {
          "name": "实施条件完备性",
          "weight": 0.20,
          "description": "设备、人员、资金是否到位"
        },
        {
          "name": "技术风险控制",
          "weight": 0.20,
          "description": "是否识别技术风险、有应对方案"
        }
      ],
      "required_sections": ["tech_solution", "implementation"]
    },
    {
      "code": "innovation",
      "name": "创新性",
      "category": "核心维度",
      "description": "评估项目的创新程度和技术水平",
      "default_weight": 0.15,
      "check_items": [],
      "required_sections": ["innovation", "tech_solution"]
    }
  ]
}
```

---

### 5. 获取权重模板

获取预设的权重配置模板。

**请求**

```http
GET /api/v1/evaluation/weights/templates
```

**响应**

```json
{
  "templates": {
    "default": {
      "name": "默认权重",
      "description": "适用于一般科技项目",
      "weights": {
        "feasibility": 0.15,
        "innovation": 0.15,
        "team": 0.10,
        "outcome": 0.12,
        "social_benefit": 0.10,
        "economic_benefit": 0.10,
        "risk_control": 0.08,
        "schedule": 0.10,
        "compliance": 0.10
      }
    },
    "innovation_focused": {
      "name": "创新导向",
      "description": "适用于创新性要求较高的项目",
      "weights": {
        "feasibility": 0.10,
        "innovation": 0.25,
        "team": 0.10,
        "outcome": 0.15,
        "social_benefit": 0.10,
        "economic_benefit": 0.10,
        "risk_control": 0.05,
        "schedule": 0.05,
        "compliance": 0.10
      }
    },
    "application_focused": {
      "name": "应用导向",
      "description": "适用于产业化应用项目",
      "weights": {
        "feasibility": 0.20,
        "innovation": 0.10,
        "team": 0.10,
        "outcome": 0.15,
        "social_benefit": 0.10,
        "economic_benefit": 0.15,
        "risk_control": 0.10,
        "schedule": 0.05,
        "compliance": 0.05
      }
    }
  }
}
```

---

### 6. 验证自定义权重

验证用户提供的权重配置是否有效。

**请求**

```http
POST /api/v1/evaluation/weights/validate
Content-Type: application/json
```

**请求体**

```json
{
  "weights": {
    "feasibility": 0.20,
    "innovation": 0.20,
    "team": 0.10
  }
}
```

**响应（有效）**

```json
{
  "valid": true,
  "message": "权重配置有效",
  "normalized_weights": {
    "feasibility": 0.40,
    "innovation": 0.40,
    "team": 0.20,
    "outcome": 0.12,
    "social_benefit": 0.10,
    "economic_benefit": 0.10,
    "risk_control": 0.08,
    "schedule": 0.10,
    "compliance": 0.10
  }
}
```

**响应（无效）**

```json
{
  "valid": false,
  "message": "未知的维度代码: unknown_dimension",
  "errors": [
    {
      "field": "weights",
      "message": "未知的维度代码: unknown_dimension"
    }
  ]
}
```

---

## 错误响应

### 错误格式

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "details": {
      "field": "additional info"
    }
  }
}
```

### 错误码

| 错误码 | HTTP状态码 | 说明 |
|--------|-----------|------|
| PROJECT_NOT_FOUND | 404 | 项目不存在 |
| DOCUMENT_NOT_FOUND | 404 | 项目文档不存在 |
| INVALID_DIMENSION | 400 | 无效的评审维度 |
| INVALID_WEIGHT | 400 | 无效的权重配置 |
| PARSE_ERROR | 500 | 文档解析失败 |
| LLM_ERROR | 503 | LLM 服务不可用 |
| RATE_LIMIT_EXCEEDED | 429 | 请求频率超限 |
| BATCH_SIZE_EXCEEDED | 400 | 批量评审数量超限 |

---

## API 路由实现

```python
# src/services/evaluation/api.py

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

from src.common.models.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    EvaluationDimension,
    DimensionScore,
)
from src.services.evaluation.agent import EvaluationAgent
from src.services.evaluation.scorers import WeightCalculator
from src.services.evaluation.checkers import CHECKER_REGISTRY

router = APIRouter()


# ============ 请求/响应模型 ============

class BatchEvaluationRequest(BaseModel):
    """批量评审请求"""
    project_ids: List[str] = Field(..., max_length=50, description="项目ID列表")
    weights: Optional[Dict[str, float]] = Field(None, description="统一权重")
    concurrency: int = Field(default=3, ge=1, le=10, description="并发数")


class BatchEvaluationResponse(BaseModel):
    """批量评审响应"""
    total: int
    success: int
    failed: int
    results: List[dict]
    summary: dict
    errors: List[dict]


class DimensionInfo(BaseModel):
    """维度信息"""
    code: str
    name: str
    category: str
    description: str
    default_weight: float
    check_items: List[dict]
    required_sections: List[str]


class DimensionsResponse(BaseModel):
    """维度列表响应"""
    dimensions: List[DimensionInfo]


class WeightValidateRequest(BaseModel):
    """权重验证请求"""
    weights: Dict[str, float]


class WeightValidateResponse(BaseModel):
    """权重验证响应"""
    valid: bool
    message: str
    normalized_weights: Optional[Dict[str, float]] = None
    errors: Optional[List[dict]] = None


# ============ Agent 管理 ============

_agent: Optional[EvaluationAgent] = None


def get_agent() -> EvaluationAgent:
    """获取 Agent 实例（单例）"""
    global _agent
    if _agent is None:
        _agent = EvaluationAgent()
    return _agent


# ============ 路由定义 ============

@router.post("", response_model=EvaluationResult)
async def evaluate_project(request: EvaluationRequest):
    """单项目评审
    
    对单个项目进行正文评审，返回详细的评审结果。
    """
    agent = get_agent()
    try:
        result = await agent.evaluate(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评审失败: {str(e)}")


@router.post("/batch", response_model=BatchEvaluationResponse)
async def evaluate_batch(request: BatchEvaluationRequest):
    """批量评审
    
    对多个项目进行批量评审，支持并发执行。
    """
    import asyncio
    from datetime import datetime
    
    agent = get_agent()
    results = []
    errors = []
    
    semaphore = asyncio.Semaphore(request.concurrency)
    
    async def evaluate_one(project_id: str):
        async with semaphore:
            try:
                req = EvaluationRequest(
                    project_id=project_id,
                    weights=request.weights
                )
                result = await agent.evaluate(req)
                return {
                    "project_id": result.project_id,
                    "project_name": result.project_name,
                    "overall_score": result.overall_score,
                    "grade": result.grade,
                }, None
            except Exception as e:
                return None, {
                    "project_id": project_id,
                    "error": str(e)
                }
    
    tasks = [evaluate_one(pid) for pid in request.project_ids]
    task_results = await asyncio.gather(*tasks)
    
    for result, error in task_results:
        if result:
            results.append(result)
        if error:
            errors.append(error)
    
    # 计算汇总统计
    scores = [r["overall_score"] for r in results]
    grades = [r["grade"] for r in results]
    
    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for g in grades:
        grade_dist[g] = grade_dist.get(g, 0) + 1
    
    return BatchEvaluationResponse(
        total=len(request.project_ids),
        success=len(results),
        failed=len(errors),
        results=results,
        summary={
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "median_score": round(sorted(scores)[len(scores)//2], 2) if scores else 0,
            "grade_distribution": grade_dist,
        },
        errors=errors
    )


@router.get("/{project_id}", response_model=EvaluationResult)
async def get_evaluation(
    project_id: str,
    refresh: bool = Query(default=False, description="是否强制重新评审")
):
    """获取评审结果
    
    获取已有项目的评审结果。如果 refresh=true，则强制重新评审。
    """
    # TODO: 从缓存或数据库获取历史结果
    if refresh:
        agent = get_agent()
        request = EvaluationRequest(project_id=project_id)
        return await agent.evaluate(request)
    
    raise HTTPException(
        status_code=404, 
        detail="未找到评审结果，请使用 refresh=true 重新评审"
    )


@router.get("/dimensions", response_model=DimensionsResponse)
async def get_dimensions():
    """获取评审维度列表
    
    返回系统支持的所有评审维度及其详细信息。
    """
    from src.services.evaluation.checkers import get_all_dimensions, get_checker
    
    dimensions = []
    dimension_categories = {
        "feasibility": "核心维度",
        "innovation": "核心维度",
        "team": "核心维度",
        "outcome": "成果维度",
        "social_benefit": "成果维度",
        "economic_benefit": "成果维度",
        "risk_control": "管理维度",
        "schedule": "管理维度",
        "compliance": "管理维度",
    }
    
    for dim_code in get_all_dimensions():
        checker = get_checker(dim_code)
        dimensions.append(DimensionInfo(
            code=dim_code,
            dimension_name=checker.dimension_name,
            category=dimension_categories.get(dim_code, "其他"),
            description=f"{checker.dimension_name}评审",
            default_weight=checker.default_weight,
            check_items=checker.CHECK_ITEMS,
            required_sections=getattr(checker, 'REQUIRED_SECTIONS', []),
        ))
    
    return DimensionsResponse(dimensions=dimensions)


@router.get("/weights/templates")
async def get_weight_templates():
    """获取权重模板
    
    返回预设的权重配置模板列表。
    """
    return {"templates": WeightCalculator.WEIGHT_TEMPLATES}


@router.post("/weights/validate", response_model=WeightValidateResponse)
async def validate_weights(request: WeightValidateRequest):
    """验证权重配置
    
    验证用户提供的权重配置是否有效。
    """
    errors = []
    
    # 检查维度代码
    for dim in request.weights:
        if dim not in CHECKER_REGISTRY:
            errors.append({
                "field": "weights",
                "message": f"未知的维度代码: {dim}"
            })
    
    if errors:
        return WeightValidateResponse(
            valid=False,
            message=errors[0]["message"],
            errors=errors
        )
    
    # 验证权重值
    for dim, weight in request.weights.items():
        if weight < 0 or weight > 1:
            errors.append({
                "field": f"weights.{dim}",
                "message": f"权重值必须在0-1之间，当前值: {weight}"
            })
    
    if errors:
        return WeightValidateResponse(
            valid=False,
            message="权重值无效",
            errors=errors
        )
    
    # 归一化权重
    normalized = WeightCalculator.get_weights(custom_weights=request.weights)
    
    return WeightValidateResponse(
        valid=True,
        message="权重配置有效",
        normalized_weights=normalized
    )
```

---

## 集成到主应用

```python
# src/app/routes/evaluation.py
from fastapi import APIRouter
from src.services.evaluation.api import router as evaluation_router

router = APIRouter()
router.include_router(evaluation_router)


# src/app/main.py (添加)
from src.app.routes import evaluation

app.include_router(
    evaluation.router, 
    prefix="/api/v1/evaluation", 
    tags=["正文评审"]
)
```

---

## 使用示例

### Python 调用

```python
import httpx
import asyncio

async def evaluate_project():
    async with httpx.AsyncClient() as client:
        # 单项目评审
        response = await client.post(
            "http://localhost:8000/api/v1/evaluation",
            json={
                "project_id": "202520014",
                "dimensions": ["feasibility", "innovation"],
                "weights": {"feasibility": 0.6, "innovation": 0.4}
            }
        )
        result = response.json()
        print(f"总分: {result['overall_score']}, 等级: {result['grade']}")

asyncio.run(evaluate_project())
```

### curl 调用

```bash
# 单项目评审
curl -X POST "http://localhost:8000/api/v1/evaluation" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "202520014"}'

# 获取维度列表
curl "http://localhost:8000/api/v1/evaluation/dimensions"

# 获取权重模板
curl "http://localhost:8000/api/v1/evaluation/weights/templates"
```