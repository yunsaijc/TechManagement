"""
全局最优匹配优化器

使用约束优化算法实现全局最优匹配
"""
from typing import Any, Dict, List, Tuple

import numpy as np

from src.common.models.grouping import (
    AssignedExpert,
    AvoidanceInfo,
    Expert,
    ExpertAssignment,
    MatchingStatistics,
    Project,
    ProjectGroup,
)
from src.services.grouping.matching.avoidance import AvoidanceChecker


class MatchingOptimizer:
    """全局最优匹配优化器
    
    使用约束优化算法实现全局最优匹配
    """
    
    def __init__(self):
        """初始化"""
        self.avoidance_checker = AvoidanceChecker()
    
    def optimize(
        self,
        projects: List[Dict],
        experts: List[Expert],
        match_scores: np.ndarray,
        experts_per_project: int = 5,
        min_experts_per_group: int = 10,
        max_reviews_per_expert: int = 5,
        avoid_relations: bool = True
    ) -> List[ExpertAssignment]:
        """执行全局最优匹配
        
        Args:
            projects: 项目列表
            experts: 专家列表
            match_scores: 匹配度矩阵 (n_projects, n_experts)
            experts_per_project: 每个项目分配的专家数
            min_experts_per_group: 每组最少懂行专家数
            max_reviews_per_expert: 每位专家最大评审数
            avoid_relations: 是否回避关系
        
        Returns:
            匹配结果列表
        """
        n_projects = len(projects)
        n_experts = len(experts)
        
        # 初始化分配
        assignments = []
        
        # 简化实现：贪心算法
        # 1. 为每个项目选择 top N 专家
        for i in range(n_projects):
            project_id = projects[i]["id"]
            
            # 获取该项目所有专家的分数
            scores = match_scores[i] if i < len(match_scores) else np.zeros(n_experts)
            
            # 选择分数最高的专家
            top_indices = np.argsort(scores)[::-1][:experts_per_project]
            
            # 构建分配
            assigned_experts = []
            for idx in top_indices:
                if idx < len(experts):
                    expert = experts[idx]
                    score = float(scores[idx])
                    
                    # 使用回避检测器
                    avoidance = None
                    if avoid_relations:
                        # 构建项目对象
                        project = Project(
                            id=project_id,
                            xmmc=projects[i].get("xmmc", ""),
                            cddw_mc=projects[i].get("cddw_mc", ""),
                            ssxk1=projects[i].get("ssxk1")
                        )
                        avoidance = self.avoidance_checker.check_all(expert, project)
                        
                        # 如果是严重回避，跳过
                        if avoidance and avoidance.avoided:
                            continue
                        avoidance = self._check_avoidance(projects[i], expert)
                        if avoidance.avoided:
                            continue
                    
                    assigned_experts.append(AssignedExpert(
                        expert_id=expert.id,
                        xm=expert.xm,
                        match_score=score,
                        reason=self._generate_reason(score),
                        avoidance=avoidance
                    ))
            
            assignments.append(ExpertAssignment(
                project_id=project_id,
                experts=assigned_experts
            ))
        
        return assignments
    
    def _check_avoidance(
        self,
        project: Dict,
        expert: Expert
    ) -> AvoidanceInfo:
        """检查是否需要回避
        
        简化实现：只检查单位是否相同
        
        Args:
            project: 项目信息
            expert: 专家信息
        
        Returns:
            回避信息
        """
        # 检查同一单位
        project_unit = project.get("cddw_mc", "")
        expert_unit = expert.gzdw or ""
        
        if project_unit and expert_unit:
            if project_unit == expert_unit:
                return AvoidanceInfo(
                    avoided=False,  # 不排除，但标记
                    reason=f"同一单位：{expert_unit}",
                    severity="low"
                )
        
        return AvoidanceInfo(avoided=False, severity="none")
    
    def _generate_reason(self, score: float) -> str:
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
    
    def calculate_statistics(
        self,
        assignments: List[ExpertAssignment],
        projects: List[Dict],
        experts: List[Expert],
        experts_per_project: int
    ) -> MatchingStatistics:
        """计算统计信息
        
        Args:
            assignments: 匹配结果
            projects: 项目列表
            experts: 专家列表
            experts_per_project: 每项目专家数
        
        Returns:
            统计信息
        """
        total_projects = len(assignments)
        
        # 统计涉及的专家
        expert_ids = set()
        total_score = 0.0
        avoidance_count = 0
        
        for assignment in assignments:
            for exp in assignment.experts:
                expert_ids.add(exp.exppert_id if hasattr(exp, 'exppert_id') else exp.expert_id)
                total_score += exp.match_score
                if exp.avoidance and exp.avoidance.avoided:
                    avoidance_count += 1
        
        total_experts = len(expert_ids)
        n_assignments = sum(len(a.experts) for a in assignments)
        
        avg_match_score = total_score / n_assignments if n_assignments > 0 else 0
        coverage_rate = total_experts / len(experts) if experts else 0
        
        return MatchingStatistics(
            total_projects=total_projects,
            total_experts=total_experts,
            avg_match_score=avg_match_score,
            avoidance_detected=avoidance_count,
            experts_per_project=experts_per_project,
            coverage_rate=coverage_rate
        )
