"""审查结果模型"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    id: str = Field(..., description="审查ID")
    document_type: str = Field(..., description="文档类型")
    document_type_raw: str = Field(default="", description="LLM 原始分类结果")
    results: List[CheckResult] = Field(default_factory=list, description="检查结果列表")
    ocr_text: str = Field(default="", description="OCR 提取的文字内容")
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="提取的结构化数据")
    llm_analysis: Optional[Dict[str, Any]] = Field(default=None, description="LLM 深度分析结果")
    summary: str = Field(..., description="审查总结")
    suggestions: List[str] = Field(default_factory=list, description="建议")
    processed_at: datetime = Field(default_factory=datetime.now)
    processing_time: float = Field(..., description="处理时间（秒）")
