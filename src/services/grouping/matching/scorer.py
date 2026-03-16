"""
匹配度计算器

计算项目与专家之间的匹配度
"""
from typing import Any, Dict, List, Tuple

import numpy as np

from src.common.models.grouping import Expert, ExpertProfile, Project, ProjectAnalysis


class MatchScorer:
    """匹配度计算器
    
    计算项目与专家之间的匹配度
    """
    
    def __init__(self, embedder: Any = None):
        """初始化
        
        Args:
            embedder: 向量化模型
        """
        self.embedder = embedder
    
    def calculate_match_score(
        self,
        project: Project,
        project_analysis: ProjectAnalysis,
        expert: Expert,
        expert_profile: ExpertProfile
    ) -> float:
        """计算单个项目-专家匹配度
        
        Args:
            project: 项目
            project_analysis: 项目分析结果
            expert: 专家
            expert_profile: 专家画像
        
        Returns:
            匹配度分数 (0-100)
        """
        # 1. 研究方向匹配 (50%)
        research_score = self._calculate_research_match(
            project_analysis, expert_profile
        )
        
        # 2. 学科匹配 (30%)
        subject_score = self._calculate_subject_match(
            project, expert
        )
        
        # 3. 历史评审经验 (20%)
        history_score = 50.0  # 简化实现
        
        # 加权计算
        score = research_score * 0.5 + subject_score * 0.3 + history_score * 0.2
        
        return score
    
    def _calculate_research_match(
        self,
        project: ProjectAnalysis,
        expert: ExpertProfile
    ) -> float:
        """计算研究方向匹配度
        
        Args:
            project_analysis: 项目分析结果
            expert_profile: 专家画像
        
        Returns:
            匹配度 (0-100)
        """
        if not project.research_field or not expert.keywords:
            return 50.0  # 默认分数
        
        # 提取项目研究领域关键词
        project_keywords = set()
        for field in [project.research_field, project.tech_direction, project.application]:
            if field:
                # 分割并清理
                keywords = [k.strip() for k in field.split(',')]
                project_keywords.update(keywords)
        
        # 提取专家关键词
        expert_keywords = set(expert.keywords)
        
        # 计算交集
        overlap = project_keywords & expert_keywords
        
        if not overlap:
            return 30.0
        
        # 计算匹配度
        match_ratio = len(overlap) / max(len(project_keywords), 1)
        return min(100.0, 30.0 + match_ratio * 70.0)
    
    def _calculate_subject_match(
        self,
        project: Project,
        expert: Expert
    ) -> float:
        """计算学科匹配度
        
        Args:
            project: 项目
            expert: 专家
        
        Returns:
            匹配度 (0-100)
        """
        project_subjects = []
        if project.ssxk1:
            project_subjects.append(project.ssxk1[:2])  # 取前2位作为大类
        if project.ssxk2:
            project_subjects.append(project.ssxk2[:2])
        
        expert_subjects = []
        for i in range(1, 6):
            code = getattr(expert, f'sxxk{i}', None)
            if code:
                expert_subjects.append(code[:2])
        
        if not project_subjects or not expert_subjects:
            return 50.0  # 默认分数
        
        # 计算交集
        overlap = set(project_subjects) & set(expert_subjects)
        
        if not overlap:
            return 30.0
        
        # 计算匹配度
        match_ratio = len(overlap) / max(len(project_subjects), 1)
        return min(100.0, 40.0 + match_ratio * 60.0)
    
    def calculate_matrix(
        self,
        project_vectors: np.ndarray,
        expert_vectors: np.ndarray
    ) -> np.ndarray:
        """计算匹配度矩阵
        
        Args:
            project_vectors: 项目向量矩阵 (n_projects, n_features)
            expert_vectors: 专家向量矩阵 (n_experts, n_features)
        
        Returns:
            匹配度矩阵 (n_projects, n_experts)
        """
        # 计算余弦相似度
        project_norm = project_vectors / (
            np.linalg.norm(project_vectors, axis=1, keepdims=True) + 1e-8
        )
        expert_norm = expert_vectors / (
            np.linalg.norm(expert_vectors, axis=1, keepdims=True) + 1e-8
        )
        
        # 相似度矩阵
        similarity = project_norm @ expert_norm.T
        
        # 转换为分数 (0-100)
        scores = similarity * 100
        
        return scores
    
    def rank_experts(
        self,
        project_id: str,
        expert_scores: List[Tuple[str, str, float]]
    ) -> List[Dict]:
        """对专家排序
        
        Args:
            project_id: 项目ID
            expert_scores: [(expert_id, expert_name, score), ...]
        
        Returns:
            排序后的专家列表
        """
        # 按分数降序排序
        sorted_experts = sorted(expert_scores, key=lambda x: x[2], reverse=True)
        
        # 构建结果
        results = []
        for expert_id, expert_name, score in sorted_experts:
            results.append({
                "expert_id": expert_id,
                "xm": expert_name,
                "match_score": score,
                "reason": self._generate_match_reason(score)
            })
        
        return results
    
    def _generate_match_reason(self, score: float) -> str:
        """生成匹配原因
        
        Args:
            score: 匹配度分数
        
        Returns:
            匹配原因
        """
        if score >= 90:
            return "研究方向高度匹配"
        elif score >= 80:
            return "研究领域高度相关"
        elif score >= 70:
            return "技术方向匹配"
        elif score >= 60:
            return "学科背景匹配"
        else:
            return "基本匹配"
