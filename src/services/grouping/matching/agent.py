"""
匹配 Agent

负责协调各组件完成专家匹配
"""
import time
from typing import Any, Dict, List, Optional

import numpy as np

from src.common.llm import get_default_llm_client, get_default_embedding_client
from src.common.models.grouping import (
    Expert,
    ExpertProfile,
    MatchingRequest,
    MatchingResult,
    MatchingStatistics,
    ProjectGroup,
)
from src.services.grouping.matching.optimizer import MatchingOptimizer
from src.services.grouping.matching.profiler import ExpertProfiler
from src.services.grouping.matching.scorer import MatchScorer
from src.services.grouping.storage.expert_repo import ExpertRepository


class MatchingAgent:
    """匹配 Agent
    
    协调各组件完成专家匹配
    """
    
    def __init__(
        self,
        llm: Any = None,
        embedder: Any = None
    ):
        """初始化
        
        Args:
            llm: LLM 客户端
            embedder: 向量化模型
        """
        self.llm = llm or get_default_llm_client()
        self.embedder = embedder or get_default_embedding_client()
        self.profiler = ExpertProfiler(self.llm)
        self.scorer = MatchScorer(self.embedder)
        self.optimizer = MatchingOptimizer()
        self.expert_repo = ExpertRepository()
    
    async def match_experts(
        self,
        group: ProjectGroup,
        group_id: int,
        request: MatchingRequest
    ) -> MatchingResult:
        """执行专家匹配
        
        Args:
            group: 分组
            group_id: 分组ID
            request: 匹配请求
        
        Returns:
            匹配结果
        """
        # 1. 获取分组内项目的学科代码
        subject_codes = self._extract_subject_codes(group)
        
        # 2. 获取专家列表
        experts = self.expert_repo.get_experts(
            subject_codes=subject_codes,
            limit=1000  # 限制数量
        )
        
        if not experts:
            raise ValueError("没有找到合适的专家")
        
        # 3. 专家画像构建
        expert_profiles = await self.profiler.profile_experts(experts)
        
        # 4. 专家向量化 (TODO: 实现 embedder)
        expert_vectors = self._generate_vectors(expert_profiles)
        
        # 5. 项目向量化 (简化: 使用随机向量)
        project_vectors = self._generate_project_vectors(group)
        
        # 6. 计算匹配度矩阵
        match_scores = self.scorer.calculate_matrix(project_vectors, expert_vectors)
        
        # 7. 转换为项目字典
        projects = [
            {
                "id": p.project_id,
                "xmmc": p.xmmc,
                "cddw_mc": ""  # TODO: 从项目信息获取
            }
            for p in group.projects
        ]
        
        # 8. 全局最优匹配
        assignments = self.optimizer.optimize(
            projects=projects,
            experts=experts,
            match_scores=match_scores,
            experts_per_project=request.experts_per_project,
            min_experts_per_group=request.min_experts_per_group,
            max_reviews_per_expert=request.max_reviews_per_expert,
            avoid_relations=request.avoid_relations
        )
        
        # 9. 计算统计信息
        statistics = self.optimizer.calculate_statistics(
            assignments=assignments,
            projects=projects,
            experts=experts,
            experts_per_project=request.experts_per_project
        )
        
        # 10. 生成警告
        warnings = self._generate_warnings(assignments)
        
        # 11. 构建结果
        result = MatchingResult(
            id=f"match_{int(time.time() * 1000)}",
            group_id=group_id,
            matches=assignments,
            statistics=statistics,
            warnings=warnings
        )
        
        return result
    
    def _extract_subject_codes(self, group: ProjectGroup) -> List[str]:
        """提取分组内项目的学科代码
        
        Args:
            group: 分组
        
        Returns:
            学科代码列表
        """
        subject_codes = []
        for project in group.projects:
            if getattr(project, "subject_code", None):
                subject_codes.append(project.subject_code)

        # 若分组项目跨学科，允许为空，后续专家库按全量召回
        return list(dict.fromkeys(subject_codes))
    
    def _generate_vectors(
        self,
        expert_profiles: List[ExpertProfile]
    ) -> np.ndarray:
        """生成专家向量
        
        使用 Embedding 模型将专家文本向量化
        
        Args:
            expert_profiles: 专家画像列表
        
        Returns:
            向量矩阵
        """
        # 提取文本列表
        texts = []
        for p in expert_profiles:
            # 融合文本用于向量化
            text_parts = []
            if p.main_research_area:
                text_parts.append(p.main_research_area)
            if p.sub_research_fields:
                text_parts.extend(p.sub_research_fields)
            if p.tech_expertise:
                text_parts.extend(p.tech_expertise)
            if p.keywords:
                text_parts.extend(p.keywords)
            
            text = " ".join(text_parts) if text_parts else p.text or ""
            texts.append(text)
        
        # 调用 Embedding API
        embeddings = self.embedder.embed_documents(texts)
        
        return np.array(embeddings)
    
    def _generate_project_vectors(
        self,
        group: ProjectGroup
    ) -> np.ndarray:
        """生成项目向量
        
        使用 Embedding 模型将项目文本向量化
        
        Args:
            group: 分组
        
        Returns:
            向量矩阵
        """
        # 提取文本列表
        texts = []
        for p in group.projects:
            # 使用项目名称作为向量化文本
            text = p.xmmc or ""
            texts.append(text)
        
        # 调用 Embedding API
        embeddings = self.embedder.embed_documents(texts)
        
        return np.array(embeddings)
    
    def _generate_warnings(
        self,
        assignments: List
    ) -> List[str]:
        """生成警告信息
        
        Args:
            assignments: 匹配结果
        
        Returns:
            警告列表
        """
        warnings = []
        
        for assignment in assignments:
            for expert in assignment.experts:
                if expert.avoidance and not expert.avoidance.avoided:
                    if expert.avoidance.severity == "low":
                        warnings.append(
                            f"专家 {expert.xm} 与项目 {assignment.project_id} "
                            f"存在关系: {expert.avoidance.reason}"
                        )
        
        return warnings
