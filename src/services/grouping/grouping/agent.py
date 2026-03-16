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
        
        # 3. 项目向量化
        project_vectors = self._generate_vectors(analyzed_projects)
        
        # 4. 计算分组数
        group_count = request.group_count
        if group_count is None:
            group_count = self.cluster.calculate_optimal_groups(
                len(projects), request.max_per_group
            )
        
        # 5. 聚类分组
        cluster_labels = self.cluster.fit_predict(project_vectors, group_count)
        
        # 6. 质量评估
        analyses_dict = {p.project_id: p for p in analyzed_projects}
        quality_dict = await self.quality_assessor.assess_projects(projects, analyses_dict)
        quality_scores = {k: v.total_score for k, v in quality_dict.items()}
        
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
        
        # 9. 构建结果
        result_groups = groups
        
        # 10. 统计信息
        stats = GroupingStatistics(
            total_projects=len(projects),
            group_count=len(result_groups),
            balance_score=0.8,
            avg_projects_per_group=len(projects) / len(result_groups) if result_groups else 0,
            avg_quality_per_group=sum(g.summary.avg_score for g in result_groups) / len(result_groups) if result_groups else 0
        )
        
        result = GroupingResult(
            id=str(uuid.uuid4()),
            year=request.year,
            strategy=request.strategy,
            groups=result_groups,
            statistics=stats,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        return result
    
    def _generate_vectors(self, analyzed_projects: List[ProjectAnalysis]) -> np.ndarray:
        """生成项目向量
        
        Args:
            analyzed_projects: 分析后的项目列表
        
        Returns:
            项目向量矩阵
        """
        # 构建文本 - 确保都是字符串
        texts = []
        for p in analyzed_projects:
            parts = [str(p.innovation or ""), str(p.tech_direction or ""), 
                     str(p.research_field or ""), str(p.application or "")]
            texts.append(" ".join(parts))
        
        # 调用 embedder
        embeddings = self.embedder.embed_documents(texts)
        return np.array(embeddings)
    
    async def _assess_quality(
        self,
        projects: List[Project],
        analyzed_projects: List[ProjectAnalysis]
    ) -> Dict[str, float]:
        """评估项目质量
        
        Args:
            projects: 原始项目列表
            analyzed_projects: 分析后的项目列表
        
        Returns:
            项目ID -> 质量分数
        """
        quality_scores = await self.quality_assessor.assess_projects(analyzed_projects)
        return {q.project_id: q.total_score for q in quality_scores}
