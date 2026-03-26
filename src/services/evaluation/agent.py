"""
评审智能体

正文评审服务的核心控制器，协调解析器、检查器和评分器完成评审任务。
"""
import asyncio
from typing import Any, Dict, List, Optional

from src.common.llm import get_default_llm_client
from src.common.models.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    CheckResult,
    DimensionScore,
)
from .config import EvaluationConfig, evaluation_config
from .checkers import (
    BaseChecker,
    FeasibilityChecker,
    InnovationChecker,
    TeamChecker,
    OutcomeChecker,
    SocialBenefitChecker,
    EconomicBenefitChecker,
    RiskControlChecker,
    ScheduleChecker,
    ComplianceChecker,
)
from .parsers import DocumentParser
from .scorers import EvaluationScorer
from .storage import EvaluationProjectRepository, EvaluationStorage


class EvaluationAgent:
    """评审智能体
    
    负责：
    1. 协调文档解析
    2. 调度检查器执行
    3. 综合评分结果
    4. 生成评审报告
    """
    
    # 维度到检查器的映射
    DIMENSION_CHECKERS = {
        "feasibility": FeasibilityChecker,
        "innovation": InnovationChecker,
        "team": TeamChecker,
        "outcome": OutcomeChecker,
        "social_benefit": SocialBenefitChecker,
        "economic_benefit": EconomicBenefitChecker,
        "risk_control": RiskControlChecker,
        "schedule": ScheduleChecker,
        "compliance": ComplianceChecker,
    }
    
    def __init__(
        self,
        config: Optional[EvaluationConfig] = None,
        llm: Optional[Any] = None,
    ):
        """初始化评审智能体
        
        Args:
            config: 配置实例
            llm: LLM实例
        """
        self.config = config or evaluation_config
        self.llm = llm or get_default_llm_client()
        self.parser = DocumentParser()
        self.scorer = EvaluationScorer()
        self.storage = EvaluationStorage()
        self.project_repo = EvaluationProjectRepository()
        
        # 初始化检查器实例（延迟加载）
        self._checkers: Dict[str, BaseChecker] = {}
    
    def get_checker(self, dimension: str) -> Optional[BaseChecker]:
        """获取指定维度的检查器
        
        Args:
            dimension: 维度代码
            
        Returns:
            Optional[BaseChecker]: 检查器实例
        """
        if dimension in self._checkers:
            return self._checkers[dimension]
        
        checker_class = self.DIMENSION_CHECKERS.get(dimension)
        if checker_class:
            checker = checker_class(llm=self.llm)
            self._checkers[dimension] = checker
            return checker
        
        return None
    
    async def evaluate(
        self,
        request: EvaluationRequest,
        file_path: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """执行评审
        
        Args:
            request: 评审请求
            file_path: 文档路径（与content二选一）
            content: 已解析的文档内容（与file_path二选一）
            
        Returns:
            EvaluationResult: 评审结果
        """
        # 1. 解析文档（如果提供的是文件路径）
        if content is None:
            if file_path is None:
                raise ValueError("必须提供 file_path 或 content 参数")
            content = await self.parser.parse(file_path)
        
        # 2. 获取要评审的维度
        dimensions = request.get_dimensions()
        
        # 3. 验证权重
        weights = request.weights or self.config.default_weights
        valid, message, normalized_weights = self.config.validate_weights(weights)
        if not valid:
            raise ValueError(f"权重验证失败: {message}")
        
        # 4. 并行执行检查
        check_results = await self._run_checks(content, dimensions)
        
        # 5. 综合评分
        result = self.scorer.build_result(
            project_id=request.project_id,
            project_name=content.get("项目名称"),
            check_results=check_results,
            weights=normalized_weights,
        )
        
        # 6. 保存结果
        await self.storage.save(result)
        
        return result

    async def evaluate_by_project(self, request: EvaluationRequest) -> EvaluationResult:
        """按项目ID执行评审

        Args:
            request: 评审请求

        Returns:
            EvaluationResult: 评审结果
        """
        project_info = self.project_repo.get_project_info(request.project_id)
        if not project_info:
            raise ValueError(f"项目不存在: {request.project_id}")

        file_path = self.project_repo.get_primary_document_path(request.project_id)
        if not file_path:
            raise ValueError(
                f"未找到项目申报文档: {request.project_id}。"
                "请先配置 EVALUATION_PROJECT_DOC_ROOT，或改用 /api/v1/evaluation/evaluate/file 上传文档评审。"
            )

        content = await self.parser.parse(file_path)
        content.setdefault("项目名称", project_info.get("xmmc", ""))
        content.setdefault("项目简介", project_info.get("xmjj", ""))

        if request.include_sections:
            content = self._filter_sections(content, request.include_sections)

        return await self.evaluate(
            request=request,
            file_path=file_path,
            content=content,
        )
    
    async def _run_checks(
        self,
        content: Dict[str, Any],
        dimensions: List[str],
    ) -> List[CheckResult]:
        """并行执行各维度检查
        
        Args:
            content: 文档内容
            dimensions: 要检查的维度列表
            
        Returns:
            List[CheckResult]: 检查结果列表
        """
        tasks = []
        
        for dimension in dimensions:
            checker = self.get_checker(dimension)
            if checker:
                tasks.append(self._safe_check(checker, content))
        
        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        check_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # 检查失败，生成默认结果
                dimension = dimensions[i] if i < len(dimensions) else "unknown"
                check_results.append(CheckResult(
                    dimension=dimension,
                    score=5.0,
                    confidence=0.0,
                    opinion=f"检查异常: {str(result)}",
                    issues=["检查过程发生错误"],
                    highlights=[],
                    items=[],
                ))
            else:
                check_results.append(result)
        
        return check_results
    
    async def _safe_check(
        self,
        checker: BaseChecker,
        content: Dict[str, Any],
    ) -> CheckResult:
        """安全执行检查（带异常处理）
        
        Args:
            checker: 检查器
            content: 文档内容
            
        Returns:
            CheckResult: 检查结果
        """
        try:
            return await checker.check(content)
        except Exception as e:
            return CheckResult(
                dimension=checker.dimension,
                dimension_name=checker.dimension_name,
                score=5.0,
                confidence=0.0,
                opinion=f"检查异常: {str(e)}",
                issues=["检查过程发生错误"],
                highlights=[],
                items=[],
            )
    
    async def batch_evaluate(
        self,
        requests: List[EvaluationRequest],
        file_paths: Optional[Dict[str, str]] = None,
        concurrency: int = 3,
    ) -> List[EvaluationResult]:
        """批量评审
        
        Args:
            requests: 评审请求列表
            file_paths: 项目ID到文件路径的映射
            concurrency: 并发数
            
        Returns:
            List[EvaluationResult]: 评审结果列表
        """
        semaphore = asyncio.Semaphore(concurrency)
        
        async def _evaluate_with_semaphore(request: EvaluationRequest):
            async with semaphore:
                file_path = file_paths.get(request.project_id) if file_paths else None
                return await self.evaluate(request, file_path=file_path)
        
        tasks = [_evaluate_with_semaphore(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        final_results = []
        for result in results:
            if isinstance(result, Exception):
                # 创建空结果
                final_results.append(EvaluationResult(
                    project_id="unknown",
                    overall_score=0,
                    grade="E",
                    dimension_scores=[],
                    summary=f"评审失败: {str(result)}",
                    recommendations=[],
                ))
            else:
                final_results.append(result)
        
        return final_results

    def _filter_sections(
        self,
        content: Dict[str, Any],
        include_sections: List[str],
    ) -> Dict[str, Any]:
        """按 include_sections 过滤章节"""
        if not include_sections:
            return content

        normalized = [s.strip() for s in include_sections if s.strip()]
        if not normalized:
            return content

        filtered: Dict[str, Any] = {}
        for section in normalized:
            for key, value in content.items():
                if key in ("项目名称", "项目简介"):
                    continue
                if key == section or section in key or key in section:
                    filtered[key] = value

        if "项目名称" in content:
            filtered["项目名称"] = content["项目名称"]
        if "项目简介" in content:
            filtered["项目简介"] = content["项目简介"]

        return filtered
    
    async def get_dimension_info(self, dimension: str) -> Optional[Dict[str, Any]]:
        """获取维度信息
        
        Args:
            dimension: 维度代码
            
        Returns:
            Optional[Dict[str, Any]]: 维度信息
        """
        config = self.config.get_dimension_config(dimension)
        if not config:
            return None
        
        return {
            "code": config.code,
            "name": config.name,
            "category": config.category,
            "description": config.description,
            "default_weight": config.default_weight,
            "check_items": config.check_items,
            "required_sections": config.required_sections,
        }
    
    async def list_dimensions(self) -> List[Dict[str, Any]]:
        """列出所有维度
        
        Returns:
            List[Dict[str, Any]]: 维度信息列表
        """
        dimensions = []
        for code, config in self.config.dimensions.items():
            if config.enabled:
                dimensions.append({
                    "code": config.code,
                    "name": config.name,
                    "category": config.category,
                    "description": config.description,
                    "default_weight": config.default_weight,
                    "check_items": config.check_items,
                    "required_sections": config.required_sections,
                })
        
        return dimensions
    
    async def get_evaluation_history(
        self,
        project_id: str,
    ) -> List[EvaluationResult]:
        """获取评审历史
        
        Args:
            project_id: 项目ID
            
        Returns:
            List[EvaluationResult]: 历史评审结果
        """
        return await self.storage.list_by_project(project_id)
