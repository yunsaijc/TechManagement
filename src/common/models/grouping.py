"""
智能分组与专家匹配 - 数据模型

定义分组服务使用的数据模型
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class GroupingStrategy(str, Enum):
    """分组策略"""
    SEMANTIC = "semantic"   # 语义优先策略
    BALANCED = "balanced"   # 兼容旧策略（内部也按语义处理）
    QUALITY = "quality"     # 兼容旧策略（内部也按语义处理）


# ========== 项目模型 ==========


class Project(BaseModel):
    """项目基础信息
    
    对应数据库: Sb_Jbxx
    """
    id: str = Field(..., description="项目ID")
    xmmc: str = Field(..., description="项目名称")
    gjc: Optional[str] = Field(None, description="关键词")
    ssxk1: Optional[str] = Field(None, description="学科代码1")
    ssxk2: Optional[str] = Field(None, description="学科代码2")
    xmjj: Optional[str] = Field(None, description="项目简介 (来自 Sb_Jj.xmjj)")
    lxbj: Optional[str] = Field(None, description="类型编辑 (来自 Sb_Jj.lxbj)")
    cddw_mc: Optional[str] = Field(None, description="承担单位名称")
    year: Optional[str] = Field(None, description="年度")

    class Config:
        from_attributes = True


class ProjectAnalysis(BaseModel):
    """项目内容分析结果
    
    使用 LLM 提取项目的核心创新点、技术方向、研究领域
    """
    project_id: str = Field(..., description="项目ID")
    
    # LLM 分析结果
    innovation: Optional[str] = Field(None, description="核心创新点")
    tech_direction: Optional[str] = Field(None, description="技术方向")
    research_field: Optional[str] = Field(None, description="研究领域")
    application: Optional[str] = Field(None, description="应用场景")
    
    # 融合文本（用于向量化）
    text: Optional[str] = Field(None, description="融合后的文本")

    class Config:
        from_attributes = True


# ========== 专家模型 ==========


class Expert(BaseModel):
    """专家基础信息
    
    对应数据库: ZJK_ZJXX
    """
    id: str = Field(..., description="专家ID (对应 ZJK_ZJXX.ZJNO)")
    xm: str = Field(..., description="姓名")
    sxxk1: Optional[str] = Field(None, description="熟悉学科1")
    sxxk2: Optional[str] = Field(None, description="熟悉学科2")
    sxxk3: Optional[str] = Field(None, description="熟悉学科3")
    sxxk4: Optional[str] = Field(None, description="熟悉学科4")
    sxxk5: Optional[str] = Field(None, description="熟悉学科5")
    sxzy: Optional[str] = Field(None, description="擅长专业")
    yjly: Optional[str] = Field(None, description="研究领域 (8000字符)")
    lwlz: Optional[str] = Field(None, description="论文论著 (5000字符)")
    gzdw: Optional[str] = Field(None, description="工作单位")

    class Config:
        from_attributes = True


class ExpertProfile(BaseModel):
    """专家画像
    
    使用 LLM 从研究领域、论文、擅长专业构建专家画像
    """
    expert_id: str = Field(..., description="专家ID")
    
    # LLM 分析结果
    main_research_area: Optional[str] = Field(None, description="主要研究方向")
    sub_research_fields: List[str] = Field(default_factory=list, description="细分领域")
    tech_expertise: List[str] = Field(default_factory=list, description="技术专长")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    
    # 融合文本（用于向量化）
    text: Optional[str] = Field(None, description="融合后的文本")

    class Config:
        from_attributes = True


# ========== 分组结果模型 ==========


class ProjectInGroup(BaseModel):
    """分组内的项目"""
    project_id: str = Field(..., description="项目ID")
    xmmc: str = Field(..., description="项目名称")
    xmjj: Optional[str] = Field(None, description="项目简介")
    subject_code: Optional[str] = Field(None, description="项目学科代码")
    subject_name: Optional[str] = Field(None, description="项目学科名称")
    semantic_score: float = Field(..., description="语义匹配得分")
    quality_score: Optional[float] = Field(None, description="兼容字段：语义得分")
    reason: Optional[str] = Field(None, description="分配理由")

    class Config:
        from_attributes = True


class GroupSummary(BaseModel):
    """分组摘要信息"""
    count: int = Field(..., description="项目数量")
    avg_score: float = Field(..., description="平均语义得分")
    main_themes: List[str] = Field(default_factory=list, description="主要主题")

    class Config:
        from_attributes = True


class ProjectGroup(BaseModel):
    """项目分组"""
    group_id: int = Field(..., description="分组ID")
    subject_code: Optional[str] = Field(None, description="组编码")
    subject_name: Optional[str] = Field(None, description="组主题")
    projects: List[ProjectInGroup] = Field(default_factory=list, description="分组内项目列表")
    
    # 统计信息
    count: int = Field(0, description="项目数量")
    avg_quality: float = Field(0.0, description="平均语义得分")
    max_quality: float = Field(0.0, description="最高语义得分")
    min_quality: float = Field(0.0, description="最低语义得分")
    
    # 兼容旧版
    summary: Optional[GroupSummary] = Field(None, description="分组摘要(兼容)")

    class Config:
        from_attributes = True


class GroupingStatistics(BaseModel):
    """分组统计信息"""
    total_projects: int = Field(..., description="项目总数")
    group_count: int = Field(..., description="分组数量")
    balance_score: float = Field(..., description="均衡度得分 (0-1)")
    avg_projects_per_group: float = Field(..., description="平均每组项目数")
    avg_quality_per_group: float = Field(..., description="平均语义得分")
    
    # 新增：语义评分详情
    quality_mean: Optional[float] = Field(None, description="语义得分均值")
    quality_median: Optional[float] = Field(None, description="语义得分中位数")
    quality_std: Optional[float] = Field(None, description="语义得分标准差")
    quality_min: Optional[float] = Field(None, description="语义得分最小值")
    quality_max: Optional[float] = Field(None, description="语义得分最大值")
    
    # 新增：分组质量
    quantity_balance: Optional[float] = Field(None, description="数量均衡度 (0-1)")
    quality_balance: Optional[float] = Field(None, description="语义均衡度 (0-1)")
    subject_purity: Optional[float] = Field(None, description="主题聚合度 (0-1)")
    split_correctness: Optional[float] = Field(None, description="拆分正确率 (0-1)")

    # 新增：可靠性验证提醒
    audit_reminder: Optional[str] = Field(None, description="人工复审提醒")

    class Config:
        from_attributes = True


class GroupingResult(BaseModel):
    """分组结果"""
    id: str = Field(..., description="结果ID")
    year: str = Field(..., description="年度")
    groups: List[ProjectGroup] = Field(default_factory=list, description="分组列表")
    statistics: GroupingStatistics = Field(..., description="统计信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        from_attributes = True


# ========== 匹配结果模型 ==========


class AvoidanceInfo(BaseModel):
    """回避信息"""
    avoided: bool = Field(..., description="是否回避")
    reason: Optional[str] = Field(None, description="回避原因")
    severity: str = Field("none", description="严重程度: low/medium/high")

    class Config:
        from_attributes = True


class AssignedExpert(BaseModel):
    """已分配的专家"""
    expert_id: str = Field(..., description="专家ID")
    xm: str = Field(..., description="姓名")
    match_score: float = Field(..., description="匹配度")
    reason: Optional[str] = Field(None, description="匹配原因")
    avoidance: Optional[AvoidanceInfo] = Field(None, description="回避信息")

    class Config:
        from_attributes = True


class ExpertAssignment(BaseModel):
    """专家分配"""
    project_id: str = Field(..., description="项目ID")
    experts: List[AssignedExpert] = Field(default_factory=list, description="分配的专家列表")

    class Config:
        from_attributes = True


class MatchingStatistics(BaseModel):
    """匹配统计信息"""
    total_projects: int = Field(..., description="项目总数")
    total_experts: int = Field(..., description="涉及专家总数")
    avg_match_score: float = Field(..., description="平均匹配度")
    avoidance_detected: int = Field(..., description="检测到的回避关系数")
    experts_per_project: int = Field(..., description="每项目专家数")
    coverage_rate: float = Field(..., description="专家覆盖率")

    class Config:
        from_attributes = True


class MatchingResult(BaseModel):
    """匹配结果"""
    id: str = Field(..., description="结果ID")
    group_id: int = Field(..., description="分组ID")
    matches: List[ExpertAssignment] = Field(default_factory=list, description="匹配列表")
    statistics: MatchingStatistics = Field(..., description="统计信息")
    warnings: List[str] = Field(default_factory=list, description="警告信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        from_attributes = True


# ========== 完整结果模型 ==========


class FullStatistics(BaseModel):
    """完整统计信息"""
    total_projects: int = Field(..., description="项目总数")
    total_groups: int = Field(..., description="分组数")
    total_experts: int = Field(..., description="涉及专家总数")
    avg_match_score: float = Field(..., description="平均匹配度")
    balance_score: float = Field(..., description="分组均衡度")

    class Config:
        from_attributes = True


class FullGroupingResult(BaseModel):
    """完整分组与匹配结果"""
    id: str = Field(..., description="结果ID")
    year: str = Field(..., description="年度")
    category: Optional[str] = Field(None, description="类别")
    groups: List[ProjectGroup] = Field(default_factory=list, description="分组列表")
    matches: Dict[int, MatchingResult] = Field(default_factory=dict, description="匹配结果 (group_id -> 匹配结果)")
    statistics: FullStatistics = Field(..., description="总体统计")
    report: str = Field(..., description="可读报告")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        from_attributes = True


# ========== 请求模型 ==========


class GroupingRequest(BaseModel):
    """分组请求"""
    year: str = Field(..., description="年度 (必填)")
    category: Optional[str] = Field(None, description="奖种类别")
    max_per_group: int = Field(15, description="每组目标项目数")
    strategy: GroupingStrategy = Field(GroupingStrategy.SEMANTIC, description="分组策略")
    limit: Optional[int] = Field(None, description="限制项目数量（测试用）")

    class Config:
        from_attributes = True


class MatchingRequest(BaseModel):
    """匹配请求"""
    group_id: int = Field(..., description="分组ID (必填)")
    experts_per_project: int = Field(5, description="每个项目分配专家数")
    min_experts_per_group: int = Field(10, description="每组最少懂行专家")
    avoid_relations: bool = Field(True, description="是否回避关系")
    max_reviews_per_expert: int = Field(5, description="每位专家最大评审数")

    class Config:
        from_attributes = True


class FullGroupingRequest(BaseModel):
    """完整分组与匹配请求"""
    year: str = Field(..., description="年度 (必填)")
    category: Optional[str] = Field(None, description="奖种类别")
    max_per_group: int = Field(15, description="每组目标项目数")
    experts_per_project: int = Field(5, description="每个项目分配专家数")
    min_experts_per_group: int = Field(10, description="每组最少懂行专家")
    avoid_relations: bool = Field(True, description="是否回避关系")
    max_reviews_per_expert: int = Field(5, description="每位专家最大评审数")

    class Config:
        from_attributes = True
