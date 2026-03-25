# 🤖 EvaluationAgent 设计

## Agent 职责

EvaluationAgent 是正文评审服务的核心编排组件，负责：

1. **数据获取**：从数据库获取项目基本信息和文档
2. **文档解析**：调用解析器提取章节内容
3. **检查器调度**：并行执行各维度检查
4. **结果聚合**：汇总检查结果，计算评分
5. **报告生成**：生成最终评审报告

---

## Agent 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                       EvaluationAgent                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│  │ 数据获取层  │    │ 检查调度层  │    │ 结果聚合层  │            │
│  │             │    │             │    │             │            │
│  │ ProjectRepo │    │ CheckerPool │    │ Scorer      │            │
│  │ DocParser   │    │ (并发控制)  │    │ Reporter    │            │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘            │
│         │                  │                  │                    │
│         └──────────────────┼──────────────────┘                    │
│                            │                                        │
│                            ▼                                        │
│                   ┌────────────────┐                               │
│                   │  Common Layer  │                               │
│                   │  llm / file    │                               │
│                   └────────────────┘                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent 实现

```python
# src/services/evaluation/agent.py

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.evaluation import (
    EvaluationDimension,
    EvaluationRequest,
    EvaluationResult,
    DimensionScore,
    DEFAULT_WEIGHTS,
)
from src.services.evaluation.checkers import get_checker, CHECKER_REGISTRY
from src.services.evaluation.scorers import DimensionScorer, WeightCalculator, ReportGenerator
from src.services.evaluation.parsers import DocumentParser
from src.services.evaluation.storage import ProjectRepository


logger = logging.getLogger(__name__)


class EvaluationAgent:
    """正文评审 Agent"""
    
    def __init__(
        self,
        llm: Any = None,
        weights: Optional[Dict[str, float]] = None,
        concurrency: int = 5,
        timeout: int = 60,
    ):
        """
        初始化 Agent
        
        Args:
            llm: LLM 客户端实例
            weights: 权重配置
            concurrency: 并发数（同时执行的检查器数量）
            timeout: 超时时间（秒）
        """
        self.llm = llm or get_default_llm_client()
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.concurrency = concurrency
        self.timeout = timeout
        
        # 初始化组件
        self.project_repo = ProjectRepository()
        self.doc_parser = DocumentParser()
        self.scorer = DimensionScorer(weights=self.weights)
        self.reporter = ReportGenerator()
    
    async def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """
        执行评审
        
        Args:
            request: 评审请求
        
        Returns:
            EvaluationResult: 评审结果
        
        Raises:
            ValueError: 参数错误
            RuntimeError: 评审过程出错
        """
        start_time = datetime.now()
        logger.info(f"开始评审项目: {request.project_id}")
        
        try:
            # Step 1: 获取项目数据
            project_info = await self._get_project_info(request.project_id)
            project_name = project_info.get("xmmc", "")
            logger.debug(f"获取项目信息: {project_name}")
            
            # Step 2: 解析文档
            sections = await self._parse_documents(request.project_id)
            logger.debug(f"解析文档完成，共 {len(sections)} 个章节")
            
            # Step 3: 确定评审维度
            dimensions = request.dimensions or list(EvaluationDimension)
            logger.debug(f"评审维度: {dimensions}")
            
            # Step 4: 设置权重
            weights = WeightCalculator.get_weights(
                custom_weights=request.weights
            )
            self.scorer = DimensionScorer(weights=weights)
            
            # Step 5: 并行执行检查
            check_results = await self._run_checkers_parallel(
                dimensions=dimensions,
                project_info=project_info,
                sections=sections,
            )
            logger.debug(f"检查完成，共 {len(check_results)} 个维度")
            
            # Step 6: 聚合评分
            dimension_scores = []
            raw_scores = {}
            
            for result in check_results:
                dim_score = self.scorer.build_dimension_score(
                    dimension=result.dimension,
                    score=result.score,
                    opinion=result.opinion,
                    issues=result.issues,
                    highlights=result.highlights,
                    confidence=result.confidence,
                )
                dimension_scores.append(dim_score)
                raw_scores[result.dimension] = result.score
            
            # Step 7: 计算总分和等级
            overall_score = self.scorer.calculate_weighted_score(raw_scores)
            grade = self.scorer.determine_grade(overall_score)
            logger.info(f"评审完成: 总分={overall_score}, 等级={grade}")
            
            # Step 8: 生成综合意见
            summary = self.scorer.generate_summary(dimension_scores, grade)
            
            # Step 9: 生成报告
            result = self.reporter.generate(
                project_id=request.project_id,
                project_name=project_name,
                dimension_scores=dimension_scores,
                overall_score=overall_score,
                grade=grade,
                summary=summary,
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"评审耗时: {elapsed:.2f}秒")
            
            return result
            
        except Exception as e:
            logger.error(f"评审失败: {e}")
            raise RuntimeError(f"评审过程出错: {e}") from e
    
    async def evaluate_batch(
        self, 
        project_ids: List[str],
        weights: Optional[Dict[str, float]] = None,
    ) -> List[EvaluationResult]:
        """
        批量评审
        
        Args:
            project_ids: 项目ID列表
            weights: 权重配置
        
        Returns:
            List[EvaluationResult]: 评审结果列表
        """
        results = []
        
        for project_id in project_ids:
            try:
                request = EvaluationRequest(
                    project_id=project_id,
                    weights=weights,
                )
                result = await self.evaluate(request)
                results.append(result)
            except Exception as e:
                logger.error(f"项目 {project_id} 评审失败: {e}")
                # 继续处理下一个项目
        
        return results
    
    async def _get_project_info(self, project_id: str) -> Dict[str, Any]:
        """
        获取项目基本信息
        
        Args:
            project_id: 项目ID
        
        Returns:
            Dict: 项目信息字典
        """
        return await self.project_repo.get_project_info(project_id)
    
    async def _parse_documents(self, project_id: str) -> Dict[str, str]:
        """
        解析项目文档
        
        Args:
            project_id: 项目ID
        
        Returns:
            Dict[str, str]: 章节内容字典
        """
        return await self.doc_parser.parse(project_id)
    
    async def _run_checkers_parallel(
        self,
        dimensions: List[str],
        project_info: Dict[str, Any],
        sections: Dict[str, str],
    ) -> List[Any]:
        """
        并行执行检查器
        
        Args:
            dimensions: 维度列表
            project_info: 项目信息
            sections: 章节内容
        
        Returns:
            List[CheckResult]: 检查结果列表
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def run_with_semaphore(dim: str):
            async with semaphore:
                try:
                    checker = get_checker(dim, llm=self.llm)
                    result = await asyncio.wait_for(
                        checker.check(
                            project_info=project_info,
                            sections=sections,
                        ),
                        timeout=self.timeout,
                    )
                    return result
                except asyncio.TimeoutError:
                    logger.warning(f"检查器 {dim} 超时")
                    from src.services.evaluation.checkers.base import CheckResult
                    return CheckResult(
                        dimension=dim,
                        score=5.0,
                        confidence=0.0,
                        opinion="检查超时，未能完成评审",
                        issues=["检查超时"],
                        highlights=[],
                    )
                except Exception as e:
                    logger.error(f"检查器 {dim} 执行失败: {e}")
                    from src.services.evaluation.checkers.base import CheckResult
                    return CheckResult(
                        dimension=dim,
                        score=5.0,
                        confidence=0.0,
                        opinion=f"检查失败: {str(e)}",
                        issues=[str(e)],
                        highlights=[],
                    )
        
        tasks = [run_with_semaphore(dim) for dim in dimensions]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        return results
```

---

## 并发控制

### 信号量机制

使用 `asyncio.Semaphore` 控制并发数，避免过多并发请求导致 LLM API 限流。

```python
# 并发执行示例
semaphore = asyncio.Semaphore(5)  # 最多 5 个并发

async def run_with_semaphore(dim: str):
    async with semaphore:
        # 执行检查
        checker = get_checker(dim, llm=self.llm)
        return await checker.check(...)
```

### 超时控制

每个检查器设置超时时间，避免某个维度检查阻塞整个流程。

```python
result = await asyncio.wait_for(
    checker.check(...),
    timeout=60,  # 60秒超时
)
```

---

## 错误处理

### 错误类型

| 错误类型 | 处理方式 |
|----------|----------|
| 项目不存在 | 抛出 `ValueError` |
| 文档解析失败 | 返回空章节，继续评审 |
| 检查器超时 | 返回默认分数，置信度为 0 |
| 检查器异常 | 返回默认分数，记录错误信息 |
| LLM 调用失败 | 由检查器内部处理 |

### 错误传播

```
┌─────────────────────────────────────────────────────────────┐
│                       错误处理流程                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  API Layer                                                   │
│      │                                                       │
│      ▼                                                       │
│  ┌─────────────────────────────────────┐                   │
│  │ try:                                │                   │
│  │     result = await agent.evaluate() │                   │
│  │ except ValueError as e:             │                   │
│  │     return 400 error                │                   │
│  │ except RuntimeError as e:           │                   │
│  │     return 500 error                │                   │
│  └─────────────────────────────────────┘                   │
│                                                              │
│  Agent Layer                                                 │
│      │                                                       │
│      ▼                                                       │
│  ┌─────────────────────────────────────┐                   │
│  │ try:                                │                   │
│  │     checker.check()                 │                   │
│  │ except TimeoutError:                │                   │
│  │     return default result           │                   │
│  │ except Exception as e:              │                   │
│  │     return error result             │                   │
│  └─────────────────────────────────────┘                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 性能优化

### LLM 调用优化

1. **并发控制**：限制并发数，避免 API 限流
2. **结果缓存**：相同输入缓存 LLM 结果（可选）
3. **批量调用**：未来可支持批量 LLM 调用

### 文档解析优化

1. **懒加载**：按需解析文档
2. **缓存机制**：缓存解析结果
3. **增量解析**：只解析变更部分

### 超时策略

```python
# 各层级超时配置
CHECKER_TIMEOUT = 60        # 单个检查器超时
AGENT_TIMEOUT = 300         # 整体评审超时
LLM_TIMEOUT = 30            # LLM 调用超时
```

---

## 使用示例

### 单项目评审

```python
from src.services.evaluation.agent import EvaluationAgent
from src.common.models.evaluation import EvaluationRequest

# 初始化 Agent
agent = EvaluationAgent(
    concurrency=5,
    timeout=60,
)

# 创建请求
request = EvaluationRequest(
    project_id="202520014",
    dimensions=["feasibility", "innovation", "team"],  # 可选指定维度
    weights={"feasibility": 0.2, "innovation": 0.3, "team": 0.2},  # 可选自定义权重
)

# 执行评审
result = await agent.evaluate(request)

print(f"总分: {result.overall_score}")
print(f"等级: {result.grade}")
print(f"意见: {result.summary}")
```

### 批量评审

```python
# 批量评审
project_ids = ["202520014", "202520036", "202520058"]
results = await agent.evaluate_batch(project_ids)

for result in results:
    print(f"{result.project_name}: {result.grade}")
```

### 使用权重模板

```python
# 使用预设权重模板
from src.services.evaluation.scorers import WeightCalculator

weights = WeightCalculator.get_weights(template="innovation_focused")
agent = EvaluationAgent(weights=weights)

request = EvaluationRequest(project_id="202520014")
result = await agent.evaluate(request)
```

---

## 相关文档

- [← 评分器设计](05-scorer.md)
- [正文解析器设计 →](07-parsers.md)