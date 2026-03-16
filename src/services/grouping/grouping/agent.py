"""
分组 Agent

负责协调各组件完成项目分组

优化版本：
1. 直接使用Embedding聚类，不需要LLM分析
2. 批量LLM调用
3. 抽样质量评估
4. 结果缓存
"""
import json
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


# 缓存配置（简化版）
_QUALITY_CACHE: Dict[str, float] = {}


class GroupingAgent:
    """分组 Agent
    
    协调各组件完成项目分组（优化版）
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
    
    def _get_project_text(self, project: Project) -> str:
        """获取项目文本（用于向量化）"""
        parts = []
        if project.xmmc:
            parts.append(project.xmmc)
        if project.gjc:
            parts.append(project.gjc)
        if project.xmjj:
            # 简单清洗HTML
            import re
            clean = re.sub(r'<[^>]+>', '', project.xmjj)
            clean = re.sub(r'\s+', ' ', clean)
            if len(clean) > 1000:
                clean = clean[:1000]
            parts.append(clean)
        return " ".join(parts)
    
    async def group_projects(
        self,
        request: GroupingRequest
    ) -> GroupingResult:
        """执行项目分组（优化版）
        
        优化点：
        1. 直接用Embedding聚类，跳过LLM分析
        2. 抽样做质量评估
        3. 批量LLM调用
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
        
        # 2. 项目向量化（直接用项目文本，不需要LLM分析）
        project_vectors = self._generate_vectors(projects)
        
        # 3. 计算分组数
        group_count = request.group_count
        if group_count is None:
            group_count = self.cluster.calculate_optimal_groups(
                len(projects), request.max_per_group
            )
        
        # 4. 聚类分组
        cluster_labels = self.cluster.fit_predict(project_vectors, group_count)
        
        # 5. 质量评估（抽样 + 批量）
        quality_scores = await self._assess_quality_sampled(
            projects, cluster_labels, group_count
        )
        
        # 6. 构建项目字典
        project_dicts = [
            {"id": p.id, "xmmc": p.xmmc, "ssxk1": p.ssxk1}
            for p in projects
        ]
        
        # 7. 分组优化
        groups = self.optimizer.optimize(
            cluster_labels,
            quality_scores,
            project_dicts,
            request.strategy
        )
        
        # 8. 构建结果
        result_groups = groups
        
        # 9. 统计信息
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
    
    def _generate_vectors(self, projects: List[Project]) -> np.ndarray:
        """生成项目向量
        
        直接使用项目文本，不需要LLM分析
        """
        texts = []
        for p in projects:
            text = self._get_project_text(p)
            texts.append(text)
        
        # 调用 embedder
        embeddings = self.embedder.embed_documents(texts)
        return np.array(embeddings)
    
    async def _assess_quality_sampled(
        self,
        projects: List[Project],
        cluster_labels: np.ndarray,
        group_count: int
    ) -> Dict[str, float]:
        """抽样质量评估（优化版）
        
        策略：
        1. 每个组抽取3-5个代表性项目
        2. 批量调用LLM
        3. 用抽样结果推算全组质量
        """
        quality_scores = {}
        
        # 按组分类项目
        groups = {}
        for i, label in enumerate(cluster_labels):
            if label not in groups:
                groups[label] = []
            groups[label].append((i, projects[i]))
        
        # 对每组抽样评估
        for group_id, group_projects in groups.items():
            # 抽样策略：距离中心最近的 + 随机补充
            if len(group_projects) <= 3:
                sample_indices = [i for i, _ in group_projects]
            else:
                # 简化：取前3个
                sample_indices = [i for i, _ in group_projects[:3]]
            
            # 批量评估
            sample_projects = [projects[i] for i in sample_indices]
            
            # 检查缓存
            uncached = []
            for p in sample_projects:
                if p.id not in _QUALITY_CACHE:
                    uncached.append(p)
                else:
                    quality_scores[p.id] = _QUALITY_CACHE[p.id]
            
            if uncached:
                # 批量LLM调用
                batch_scores = await self.quality_assessor.batch_assess(uncached)
                for pid, score in batch_scores.items():
                    _QUALITY_CACHE[pid] = score
                    quality_scores[pid] = score
            
            # 计算组平均分
            # group_projects 是 [(index, Project), ...]
            sample_projs = [projects[i] for i in sample_indices]
            group_avg = np.mean([quality_scores.get(p.id, 75) for p in sample_projs])
            
            # 推算到全组
            for i, p in group_projects:
                if p.id not in quality_scores:
                    quality_scores[p.id] = group_avg
        
        return quality_scores
    
    async def _assess_quality(
        self,
        projects: List[Project],
        analyzed_projects: List[ProjectAnalysis]
    ) -> Dict[str, float]:
        """评估项目质量（兼容旧接口）"""
        quality_scores = await self.quality_assessor.assess_projects(analyzed_projects)
        return {q.project_id: q.total_score for q in quality_scores}
