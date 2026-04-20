"""审查结果模型"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator

from src.services.review.doc_types import normalize_doc_type


class CheckStatus(str, Enum):
    """检查状态"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class CheckResult(BaseModel):
    """检查结果"""
    item: str = Field(..., description="检查项名称")
    status: CheckStatus = Field(..., description="检查状态")
    message: str = Field(..., description="检查详情")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据")
    confidence: float = Field(default=1.0, ge=0, le=1, description="置信度")


class ReviewResult(BaseModel):
    """审查结果"""
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="审查ID")
    status: str = Field(default="done", description="处理状态：processing/done/failed")
    doc_type: str = Field(
        ...,
        validation_alias=AliasChoices("doc_type", "document_type"),
        description="统一文档类型",
    )
    doc_type_raw: str = Field(
        default="",
        validation_alias=AliasChoices("doc_type_raw", "document_type_raw"),
        description="原始文档类型输入/分类结果",
    )
    results: List[CheckResult] = Field(default_factory=list, description="检查结果列表")
    structured_result: Dict[str, Any] = Field(default_factory=dict, description="按业务分组的结构化结果")
    ocr_text: str = Field(default="", description="OCR 提取的文字内容")
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="提取的结构化数据")
    llm_analysis: Optional[Dict[str, Any]] = Field(default=None, description="LLM 深度分析结果")
    summary: str = Field(..., description="审查总结")
    suggestions: List[str] = Field(default_factory=list, description="建议")
    processed_at: datetime = Field(default_factory=datetime.now)
    processing_time: float = Field(..., description="处理时间（秒）")

    @field_validator("doc_type", mode="before")
    @classmethod
    def _normalize_doc_type(cls, value: Any) -> str:
        return normalize_doc_type(str(value or ""))

    @computed_field
    @property
    def document_type(self) -> str:
        """兼容旧字段名。"""
        return self.doc_type

    @computed_field
    @property
    def document_type_raw(self) -> str:
        """兼容旧字段名。"""
        return self.doc_type_raw
