from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ConflictSeverity(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ConflictCategory(str, Enum):
    TIME_SPAN = "TIME_SPAN"
    BUDGET_SUM = "BUDGET_SUM"
    BUDGET_TOTAL = "BUDGET_TOTAL"
    METRIC_VALUE = "METRIC_VALUE"
    METRIC_UNIT = "METRIC_UNIT"
    ORG_ROLE = "ORG_ROLE"
    PERSON_ROLE = "PERSON_ROLE"
    OTHER = "OTHER"


class DocSpan(BaseModel):
    page: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str = ""


class ExtractedEntity(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    value: str = ""
    normalized: Dict[str, Any] = {}
    spans: List[DocSpan] = []


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    relation: str
    confidence: float = 1.0


class GraphStats(BaseModel):
    entity_count: int = 0
    edge_count: int = 0


class DocumentGraph(BaseModel):
    doc_id: str
    entities: List[ExtractedEntity] = []
    edges: List[GraphEdge] = []
    stats: GraphStats = GraphStats()


class RuleInfo(BaseModel):
    rule_id: str
    name: str = ""


class RuleConfigSnapshot(BaseModel):
    version: str = "v1"
    enabled_rules: List[RuleInfo] = []
    thresholds: Dict[str, Any] = {}


class ConflictItem(BaseModel):
    conflict_id: str
    severity: ConflictSeverity
    category: ConflictCategory
    title: str
    description: str
    evidence: List[DocSpan] = []
    related_entities: List[str] = []
    rule_id: str = ""


class LogicOnDimensionSummary(BaseModel):
    """按 R-TIME-01 / R-BUDGET-01 / R-METRIC-01 维度的结论与可读说明。"""

    rule_id: str
    name: str = ""
    # consistent: 已核对且未发现矛盾；inconsistent: 已检出矛盾；insufficient: 抽取不足无法核对
    outcome: str = "insufficient"
    detail_lines: List[str] = []


class LogicOnResult(BaseModel):
    doc_id: str
    doc_kind: str = "unknown"
    # 从正文抽取并清洗后的展示名（与批量 debug 列表 display_name 同源逻辑）
    project_name: str = ""
    partial: bool = False
    conflicts: List[ConflictItem] = []
    graph: Optional[DocumentGraph] = None
    rule_snapshot: RuleConfigSnapshot = RuleConfigSnapshot()
    warnings: List[str] = []
    dimension_summaries: List[LogicOnDimensionSummary] = []
    # 工具调用 Agent：在规则检出后生成的复核说明与轨迹（可选）
    agent_analysis: Optional[str] = None
    agent_tool_trace: Optional[List[Dict[str, Any]]] = None


class LogicOnTextRequest(BaseModel):
    doc_kind: str = "auto"
    text: str
    enable_llm: bool = True
    return_graph: bool = False
    enable_agent: bool = True
    agent_max_turns: int = 8
    enable_equivalence_probe: bool = True
    amount_tolerance_wan: float = 0.01
    date_tolerance_days: int = 30
    metric_tolerance_ratio: float = 0.01


class LogicOnTask(BaseModel):
    task_id: str
    doc_id: str
    state: str
    progress: float = 0.0
    stage: str = ""
    error_code: str = ""
    message: str = ""
    summary: str = ""
    result: Optional[LogicOnResult] = None
