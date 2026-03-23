"""
智能分组与专家匹配服务

服务入口，提供分组和匹配功能
"""
from typing import Any, Optional

from src.common.llm import get_default_llm_client
from src.common.models.grouping import (
    FullGroupingRequest,
    FullGroupingResult,
    FullStatistics,
    GroupingRequest,
    GroupingResult,
    GroupingStrategy,
    MatchingRequest,
    MatchingResult,
)
from src.services.grouping.grouping.agent import GroupingAgent
from src.services.grouping.matching.agent import MatchingAgent


class GroupingService:
    """智能分组与专家匹配服务
    
    提供分组和专家匹配功能
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
        self.embedder = embedder
        
        # 初始化子服务
        self.grouping_agent = GroupingAgent(llm, embedder)
        self.matching_agent = MatchingAgent(llm, embedder)
    
    async def group_projects(
        self,
        request: GroupingRequest
    ) -> GroupingResult:
        """项目分组
        
        Args:
            request: 分组请求
        
        Returns:
            分组结果
        """
        return await self.grouping_agent.group_projects(request)
    
    async def match_experts(
        self,
        group: Any,
        group_id: int,
        request: MatchingRequest
    ) -> MatchingResult:
        """专家匹配
        
        Args:
            group: 分组结果
            group_id: 分组ID
            request: 匹配请求
        
        Returns:
            匹配结果
        """
        return await self.matching_agent.match_experts(group, group_id, request)
    
    async def full_grouping(
        self,
        request: FullGroupingRequest
    ) -> FullGroupingResult:
        """完整分组与匹配
        
        Args:
            request: 完整请求
        
        Returns:
            完整结果
        """
        # 1. 分组
        grouping_request = GroupingRequest(
            category=request.category,
            max_per_group=request.max_per_group,
            strategy=GroupingStrategy.SEMANTIC
        )
        grouping_result = await self.group_projects(grouping_request)
        
        # 2. 匹配
        matches = {}
        warnings = []
        
        for group in grouping_result.groups:
            matching_request = MatchingRequest(
                group_id=group.group_id,
                experts_per_project=request.experts_per_project,
                min_experts_per_group=request.min_experts_per_group,
                avoid_relations=request.avoid_relations,
                max_reviews_per_expert=request.max_reviews_per_expert
            )
            
            match_result = await self.match_experts(
                group, group.group_id, matching_request
            )
            
            matches[group.group_id] = match_result
            warnings.extend(match_result.warnings)
        
        # 3. 统计信息
        total_projects = grouping_result.statistics.total_projects
        total_groups = grouping_result.statistics.group_count
        
        # 统计涉及专家数
        total_experts = set()
        avg_match_score = 0.0
        match_count = 0
        
        for match_result in matches.values():
            for assignment in match_result.matches:
                for exp in assignment.experts:
                    total_experts.add(exp.expert_id)
                    avg_match_score += exp.match_score
                    match_count += 1
        
        if match_count > 0:
            avg_match_score /= match_count
        
        statistics = FullStatistics(
            total_projects=total_projects,
            total_groups=total_groups,
            total_experts=len(total_experts),
            avg_match_score=avg_match_score,
            balance_score=grouping_result.statistics.balance_score
        )
        
        # 4. 生成报告
        report = self._generate_report(
            total_projects, total_groups, len(total_experts),
            avg_match_score, grouping_result.statistics.balance_score,
            len(warnings)
        )
        
        # 5. 构建结果
        result = FullGroupingResult(
            id=f"full_{grouping_result.id}",
            year="fixed",
            category=request.category,
            groups=grouping_result.groups,
            matches=matches,
            statistics=statistics,
            report=report
        )
        
        return result
    
    def _generate_report(
        self,
        total_projects: int,
        total_groups: int,
        total_experts: int,
        avg_match_score: float,
        balance_score: float,
        warning_count: int
    ) -> str:
        """生成报告
        
        Args:
            total_projects: 项目总数
            total_groups: 分组数
            total_experts: 专家总数
            avg_match_score: 平均匹配度
            balance_score: 均衡度
            warning_count: 警告数量
        
        Returns:
            报告文本
        """
        parts = [
            f"分组与匹配完成。",
            f"共{total_projects}个项目分成{total_groups}组，",
            f"每组平均{total_projects // total_groups}个项目。"
        ]
        
        if total_experts > 0:
            parts.append(f"共涉及{total_experts}位专家。")
        
        if avg_match_score > 0:
            parts.append(f"平均匹配度{avg_match_score:.1f}分。")
        
        if warning_count > 0:
            parts.append(f"检测到{warning_count}对需要回避的专家-项目关系，已自动处理。")
        
        return "".join(parts)


# 全局服务实例
_service: Optional[GroupingService] = None


def get_grouping_service() -> GroupingService:
    """获取分组服务实例
    
    Returns:
        分组服务实例
    """
    global _service
    if _service is None:
        _service = GroupingService()
    return _service
