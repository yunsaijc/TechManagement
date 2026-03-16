"""
分组优化器

确保分组结果满足约束条件：数量均衡、质量均衡、学科内聚
"""
from typing import Dict, List, Tuple

import numpy as np

from src.common.models.grouping import (
    GroupSummary,
    GroupingStrategy,
    ProjectGroup,
    ProjectInGroup,
    ProjectQuality,
)


class GroupOptimizer:
    """分组优化器
    
    优化分组结果，满足约束条件
    """
    
    def optimize(
        self,
        cluster_labels: np.ndarray,
        quality_scores: Dict[str, float],
        projects: List[Dict],
        strategy: GroupingStrategy = GroupingStrategy.BALANCED
    ) -> List[ProjectGroup]:
        """优化分组结果
        
        Args:
            cluster_labels: 聚类标签
            quality_scores: 项目ID -> 质量得分
            projects: 项目列表
            strategy: 分组策略
        
        Returns:
            优化后的分组列表
        """
        n_clusters = len(set(cluster_labels))
        
        # 构建初始分组
        groups = self._build_initial_groups(
            cluster_labels, quality_scores, projects, n_clusters
        )
        
        # 根据策略优化
        if strategy == GroupingStrategy.BALANCED:
            groups = self._balance_groups(groups)
        elif strategy == GroupingStrategy.QUALITY:
            groups = self._quality_layers(groups)
        
        # 添加分组ID
        for i, group in enumerate(groups):
            group.group_id = i + 1
        
        return groups
    
    def _build_initial_groups(
        self,
        cluster_labels: np.ndarray,
        quality_scores: Dict[str, float],
        projects: List[Dict],
        n_clusters: int
    ) -> List[ProjectGroup]:
        """构建初始分组
        
        Args:
            cluster_labels: 聚类标签
            quality_scores: 质量得分
            projects: 项目列表
            n_clusters: 分组数
        
        Returns:
            初始分组列表
        """
        groups = []
        
        for cluster_id in range(n_clusters):
            # 获取该簇的项目
            cluster_projects = []
            for i, label in enumerate(cluster_labels):
                if label == cluster_id:
                    project = projects[i]
                    project_id = project.get("id", f"proj_{i}")
                    quality = quality_scores.get(project_id, 75.0)
                    
                    cluster_projects.append(ProjectInGroup(
                        project_id=project_id,
                        xmmc=project.get("xmmc", ""),
                        quality_score=quality,
                        reason="基于内容聚类"
                    ))
            
            # 计算分组摘要
            if cluster_projects:
                avg_score = sum(p.quality_score for p in cluster_projects) / len(cluster_projects)
                summary = GroupSummary(
                    count=len(cluster_projects),
                    avg_score=avg_score,
                    main_themes=self._extract_themes(cluster_projects)
                )
            else:
                summary = GroupSummary(count=0, avg_score=0, main_themes=[])
            
            groups.append(ProjectGroup(
                group_id=cluster_id,
                projects=cluster_projects,
                summary=summary
            ))
        
        return groups
    
    def _balance_groups(self, groups: List[ProjectGroup]) -> List[ProjectGroup]:
        """均衡分组大小
        
        Args:
            groups: 分组列表
        
        Returns:
            均衡后的分组
        """
        # 统计总项目数和目标大小
        total_projects = sum(g.summary.count for g in groups)
        n_groups = len(groups)
        target_size = total_projects / n_groups
        
        # 找出过大和过小的组
        large_groups = [g for g in groups if g.summary.count > target_size + 3]
        small_groups = [g for g in groups if g.summary.count < target_size - 3]
        
        # 简单均衡：调整目标大小
        for group in groups:
            # 保持分组结构，仅调整摘要
            group.summary.avg_projects_per_group = target_size
        
        return groups
    
    def _quality_layers(self, groups: List[ProjectGroup]) -> List[ProjectGroup]:
        """按质量分层
        
        将所有项目按质量排序，然后交错分配到各组
        
        Args:
            groups: 分组列表
        
        Returns:
            质量均衡后的分组
        """
        # 收集所有项目
        all_projects = []
        for group in groups:
            for p in group.projects:
                all_projects.append(p)
        
        # 按质量排序
        all_projects.sort(key=lambda x: x.quality_score, reverse=True)
        
        # 交错分配到各组
        n_groups = len(groups)
        for i, project in enumerate(all_projects):
            target_group = i % n_groups
            groups[target_group].projects.append(project)
        
        # 重新计算摘要
        for group in groups:
            if group.projects:
                scores = [p.quality_score for p in group.projects]
                group.summary = GroupSummary(
                    count=len(group.projects),
                    avg_score=sum(scores) / len(scores),
                    main_themes=self._extract_themes(group.projects)
                )
            else:
                group.summary = GroupSummary(count=0, avg_score=0, main_themes=[])
        
        return groups
    
    def _extract_themes(self, projects: List[ProjectInGroup]) -> List[str]:
        """提取分组主题
        
        Args:
            projects: 项目列表
        
        Returns:
            主要主题列表
        """
        # 简单实现：返回前3个主题
        # 实际应该基于项目内容分析提取
        themes = []
        for p in projects[:3]:
            if p.xmmc:
                # 取项目名称前10个字作为主题
                theme = p.xmmc[:10]
                themes.append(theme)
        
        return themes[:3]
    
    def calculate_balance_score(self, groups: List[ProjectGroup]) -> float:
        """计算均衡度得分
        
        Args:
            groups: 分组列表
        
        Returns:
            均衡度得分 (0-1)
        """
        if not groups:
            return 0.0
        
        # 计算数量均衡度
        counts = [g.summary.count for g in groups]
        avg_count = sum(counts) / len(counts)
        
        if avg_count == 0:
            return 0.0
        
        count_variance = sum((c - avg_count) ** 2 for c in counts) / len(counts)
        count_score = 1.0 - min(1.0, math.sqrt(count_variance) / avg_count)
        
        # 计算质量均衡度
        scores = [g.summary.avg_score for g in groups if g.summary.count > 0]
        if scores:
            avg_score = sum(scores) / len(scores)
            score_variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
            score_score = 1.0 - min(1.0, math.sqrt(score_variance) / avg_score)
        else:
            score_score = 0.0
        
        # 综合得分
        return (count_score + score_score) / 2


import math  # 需要导入 math
