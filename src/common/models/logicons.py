"""逻辑自洽校验数据模型"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ConflictSeverity(str, Enum):
    """冲突严重等级"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConflictCategory(str, Enum):
    """冲突类别"""

    TIMELINE = "timeline"
    BUDGET = "budget"
    INDICATOR = "indicator"
    SEMANTIC = "semantic"


class DocSpan(BaseModel):
    """文档定位片段"""

    section: str = Field(..., description="章节名称")
    location: str = Field(..., description="位置，如 line:12")
    quote: str = Field(..., description="证据原文")


class ExtractedEntity(BaseModel):
    """抽取到的实体"""

    entity_type: str = Field(..., description="实体类型：time/money/person/org/indicator")
    name: str = Field(..., description="实体名")
    value: Optional[float] = Field(None, description="数值值")
    unit: Optional[str] = Field(None, description="单位")
    section: str = Field(..., description="章节")
    location: str = Field(..., description="位置")
    raw_text: str = Field(..., description="原始文本")


class GraphEdge(BaseModel):
    """图谱关系边"""

    source: int = Field(..., description="源节点索引")
    target: int = Field(..., description="目标节点索引")
    relation: str = Field(..., description="关系类型")


class DocumentGraph(BaseModel):
    """临时文档图谱"""

    entities: List[ExtractedEntity] = Field(default_factory=list, description="实体列表")
    edges: List[GraphEdge] = Field(default_factory=list, description="关系边列表")


class ConflictItem(BaseModel):
    """冲突项"""

    conflict_id: str = Field(..., description="冲突ID")
    rule_code: str = Field(..., description="规则编码")
    category: ConflictCategory = Field(..., description="冲突类别")
    severity: ConflictSeverity = Field(..., description="严重等级")
    message: str = Field(..., description="冲突描述")
    suggestion: str = Field(..., description="修正建议")
    evidences: List[DocSpan] = Field(default_factory=list, description="证据列表")


class LogiConsSummary(BaseModel):
    """冲突统计摘要"""

    high: int = Field(0, description="高风险数量")
    medium: int = Field(0, description="中风险数量")
    low: int = Field(0, description="低风险数量")
    total: int = Field(0, description="冲突总数")


class GraphStats(BaseModel):
    """图谱统计信息"""

    entity_count: int = Field(0, description="实体数")
    edge_count: int = Field(0, description="关系数")


class LogiConsTextRequest(BaseModel):
    """文本校验请求"""

    project_id: str = Field(..., description="项目ID")
    text: str = Field(..., description="待校验文本")
    budget_tolerance: float = Field(0.01, description="预算容差比例")
    timeline_grace_years: int = Field(0, description="时间宽限年数")
    enable_llm_enhancement: bool = Field(False, description="是否启用大模型增强")


class LogiConsResult(BaseModel):
    """逻辑自洽校验结果"""

    check_id: str = Field(..., description="校验任务ID")
    project_id: str = Field(..., description="项目ID")
    summary: LogiConsSummary = Field(..., description="冲突统计")
    conflicts: List[ConflictItem] = Field(default_factory=list, description="冲突明细")
    graph_stats: GraphStats = Field(default_factory=GraphStats, description="图谱统计")
    warnings: List[str] = Field(default_factory=list, description="提示信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class LogiConsTask(BaseModel):
    """任务状态"""

    check_id: str = Field(..., description="任务ID")
    project_id: str = Field(..., description="项目ID")
    state: str = Field(..., description="任务状态")
    summary: Optional[LogiConsSummary] = Field(None, description="结果摘要")


class RuleInfo(BaseModel):
    """规则信息"""

    code: str
    name: str
    category: ConflictCategory
    default_enabled: bool = True


class RuleConfigSnapshot(BaseModel):
    """规则配置快照"""

    rules: List[RuleInfo]
    defaults: dict
