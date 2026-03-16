"""
分组 Agent

负责协调各组件完成项目分组
"""
import time
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

from src.common.llm import get_default_llm_client, get_default_embedding_client
from src.common.models.grouping import (
    GroupingRequest,
    GroupingResult,
    GroupingStatistics,
    GroupingStrategy,
    GroupSummary,
    Project,
    ProjectAnalysis,
    ProjectGroup,
    ProjectInGroup,
    ProjectQuality,
)
from src.services.grouping.grouping.analyzer import ProjectAnalyzer
from src.services.grouping.grouping.cluster import ProjectCluster
from src.services.grouping.grouping.optimizer import GroupOptimizer
from src.services.grouping.grouping.quality import QualityAssessor
from src.services.grouping.storage.project_repo import ProjectRepository


class GroupingAgent:
    """分组 Agent
    
    协调各组件完成项目分组
    """
    
    def __init__(
        self,
        llm: Any = None,
        embedder: Any = None,
        cluster_algorithm: str = "kmeans"
    ):
        """初始化
        
        Args:
            llm: LLM 客户端
            embedder: 向量化模型
            cluster_algorithm: 聚类算法
        """
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedding_client()
        self.analyzer = ProjectAnalyzer(self.llm)
        self.cluster = ProjectCluster(cluster_algorithm)
        self.optimizer = GroupOptimizer()
        self.quality_assessor = QualityAssessor(self.llm)
        self.project_repo = ProjectRepository()
    
    async def group_projects(
        self,
        request: GroupingRequest
    ) -> GroupingResult:
        """执行项目分组
        
        Args:
            request: 分组请求
        
        Returns:
            分组结果
        """
        start_time = time.time()
        
        # 1. 获取项目列表
        # TODO: 可通过参数控制数量，目前测试时默认限制
        limit = getattr(request, 'limit', 10) or 10
        projects = self.project_repo.get_projects_by_year(
            year=request.year,
            category=request.category,
            limit=limit
        )
        
        if not projects:
            raise ValueError(f"没有找到 {request.year} 年度的项目")
        
        # 2. 项目内容分析
        analyzed_projects = await self.analyzer.analyze_projects(projects)
        
        # 3. 项目向量化 (TODO: 实现 embedder)
        project_vectors = self._generate_vectors(analyzed_projects)
        
        # 4. 计算分组数
        group_count = request.group_count
        if group_count is None:
            group_count = self.cluster.calculate_optimal_groups(
                len(projects), request.max_per_group
            )
        
        # 5. 聚类分组
        cluster_labels = self.cluster.fit_predict(project_vectors, group_count)
        
        # 6. 质量评估 (使用 LLM)
        quality_scores = await self._assess_quality(projects, analyzed_projects)
        
        # 7. 构建项目字典列表
        project_dicts = [
            {
                "id": p.id,
                "xmmc": p.xmmc,
                "ssxk1": p.ssxk1
            }
            for p in projects
        ]
        
        # 8. 分组优化
        groups = self.optimizer.optimize(
            cluster_labels,
            quality_scores,
            project_dicts,
            request.strategy
        )
        
        # 9. 计算统计信息
        statistics = self._calculate_statistics(groups)
        
        # 10. 构建结果
        result = GroupingResult(
            id=f"group_{int(time.time() * 1000)}",
            year=request.year,
            groups=groups,
            statistics=statistics
        )
        
        return result
    
    def _generate_vectors(
        self,
        analyzed_projects: List[ProjectAnalysis]
    ) -> np.ndarray:
        """生成项目向量
        
        使用 Embedding 模型将项目文本向量化
        
        Args:
            analyzed_projects: 分析后的项目
        
        Returns:
            向量矩阵
        """
        # 提取文本列表
        texts = []
        for p in analyzed_projects:
            # 融合文本用于向量化
            text_parts = []
            if p.innovation:
                text_parts.append(p.innovation)
            if p.tech_direction:
                text_parts.append(p.tech_direction)
            if p.research_field:
                text_parts.append(p.research_field)
            if p.application:
                text_parts.append(p.application)
            
            text = " ".join(text_parts) if text_parts else p.text or ""
            texts.append(text)
        
        # 调用 Embedding API
        # embed_documents 返回 List[List[float]]
        embeddings = self.embedder.embed_documents(texts)
        
        return np.array(embeddings)
    
    async def _assess_quality(
        self,
        projects: List[Project],
        analyzed_projects: List[ProjectAnalysis] = None
    ) -> Dict[str, float]:
        """评估项目质量
        
        使用 LLM 评估项目的创新性、技术难度、应用价值
        
        Args:
            projects: 项目列表
            analyzed_projects: 项目分析结果列表
        
        Returns:
            项目ID -> 质量分数
        """
        # 构建分析结果字典
        analyses_dict = {}
        if analyzed_projects:
            for a in analyzed_projects:
                analyses_dict[a.project_id] = a
        
        # 调用质量评估器
        quality_results = await self.quality_assessor.assess_projects(
            projects, analyses_dict
        )
        
        # 提取总分数
        return {
            project_id: quality.total_score
            for project_id, quality in quality_results.items()
        }
    
    def _calculate_statistics(self, groups: List[ProjectGroup]) -> GroupingStatistics:
        """计算统计信息
        
        Args:
            groups: 分组列表
        
        Returns:
            统计信息
        """
        total_projects = sum(g.summary.count for g in groups)
        group_count = len(groups)
        
        # 计算均衡度
        balance_score = self.optimizer.calculate_balance_score(groups)
        
        # 计算平均值
        avg_projects = total_projects / group_count if group_count > 0 else 0
        
        scores = [g.summary.avg_score for g in groups if g.summary.count > 0]
        avg_quality = sum(scores) / len(scores) if scores else 0
        
        return GroupingStatistics(
            total_projects=total_projects,
            group_count=group_count,
            balance_score=balance_score,
            avg_projects_per_group=avg_projects,
            avg_quality_per_group=avg_quality
        )
