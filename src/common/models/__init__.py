"""通用数据模型

所有服务共享使用的数据类型定义。
"""
from src.common.models.api import ApiResponse, PaginatedResponse, ResponseStatus
from src.common.models.document import BoundingBox, DocumentContent, ImageRegion, TextBlock
from src.common.models.enums import CheckItem, DocumentType
from src.common.models.file import FileMeta, FileType, UploadFile
from src.common.models.review import CheckResult, CheckStatus, ReviewResult
from src.common.models.project_review import (
    ProjectInfo,
    CooperationInfo,
    ProjectAttachment,
    ExternalChecks,
    ProjectReviewRequest,
    MissingAttachment,
    ProjectReviewResult,
    ProjectTypeInfo,
    ProjectReviewContext,
)
from src.common.models.types import JSON, ImageData, CheckFunction
# 分组服务模型
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
    Expert,
    ExpertProfile,
    ExpertAssignment,
    AssignedExpert,
    AvoidanceInfo,
    MatchingRequest,
    MatchingResult,
    MatchingStatistics,
    FullGroupingRequest,
    FullGroupingResult,
    FullStatistics,
)
from src.common.models.perfcheck import (
    Budget,
    BudgetItem,
    BudgetComparison,
    ContentComparison,
    DocumentSchema,
    BasicInfo,
    TeamMember,
    Organization,
    UnitBudgetAllocation,
    MetricComparison,
    PerformanceTarget,
    PerfCheckRequest,
    PerfCheckResult,
    PerfCheckTask,
    ResearchContent,
    OtherInfoComparison,
    UnitBudgetComparison,
)


__all__ = [
    # 文件模型
    "FileType",
    "FileMeta",
    "UploadFile",
    # 审查模型
    "CheckStatus",
    "CheckResult",
    "ReviewResult",
    "ProjectInfo",
    "CooperationInfo",
    "ProjectAttachment",
    "ExternalChecks",
    "ProjectReviewRequest",
    "MissingAttachment",
    "ProjectReviewResult",
    "ProjectTypeInfo",
    "ProjectReviewContext",
    # 文档模型
    "BoundingBox",
    "TextBlock",
    "ImageRegion",
    "DocumentContent",
    # API 模型
    "ResponseStatus",
    "ApiResponse",
    "PaginatedResponse",
    # 类型别名
    "JSON",
    "ImageData",
    "CheckFunction",
    # 枚举
    "DocumentType",
    "CheckItem",
    # 分组服务模型
    "GroupingStrategy",
    "GroupingRequest",
    "GroupingResult",
    "GroupingStatistics",
    "GroupSummary",
    "Project",
    "ProjectAnalysis",
    "ProjectGroup",
    "ProjectInGroup",
    "Expert",
    "ExpertProfile",
    "ExpertAssignment",
    "AssignedExpert",
    "AvoidanceInfo",
    "MatchingRequest",
    "MatchingResult",
    "MatchingStatistics",
    "FullGroupingRequest",
    "FullGroupingResult",
    "FullStatistics",
    # 绩效核验模型
    "Budget",
    "BudgetItem",
    "BudgetComparison",
    "ContentComparison",
    "DocumentSchema",
    "BasicInfo",
    "TeamMember",
    "Organization",
    "UnitBudgetAllocation",
    "MetricComparison",
    "PerformanceTarget",
    "PerfCheckRequest",
    "PerfCheckResult",
    "PerfCheckTask",
    "ResearchContent",
    "OtherInfoComparison",
    "UnitBudgetComparison",
    # 逻辑自洽模型
    "ConflictSeverity",
    "ConflictCategory",
    "DocSpan",
    "ExtractedEntity",
    "GraphEdge",
    "DocumentGraph",
    "ConflictItem",
    "GraphStats",
    "RuleInfo",
    "RuleConfigSnapshot",
]
