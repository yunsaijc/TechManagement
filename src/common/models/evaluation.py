"""
正文评审服务 - 数据模型

定义评审服务使用的数据模型，包括评审维度、评分、结果等。
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============ 评审维度枚举 ============

class EvaluationDimension(str, Enum):
    """评审维度（9个）
    
    分为三大类：
    - 核心维度：技术可行性、创新性、团队能力
    - 成果维度：预期成果、社会效益、经济效益
    - 管理维度：风险控制、进度合理性、合规性
    """
    # 核心维度
    FEASIBILITY = "feasibility"              # 技术可行性
    INNOVATION = "innovation"                # 创新性
    TEAM = "team"                            # 团队能力
    
    # 成果维度
    OUTCOME = "outcome"                      # 预期成果
    SOCIAL_BENEFIT = "social_benefit"        # 社会效益
    ECONOMIC_BENEFIT = "economic_benefit"    # 经济效益
    
    # 管理维度
    RISK_CONTROL = "risk_control"            # 风险控制
    SCHEDULE = "schedule"                    # 进度合理性
    COMPLIANCE = "compliance"                # 合规性


# ============ 默认权重 ============

DEFAULT_WEIGHTS: Dict[str, float] = {
    EvaluationDimension.FEASIBILITY.value: 0.15,
    EvaluationDimension.INNOVATION.value: 0.15,
    EvaluationDimension.TEAM.value: 0.10,
    EvaluationDimension.OUTCOME.value: 0.12,
    EvaluationDimension.SOCIAL_BENEFIT.value: 0.10,
    EvaluationDimension.ECONOMIC_BENEFIT.value: 0.10,
    EvaluationDimension.RISK_CONTROL.value: 0.08,
    EvaluationDimension.SCHEDULE.value: 0.10,
    EvaluationDimension.COMPLIANCE.value: 0.10,
}

# 等级判定阈值
GRADE_THRESHOLDS = {
    "A": 9.0,   # 优秀：≥9.0
    "B": 8.0,   # 良好：≥8.0
    "C": 6.0,   # 中等：≥6.0
    "D": 4.0,   # 较差：≥4.0
    "E": 0.0,   # 不合格：<4.0
}

# 维度中文名称映射
DIMENSION_NAMES = {
    EvaluationDimension.FEASIBILITY.value: "技术可行性",
    EvaluationDimension.INNOVATION.value: "创新性",
    EvaluationDimension.TEAM.value: "团队能力",
    EvaluationDimension.OUTCOME.value: "预期成果",
    EvaluationDimension.SOCIAL_BENEFIT.value: "社会效益",
    EvaluationDimension.ECONOMIC_BENEFIT.value: "经济效益",
    EvaluationDimension.RISK_CONTROL.value: "风险控制",
    EvaluationDimension.SCHEDULE.value: "进度合理性",
    EvaluationDimension.COMPLIANCE.value: "合规性",
}

# 维度分类
DIMENSION_CATEGORIES = {
    "核心维度": [EvaluationDimension.FEASIBILITY, EvaluationDimension.INNOVATION, EvaluationDimension.TEAM],
    "成果维度": [EvaluationDimension.OUTCOME, EvaluationDimension.SOCIAL_BENEFIT, EvaluationDimension.ECONOMIC_BENEFIT],
    "管理维度": [EvaluationDimension.RISK_CONTROL, EvaluationDimension.SCHEDULE, EvaluationDimension.COMPLIANCE],
}


# ============ 检查项模型 ============

class CheckItem(BaseModel):
    """检查项结果
    
    每个维度包含多个检查项，每个检查项有独立的评分和评价。
    """
    name: str = Field(..., description="检查项名称")
    score: float = Field(..., ge=1, le=10, description="得分 (1-10)")
    weight: float = Field(default=1.0, ge=0, le=1, description="权重")
    comment: str = Field(default="", description="评价")


# ============ 维度评分模型 ============

class DimensionScore(BaseModel):
    """单维度评分（十分制）
    
    包含维度的评分、权重、评审意见、问题列表和亮点列表。
    """
    dimension: str = Field(..., description="维度代码")
    dimension_name: str = Field(default="", description="维度名称")
    score: float = Field(..., ge=1, le=10, description="得分 (1-10)")
    weight: float = Field(..., ge=0, le=1, description="权重")
    weighted_score: float = Field(..., description="加权得分")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    opinion: str = Field(..., description="评审意见")
    issues: List[str] = Field(default_factory=list, description="问题列表")
    highlights: List[str] = Field(default_factory=list, description="亮点列表")
    items: List[CheckItem] = Field(default_factory=list, description="检查项详情")
    
    def model_post_init(self, __context: Any) -> None:
        """初始化后自动填充维度名称"""
        if not self.dimension_name and self.dimension in DIMENSION_NAMES:
            self.dimension_name = DIMENSION_NAMES[self.dimension]


# ============ 评审请求模型 ============

class EvaluationRequest(BaseModel):
    """评审请求
    
    包含项目ID、可选的评审维度列表、自定义权重等。
    """
    project_id: str = Field(..., description="项目ID")
    
    # 可选：指定评审维度（默认全部）
    dimensions: Optional[List[str]] = Field(
        default=None, 
        description="评审维度列表，默认全部9个维度"
    )
    
    # 可选：自定义权重（默认使用 DEFAULT_WEIGHTS）
    weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="自定义权重，未指定的维度使用默认权重"
    )
    
    # 可选：指定评审章节
    include_sections: List[str] = Field(
        default_factory=list,
        description="指定解析的章节，默认全部"
    )

    # 融合能力开关
    enable_highlight: bool = Field(default=False, description="是否启用划重点")
    enable_industry_fit: bool = Field(default=False, description="是否启用产业指南贴合评估")
    enable_benchmark: bool = Field(default=False, description="是否启用技术摸底")
    enable_chat_index: bool = Field(default=False, description="是否构建聊天索引")
    
    # 附加选项
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="附加选项"
    )
    
    def get_dimensions(self) -> List[str]:
        """获取要评审的维度列表"""
        if self.dimensions:
            return self.dimensions
        return [dim.value for dim in EvaluationDimension]


class BatchEvaluationRequest(BaseModel):
    """批量评审请求"""
    project_ids: List[str] = Field(..., max_length=50, description="项目ID列表，最多50个")
    weights: Optional[Dict[str, float]] = Field(default=None, description="统一权重")
    concurrency: int = Field(default=3, ge=1, le=10, description="并发数")


class GuideEvaluationRequest(BaseModel):
    """按指南代码批量评审请求"""
    zndm: str = Field(..., min_length=1, description="指南代码")
    limit: Optional[int] = Field(default=None, ge=1, le=100, description="最多评审项目数，不传则全量")
    dimensions: Optional[List[str]] = Field(default=None, description="评审维度列表，默认全部9个维度")
    weights: Optional[Dict[str, float]] = Field(default=None, description="自定义权重")
    include_sections: List[str] = Field(default_factory=list, description="指定解析的章节，默认全部")
    enable_highlight: bool = Field(default=False, description="是否启用划重点")
    enable_industry_fit: bool = Field(default=False, description="是否启用产业指南贴合评估")
    enable_benchmark: bool = Field(default=False, description="是否启用技术摸底")
    enable_chat_index: bool = Field(default=False, description="是否构建聊天索引")
    concurrency: int = Field(default=3, ge=1, le=10, description="并发数")


class GuideEvaluationResult(BaseModel):
    """按指南代码批量评审结果"""
    zndm: str = Field(..., description="指南代码")
    guide_name: Optional[str] = Field(default=None, description="指南名称")
    total: int = Field(..., description="总数")
    success: int = Field(..., description="成功数")
    failed: int = Field(..., description="失败数")
    results: List["EvaluationResult"] = Field(default_factory=list, description="评审结果列表")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="错误列表")


# ============ 融合输出模型 ============

class StructuredHighlights(BaseModel):
    """结构化划重点"""
    research_goals: List[str] = Field(default_factory=list, description="研究目标")
    innovations: List[str] = Field(default_factory=list, description="创新点")
    technical_route: List[str] = Field(default_factory=list, description="技术路线")


class IndustryFitResult(BaseModel):
    """产业指南贴合结果"""
    fit_score: float = Field(default=0.0, ge=0, le=1, description="贴合度得分")
    matched: List[str] = Field(default_factory=list, description="匹配项")
    gaps: List[str] = Field(default_factory=list, description="差距项")
    suggestions: List[str] = Field(default_factory=list, description="建议")


class BenchmarkReference(BaseModel):
    """技术摸底参考条目"""
    source: str = Field(..., description="来源类型，例如 literature/patent")
    title: str = Field(..., description="标题")
    snippet: str = Field(default="", description="摘要片段")
    year: Optional[int] = Field(default=None, description="年份")
    url: Optional[str] = Field(default=None, description="链接")
    score: Optional[float] = Field(default=None, description="相关度")


class BenchmarkResult(BaseModel):
    """技术摸底结论"""
    novelty_level: str = Field(default="unknown", description="新颖性等级")
    literature_position: str = Field(default="", description="文献定位")
    patent_overlap: str = Field(default="", description="专利重叠")
    conclusion: str = Field(default="", description="综合结论")
    references: List[BenchmarkReference] = Field(default_factory=list, description="参考条目")


class EvidenceItem(BaseModel):
    """证据条目"""
    source: str = Field(..., description="证据来源")
    file: str = Field(default="", description="文件名")
    page: int = Field(default=0, ge=0, description="页码")
    snippet: str = Field(default="", description="证据片段")
    category: str = Field(default="", description="证据分类，如 goal/innovation/route")
    target: str = Field(default="", description="对应的摘要条目或结论")


class EvaluationError(BaseModel):
    """评审子任务错误"""
    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误信息")
    module: Optional[str] = Field(default=None, description="模块名")


# ============ 评审结果模型 ============

class EvaluationResult(BaseModel):
    """评审结果
    
    包含项目的总分、等级、各维度评分、综合意见和修改建议。
    """
    project_id: str = Field(..., description="项目ID")
    project_name: Optional[str] = Field(default=None, description="项目名称")
    
    # 总分（加权平均，满分10分）
    overall_score: float = Field(..., ge=0, le=10, description="加权总分")
    
    # 等级（根据分数自动判定）
    grade: str = Field(..., description="等级：A/B/C/D/E")
    
    # 各维度评分
    dimension_scores: List[DimensionScore] = Field(
        default_factory=list,
        description="各维度评分详情"
    )
    
    # 综合意见
    summary: str = Field(..., description="综合评审意见")
    
    # 建议
    recommendations: List[str] = Field(
        default_factory=list,
        description="修改建议"
    )

    # 评审标识（用于聊天等后续能力）
    evaluation_id: Optional[str] = Field(default=None, description="评审记录ID")

    # 融合能力输出
    highlights: Optional[StructuredHighlights] = Field(default=None, description="结构化划重点")
    industry_fit: Optional[IndustryFitResult] = Field(default=None, description="产业指南贴合")
    benchmark: Optional[BenchmarkResult] = Field(default=None, description="技术摸底结论")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="证据链")
    chat_ready: bool = Field(default=False, description="是否可进行聊天问答")
    partial: bool = Field(default=False, description="是否为降级结果")
    errors: List[EvaluationError] = Field(default_factory=list, description="错误列表")
    
    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    model_version: Optional[str] = Field(default=None, description="模型版本")
    
    @classmethod
    def determine_grade(cls, score: float) -> str:
        """根据分数判定等级"""
        for grade, threshold in GRADE_THRESHOLDS.items():
            if score >= threshold:
                return grade
        return "E"


class BatchEvaluationResult(BaseModel):
    """批量评审结果"""
    total: int = Field(..., description="总数")
    success: int = Field(..., description="成功数")
    failed: int = Field(..., description="失败数")
    results: List[EvaluationResult] = Field(default_factory=list, description="评审结果列表")
    summary: Dict[str, Any] = Field(default_factory=dict, description="汇总统计")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="错误列表")


# ============ 检查结果模型（检查器内部使用） ============

class CheckResult(BaseModel):
    """检查结果
    
    检查器执行后返回的结果，用于构建 DimensionScore。
    """
    dimension: str = Field(..., description="维度代码")
    dimension_name: str = Field(default="", description="维度名称")
    score: float = Field(..., ge=1, le=10, description="总得分 (1-10)")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    opinion: str = Field(..., description="综合评审意见")
    issues: List[str] = Field(default_factory=list, description="问题列表")
    highlights: List[str] = Field(default_factory=list, description="亮点列表")
    items: List[CheckItem] = Field(default_factory=list, description="检查项详情")
    details: Dict[str, Any] = Field(default_factory=dict, description="额外信息")
    
    def model_post_init(self, __context: Any) -> None:
        """初始化后自动填充维度名称"""
        if not self.dimension_name and self.dimension in DIMENSION_NAMES:
            self.dimension_name = DIMENSION_NAMES[self.dimension]


# ============ 维度信息模型（API响应） ============

class DimensionCheckItem(BaseModel):
    """维度检查项信息"""
    name: str = Field(..., description="检查项名称")
    weight: float = Field(..., description="权重")
    description: str = Field(default="", description="描述")


class DimensionInfo(BaseModel):
    """维度信息（API响应）"""
    code: str = Field(..., description="维度代码")
    name: str = Field(..., description="维度名称")
    category: str = Field(..., description="维度分类")
    description: str = Field(default="", description="描述")
    default_weight: float = Field(..., description="默认权重")
    check_items: List[DimensionCheckItem] = Field(default_factory=list, description="检查项")
    required_sections: List[str] = Field(default_factory=list, description="依赖章节")


class DimensionsResponse(BaseModel):
    """维度列表响应"""
    dimensions: List[DimensionInfo] = Field(default_factory=list)


# ============ 权重验证模型 ============

class WeightValidateRequest(BaseModel):
    """权重验证请求"""
    weights: Dict[str, float] = Field(..., description="权重配置")


class WeightValidateResponse(BaseModel):
    """权重验证响应"""
    valid: bool = Field(..., description="是否有效")
    message: str = Field(..., description="消息")
    normalized_weights: Optional[Dict[str, float]] = Field(default=None, description="归一化后的权重")
    errors: Optional[List[Dict[str, Any]]] = Field(default=None, description="错误列表")


# ============ 聊天问答模型 ============

class ChatCitation(BaseModel):
    """问答引用"""
    file: str = Field(default="", description="文件名")
    page: int = Field(default=0, ge=0, description="页码")
    snippet: str = Field(default="", description="引用片段")


class EvaluationChatAskRequest(BaseModel):
    """聊天问答请求"""
    evaluation_id: str = Field(..., description="评审记录ID")
    question: str = Field(..., min_length=1, description="问题")


class EvaluationChatAskResponse(BaseModel):
    """聊天问答响应"""
    answer: str = Field(..., description="回答")
    citations: List[ChatCitation] = Field(default_factory=list, description="引用")


# ============ 辅助函数 ============

def get_dimension_name(dimension: str) -> str:
    """获取维度中文名称"""
    return DIMENSION_NAMES.get(dimension, dimension)


def get_dimension_category(dimension: str) -> str:
    """获取维度分类"""
    for category, dims in DIMENSION_CATEGORIES.items():
        if dimension in [d.value for d in dims]:
            return category
    return "其他"


def determine_grade(score: float) -> str:
    """根据分数判定等级"""
    for grade, threshold in GRADE_THRESHOLDS.items():
        if score >= threshold:
            return grade
    return "E"
