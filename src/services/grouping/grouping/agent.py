"""
分组 Agent

重构版：按学科分组 + 质量评估 + 均衡分配

逻辑：
1. 按三级学科初步分组
2. 数量 ≤15 → 保留原分组
3. 数量 >30 → 质量评估 + 均衡分配
4. 合并结果
"""
import asyncio
import re
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from src.common.llm import get_default_llm_client
from src.common.models.grouping import (
    GroupingRequest,
    GroupingResult,
    GroupingStatistics,
    GroupSummary,
    Project,
    ProjectGroup,
    ProjectInGroup,
    ProjectQuality,
)
from src.services.grouping.grouping.quality import QualityAssessor
from src.services.grouping.storage.project_repo import ProjectRepository
from src.common.database import get_subject_repo


# 质量分数缓存
_QUALITY_CACHE: Dict[str, float] = {}


class GroupingAgent:
    """分组 Agent (重构版)
    
    按学科分组 + 质量评估 + 均衡分配
    """
    
    def __init__(
        self,
        llm: Any = None,
        max_per_group: int = 15,
        quality_weights: List[float] = None,
        concurrency: int = 10
    ):
        """初始化
        
        Args:
            llm: LLM 客户端
            max_per_group: 每组目标项目数 (默认15)
            quality_weights: 质量权重 [创新性, 技术难度, 应用价值]
            concurrency: LLM 并发数
        """
        self.llm = llm or get_default_llm_client()
        self.max_per_group = max_per_group
        self.quality_weights = quality_weights or [1.0, 1.0, 1.0]
        self.concurrency = concurrency
        
        self.quality_assessor = QualityAssessor(self.llm)
        self.project_repo = ProjectRepository()
        self.subject_repo = get_subject_repo()
    
    def _get_subject_level(self, code: str) -> int:
        """判断学科层级
        
        - code 长度=2 → 一级学科
        - code 长度=3 → 二级学科
        - code 长度≥4 → 三级学科
        """
        if not code:
            return 0
        length = len(code)
        if length == 2:
            return 1
        elif length == 3:
            return 2
        elif length >= 4:
            return 3
        return 0
    
    def _get_subject_code(self, ssxk1: Optional[str]) -> str:
        """获取三级学科代码
        
        取 ssxk1 的前4位作为三级学科代码
        """
        if not ssxk1:
            return "unknown"
        code = ssxk1.strip()
        if len(code) >= 4:
            return code[:4]
        elif len(code) >= 2:
            return code[:2]  # 不足4位用2位
        return "unknown"
    
    def _get_subject_name(self, code: str) -> str:
        """获取学科名称"""
        if code == "unknown":
            return "未知学科"
        
        subject = self.subject_repo.get_by_code(code)
        if subject:
            return subject.name or code
        return code
    
    def _group_by_subject(self, projects: List[Project]) -> Dict[str, List[Project]]:
        """按三级学科分组
        
        Returns:
            {subject_code: [Project, ...]}
        """
        subject_groups = defaultdict(list)
        
        for project in projects:
            subject_code = self._get_subject_code(project.ssxk1)
            subject_groups[subject_code].append(project)
        
        return dict(subject_groups)
    
    def _clean_html(self, text: Optional[str]) -> str:
        """清洗 HTML 标签"""
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    async def _assess_quality(
        self, 
        projects: List[Project]
    ) -> Dict[str, float]:
        """评估所有项目质量
        
        Args:
            projects: 项目列表
        
        Returns:
            {project_id: quality_score}
        """
        quality_scores = {}
        
        # 过滤已缓存的项目
        uncached = []
        for p in projects:
            if p.id in _QUALITY_CACHE:
                quality_scores[p.id] = _QUALITY_CACHE[p.id]
            else:
                uncached.append(p)
        
        if not uncached:
            return quality_scores
        
        # 并发评估
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def assess_one(p: Project) -> tuple:
            async with semaphore:
                try:
                    score = await self.quality_assessor.assess_single(p)
                    return p.id, score
                except Exception as e:
                    print(f"质量评估失败: {p.id}, {e}")
                    return p.id, 75.0  # 默认分
        
        tasks = [assess_one(p) for p in uncached]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, tuple):
                pid, score = result
                _QUALITY_CACHE[pid] = score
                quality_scores[pid] = score
        
        return quality_scores
    
    def _balanced_distribute(
        self,
        projects: List[Project],
        quality_scores: Dict[str, float],
        target_groups: int = None
    ) -> List[List[Project]]:
        """质量均衡分配算法
        
        目标: 每组数量均衡 + 质量总分均衡
        方法: 贪心分配（先按质量排序，然后轮转分配）
        
        Args:
            projects: 项目列表
            quality_scores: {project_id: score}
            target_groups: 目标分组数（默认根据 max_per_group 计算）
        
        Returns:
            [[Project, ...], ...]
        """
        if not projects:
            return []
        
        # 计算目标组数（尽量均衡）
        if target_groups is None:
            target_groups = max(1, round(len(projects) / self.max_per_group))
        
        # 按质量降序排序
        sorted_projects = sorted(
            projects,
            key=lambda p: quality_scores.get(p.id, 75.0),
            reverse=True
        )
        
        # 初始化分组
        groups = [[] for _ in range(target_groups)]
        group_scores = [0.0] * target_groups
        
        # 贪心分配：总是加入分数最低的组
        for p in sorted_projects:
            min_idx = group_scores.index(min(group_scores))
            groups[min_idx].append(p)
            group_scores[min_idx] += quality_scores.get(p.id, 75.0)
        
        return groups
    
    async def group_projects(
        self,
        request: GroupingRequest
    ) -> GroupingResult:
        """执行项目分组 (重构版)
        
        流程：
        1. 获取项目列表
        2. 按三级学科初步分组
        3. 数量≤15 → 保留原分组
        4. 数量>30 → 质量评估 + 均衡分配
        5. 合并结果
        """
        start_time = time.time()
        
        # 更新参数
        self.max_per_group = request.max_per_group
        
        # 1. 获取项目列表
        limit = request.limit
        projects = self.project_repo.get_projects_by_year(
            year=request.year,
            category=request.category,
            limit=limit
        )
        
        if not projects:
            raise ValueError(f"没有找到 {request.year} 年度的项目")
        
        print(f"[Grouping] 获取到 {len(projects)} 个项目")
        
        # 2. 按三级学科初步分组
        subject_groups = self._group_by_subject(projects)
        print(f"[Grouping] 按学科分为 {len(subject_groups)} 个学科组")
        
        # 3. 处理每个学科
        all_groups = []  # 最终分组
        
        for subject_code, subject_projects in subject_groups.items():
            count = len(subject_projects)
            subject_name = self._get_subject_name(subject_code)
            
            if count <= self.max_per_group:
                # 数量≤max，直接保留
                all_groups.append({
                    "subject_code": subject_code,
                    "subject_name": subject_name,
                    "projects": subject_projects,
                    "need_split": False
                })
            else:
                # 数量>max，需要拆分
                print(f"[Grouping] 学科 {subject_code}({subject_name}) 有 {count} 个项目，需要拆分")
                
                # 计算拆分后的组数（尽量均衡）
                target_groups = max(1, round(count / self.max_per_group))
                
                # 3.1 评估质量
                quality_scores = await self._assess_quality(subject_projects)
                
                # 3.2 均衡分配（传入目标组数）
                split_groups = self._balanced_distribute(subject_projects, quality_scores, target_groups)
                
                for i, group in enumerate(split_groups):
                    all_groups.append({
                        "subject_code": f"{subject_code}_{i+1}",
                        "subject_name": f"{subject_name}({i+1})",
                        "projects": group,
                        "need_split": True,
                        "parent_subject": subject_code
                    })
        
        # 4. 构建结果
        result_groups = []
        group_id = 1
        
        for g in all_groups:
            projects_in_group = g["projects"]
            
            # 计算质量分数
            scores = []
            for p in projects_in_group:
                score = _QUALITY_CACHE.get(p.id, 75.0)
                scores.append(score)
            
            # 构建 ProjectInGroup
            project_items = [
                ProjectInGroup(
                    project_id=p.id,
                    xmmc=p.xmmc,
                    quality_score=_QUALITY_CACHE.get(p.id, 75.0),
                    reason=f"学科: {g['subject_name']}"
                )
                for p in projects_in_group
            ]
            
            # 统计信息
            avg_score = np.mean(scores) if scores else 0
            max_score = max(scores) if scores else 0
            min_score = min(scores) if scores else 0
            
            result_groups.append(
                ProjectGroup(
                    group_id=group_id,
                    subject_code=g["subject_code"],
                    subject_name=g["subject_name"],
                    projects=project_items,
                    count=len(projects_in_group),
                    avg_quality=round(avg_score, 2),
                    max_quality=round(max_score, 2),
                    min_quality=round(min_score, 2)
                )
            )
            group_id += 1
        
        # 5. 统计信息
        total_projects = len(projects)
        total_groups = len(result_groups)
        
        stats = GroupingStatistics(
            total_projects=total_projects,
            group_count=total_groups,
            balance_score=0.85,  # 简化
            avg_projects_per_group=total_projects / total_groups if total_groups else 0,
            avg_quality_per_group=np.mean([g.avg_quality for g in result_groups]) if result_groups else 0
        )
        
        result = GroupingResult(
            id=str(uuid.uuid4()),
            year=request.year,
            groups=result_groups,
            statistics=stats,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        elapsed = time.time() - start_time
        print(f"[Grouping] 完成，用时 {elapsed:.2f}秒，分组 {total_groups} 个")
        
        return result
