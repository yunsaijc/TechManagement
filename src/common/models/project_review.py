"""项目级形式审查模型"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.models.review import CheckResult, ReviewResult


class ProjectInfo(BaseModel):
    """项目基础信息"""

    project_id: str = Field(..., description="项目唯一标识")
    project_type: str = Field(..., description="项目类型")
    project_name: str = Field(default="", description="项目名称")
    applicant_unit: str = Field(default="", description="申报单位")
    applicant_unit_type: str = Field(default="", description="申报单位类型")
    registered_date: str = Field(default="", description="注册时间")
    execution_period_years: float = Field(0, description="执行期")
    fiscal_funding: float = Field(0, description="财政资金")
    self_funding: float = Field(0, description="自筹资金")
    has_clinical_research: bool = Field(False, description="是否涉及临床研究")
    has_special_industry_requirement: bool = Field(False, description="是否涉及特种行业")
    has_biosafety_activity: bool = Field(False, description="是否涉及生物安全活动")
    has_cooperation_unit: bool = Field(False, description="是否有合作单位")


class CooperationInfo(BaseModel):
    """合作单位信息"""

    cooperation_units: List[str] = Field(default_factory=list, description="合作单位列表")
    cooperation_regions: List[str] = Field(default_factory=list, description="合作单位地区列表")
    has_formal_cooperation_agreement: bool = Field(False, description="是否有正式合作协议")
    has_management_recommendation_letter: bool = Field(False, description="是否有推荐函")


class ProjectAttachment(BaseModel):
    """项目附件"""

    attachment_id: str = Field(..., description="附件唯一标识")
    doc_kind: str = Field(..., description="附件业务类型")
    file_name: str = Field(..., description="文件名")
    file_ref: str = Field(..., description="文件引用")
    document_type: Optional[str] = Field(default=None, description="附件级审查类型")
    required: bool = Field(False, description="是否必需")


class ExternalChecks(BaseModel):
    """外部校验结果"""

    integrity_status: str = Field(default="", description="科研失信状态")
    social_credit_status: str = Field(default="", description="社会失信状态")
    duplicate_submission_status: str = Field(default="", description="重复申报状态")
    applicant_region: str = Field(default="", description="申报单位地区")
    extra: Dict[str, Any] = Field(default_factory=dict, description="扩展字段")


class ProjectReviewRequest(BaseModel):
    """项目级审查请求"""

    project_info: ProjectInfo
    cooperation_info: Optional[CooperationInfo] = None
    attachments: List[ProjectAttachment] = Field(default_factory=list)
    external_checks: Optional[ExternalChecks] = None


class MissingAttachment(BaseModel):
    """缺失附件"""

    doc_kind: str = Field(..., description="缺失的附件类型")
    reason: str = Field(..., description="缺失原因")


class ProjectReviewResult(BaseModel):
    """项目级审查结果"""

    id: str = Field(..., description="项目审查ID")
    project_id: str = Field(..., description="项目ID")
    project_type: str = Field(..., description="项目类型")
    results: List[CheckResult] = Field(default_factory=list, description="项目级规则结果")
    missing_attachments: List[MissingAttachment] = Field(default_factory=list, description="缺失附件")
    attachment_results: List[ReviewResult] = Field(default_factory=list, description="附件级结果")
    summary: str = Field(..., description="审查总结")
    suggestions: List[str] = Field(default_factory=list, description="建议")
    processed_at: datetime = Field(default_factory=datetime.now)
    processing_time: float = Field(..., description="处理时间（秒）")


class ProjectTypeInfo(BaseModel):
    """项目类型信息"""

    value: str
    label: str
    required_doc_kinds: List[str] = Field(default_factory=list)


class ProjectReviewContext(BaseModel):
    """项目级审查上下文"""

    project_info: ProjectInfo
    cooperation_info: Optional[CooperationInfo] = None
    attachments: List[ProjectAttachment] = Field(default_factory=list)
    attachment_results: Dict[str, ReviewResult] = Field(default_factory=dict)
    external_checks: Optional[ExternalChecks] = None
