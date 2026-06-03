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
    year: str = Field(default="", description="年度")
    guide_name: str = Field(default="", description="指南名称")
    applicant_unit: str = Field(default="", description="申报单位")
    applicant_unit_type: str = Field(default="", description="申报单位类型")
    applicant_region: str = Field(default="", description="申报单位注册地区")
    applicant_credit_code: str = Field(default="", description="统一社会信用代码")
    applicant_is_independent_legal_person: Optional[bool] = Field(default=None, description="是否独立法人")
    applicant_is_government_agency: bool = Field(False, description="申报单位是否行政机关")
    registered_date: str = Field(default="", description="注册时间")
    project_leader_birth_date: str = Field(default="", description="项目负责人出生日期")
    execution_period_years: float = Field(0, description="执行期")
    fiscal_funding: float = Field(0, description="财政资金")
    self_funding: float = Field(0, description="自筹资金")
    budget_line_items: List[str] = Field(default_factory=list, description="预算相关明细行")
    performance_metric_count: int = Field(0, description="绩效指标数量")
    performance_first_year_ratio: Optional[float] = Field(default=None, description="第一年度目标占总体目标比例")
    performance_metric_rows: List[Dict[str, Any]] = Field(default_factory=list, description="绩效指标明细")
    has_clinical_research: bool = Field(False, description="是否涉及临床研究")
    has_special_industry_requirement: bool = Field(False, description="是否涉及特种行业")
    has_biosafety_activity: bool = Field(False, description="是否涉及生物安全活动")
    has_cooperation_unit: bool = Field(False, description="是否有合作单位")
    leader_achievement_categories: List[str] = Field(default_factory=list, description="负责人/骨干成果类别")
    leader_achievement_evidence_lines: List[str] = Field(default_factory=list, description="负责人/骨干成果线索")


class CooperationInfo(BaseModel):
    """合作单位信息"""

    cooperation_units: List[str] = Field(default_factory=list, description="合作单位列表")
    cooperation_unit_types: List[str] = Field(default_factory=list, description="合作单位类型列表")
    cooperation_regions: List[str] = Field(default_factory=list, description="合作单位地区列表")
    cooperation_unit_region_details: List[Dict[str, str]] = Field(default_factory=list, description="合作单位地区明细")
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
    recognition_confidence: float = Field(0.0, description="类型识别置信度")
    classification_source: str = Field(default="", description="分类来源")
    classification_reason: str = Field(default="", description="分类原因")
    classification_details: Dict[str, Any] = Field(default_factory=dict, description="分类调试信息")


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


class BatchReviewRequest(BaseModel):
    """批次形式审查请求"""

    zxmc: str = Field(..., description="专项/批次标识")
    limit: Optional[int] = Field(default=None, ge=1, description="最多处理的项目数")
    project_ids: List[str] = Field(default_factory=list, description="指定处理的项目ID列表")
    notice_url: str = Field(default="", description="申报通知 URL")
    notice_html: str = Field(default="", description="申报通知 HTML 正文")


class ProjectIndexRow(BaseModel):
    """项目索引记录"""

    project_id: str = Field(..., description="项目ID")
    year: str = Field(default="", description="年度")
    project_name: str = Field(default="", description="项目名称")
    guide_name: str = Field(default="", description="指南名称")
    applicant_unit: str = Field(default="", description="承担单位")
    unit_name: str = Field(default="", description="单位名称")
    project_leader: str = Field(default="", description="项目负责人")
    start_date: str = Field(default="", description="开始日期")
    end_date: str = Field(default="", description="结束日期")


class MissingAttachment(BaseModel):
    """缺失附件"""

    doc_kind: str = Field(..., description="缺失的附件类型")
    reason: str = Field(..., description="缺失原因")


class ManualReviewItem(BaseModel):
    """待人工复核项"""

    item: str = Field(..., description="复核项编码")
    message: str = Field(..., description="复核说明")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据")


class PolicyRuleCheck(BaseModel):
    """与 docx 单条规则一一对应的对照结果"""

    code: str = Field(..., description="规则编码")
    requirement: str = Field(default="", description="规则要求")
    status: str = Field(..., description="规则状态")
    source_rule: str = Field(default="", description="映射到的项目级规则")
    matched_result_item: Optional[str] = Field(default=None, description="实际命中的检查项")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据")
    reason: str = Field(default="", description="状态说明")


class ProjectReviewResult(BaseModel):
    """项目级审查结果"""

    id: str = Field(..., description="项目审查ID")
    project_id: str = Field(..., description="项目ID")
    project_type: str = Field(..., description="项目类型")
    results: List[CheckResult] = Field(default_factory=list, description="项目级规则结果")
    policy_rule_checks: List[PolicyRuleCheck] = Field(default_factory=list, description="docx 逐条规则对照结果")
    missing_attachments: List[MissingAttachment] = Field(default_factory=list, description="缺失附件")
    attachment_results: List[ReviewResult] = Field(default_factory=list, description="附件级结果")
    manual_review_items: List[ManualReviewItem] = Field(default_factory=list, description="待人工复核项")
    summary: str = Field(..., description="审查总结")
    suggestions: List[str] = Field(default_factory=list, description="建议")
    processed_at: datetime = Field(default_factory=datetime.now)
    processing_time: float = Field(..., description="处理时间（秒）")


class BatchReviewResult(BaseModel):
    """批次形式审查结果"""

    id: str = Field(..., description="批次审查ID")
    zxmc: str = Field(..., description="专项/批次标识")
    project_count: int = Field(..., description="项目数量")
    project_results: List[ProjectReviewResult] = Field(default_factory=list, description="项目审查结果")
    debug_dir: str = Field(default="", description="调试输出目录")
    report_url: str = Field(default="", description="报告访问地址")
    summary: str = Field(..., description="批次审查总结")
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

    project_index_row: Optional[ProjectIndexRow] = None
    project_info: ProjectInfo
    cooperation_info: Optional[CooperationInfo] = None
    attachments: List[ProjectAttachment] = Field(default_factory=list)
    attachment_results: Dict[str, ReviewResult] = Field(default_factory=dict)
    external_checks: Optional[ExternalChecks] = None
    attachment_classification_reliable: bool = Field(False, description="附件类型识别是否可靠")
    scan_info: Dict[str, Any] = Field(default_factory=dict, description="目录扫描信息")
    notice_context: Dict[str, Any] = Field(default_factory=dict, description="申报通知上下文")
