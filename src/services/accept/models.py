"""科技项目结题验收模型。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.common.models.document import BoundingBox


MetricComparator = Literal["≥", "≤", "=", ">", "<"]
EvidenceAggregation = Literal["sum", "max", "count"]
EvidenceStatus = Literal["fulfilled", "partial", "missing"]
EvidenceMode = Literal["itemized", "summary"]
EvidenceRole = Literal["primary", "supporting", "derived"]
MetricEvaluationLayer = Literal["deliverable", "numeric", "technical", "financial", "talent", "generic"]
EvidenceNature = Literal["artifact", "proof", "summary", "catalog", "reference", "unknown"]
EvidenceJudgeSource = Literal["rule", "llm", "hybrid", "unknown"]


class ParsedAcceptanceDocument(BaseModel):
    """统一文档解析结果。"""

    file_name: str = ""
    file_type: str = ""
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list["ParsedAcceptanceBlock"] = Field(default_factory=list)


class ParsedAcceptanceBlock(BaseModel):
    """原文材料块，用于页内定位。"""

    block_id: str
    text: str
    page: int = 0
    bbox: Optional[BoundingBox] = None
    line_index_start: int = 0
    line_index_end: int = 0


class KPICommitment(BaseModel):
    """任务书中的承诺指标。"""

    commitment_id: str
    metric_name: str
    metric_category: str
    target_value: float
    target_unit: str
    comparator: MetricComparator = "≥"
    aggregation: EvidenceAggregation = "sum"
    action: str = ""
    subject_scope: str = ""
    time_constraint: str = ""
    caliber_constraint: str = ""
    metric_variant: str = ""
    metric_layer: MetricEvaluationLayer = "generic"
    alternate_metric_names: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source_line: str = ""
    source_section: str = ""
    source_block_id: str = ""
    source_page: int = 0


class AttachmentEvidence(BaseModel):
    """附件中的证据项。"""

    evidence_id: str
    file_name: str
    doc_kind: str
    metric_name: str
    metric_category: str
    value: Optional[float] = None
    unit: str = ""
    implicit_count: float = 0.0
    action: str = ""
    subject_scope: str = ""
    time_label: str = ""
    caliber_label: str = ""
    metric_variant: str = ""
    normalized_value: Optional[float] = None
    normalized_unit: str = ""
    evidence_mode: EvidenceMode = "summary"
    evidence_role: EvidenceRole = "supporting"
    evidence_nature: EvidenceNature = "unknown"
    evidence_judge_source: EvidenceJudgeSource = "unknown"
    evidence_judge_reason: str = ""
    artifact_key: str = ""
    normalized_artifact_key: str = ""
    artifact_title: str = ""
    confidence: float = 0.5
    title: str = ""
    excerpt: str = ""
    keywords: list[str] = Field(default_factory=list)
    source_block_id: str = ""
    source_page: int = 0


class KPIMatchDetail(BaseModel):
    """单条指标与证据的匹配详情。"""

    evidence_id: str
    file_name: str
    doc_kind: str
    metric_name: str = ""
    contribution_value: float
    evidence_role: EvidenceRole = "supporting"
    evidence_mode: EvidenceMode = "summary"
    evidence_nature: EvidenceNature = "unknown"
    evidence_judge_source: EvidenceJudgeSource = "unknown"
    evidence_judge_reason: str = ""
    artifact_key: str = ""
    time_label: str = ""
    caliber_label: str = ""
    title: str = ""
    excerpt: str = ""
    reason: str = ""
    source_block_id: str = ""
    source_page: int = 0


class AcceptanceCheckRow(BaseModel):
    """自动核查表中的一行。"""

    commitment_id: str
    metric_name: str
    metric_category: str
    target_display: str
    target_value: float
    target_unit: str
    actual_display: str
    actual_value: float
    application_display: str = ""
    application_value: float = 0.0
    application_evidence_count: int = 0
    attachment_display: str = ""
    attachment_value: float = 0.0
    attachment_evidence_count: int = 0
    consistency_summary: str = ""
    fulfillment_ratio: float
    status: EvidenceStatus
    matched_evidence_count: int
    applied_evidence_count: int = 0
    rule_basis: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    reason: str
    source_line: str = ""
    action: str = ""
    subject_scope: str = ""
    time_constraint: str = ""
    caliber_constraint: str = ""
    metric_variant: str = ""
    metric_layer: MetricEvaluationLayer = "generic"
    application_status: EvidenceStatus = "missing"
    attachment_status: EvidenceStatus = "missing"
    conflict_flags: list[str] = Field(default_factory=list)
    match_details: list[KPIMatchDetail] = Field(default_factory=list)
    source_block_id: str = ""
    source_page: int = 0


class AcceptanceCheckResult(BaseModel):
    """验收指标自动核查结果。"""

    project_id: str
    total_commitments: int
    fulfilled_commitments: int
    partial_commitments: int
    missing_commitments: int
    fulfillment_rate: float
    rows: list[AcceptanceCheckRow] = Field(default_factory=list)
    extracted_commitments: list[KPICommitment] = Field(default_factory=list)
    extracted_evidence: list[AttachmentEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_markdown_table(self) -> str:
        """渲染《验收指标自动核查表》Markdown。"""
        headers = [
            "指标",
            "目标值",
            "核验值",
            "履约率",
            "状态",
            "证据数",
            "核验说明",
        ]
        lines = ["| " + " | ".join(headers) + " |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for row in self.rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row.metric_name,
                        row.target_display,
                        row.actual_display,
                        f"{row.fulfillment_ratio:.0%}",
                        row.status,
                        str(row.matched_evidence_count),
                        row.reason.replace("\n", " ").strip(),
                    ]
                )
                + " |"
            )
        return "\n".join(lines)
