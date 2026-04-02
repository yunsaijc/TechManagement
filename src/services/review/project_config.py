"""项目级形式审查配置"""
import os
import re
from typing import Any, Dict, List, Optional

from src.services.review.notice_rules import get_merged_policy_review_points


PROJECT_CONFIG: Dict[str, Dict[str, Any]] = {
    "regional_innovation": {
        "label": "区域创新体系建设项目",
        "guide_names": ["区域创新体系建设项目", "区域科技创新体系项目"],
        "required_project_fields": [
            "project_id",
            "project_type",
            "project_name",
            "applicant_unit",
            "execution_period_years",
            "year",
        ],
        "required_doc_kinds": ["commitment_letter"],
        "conditional_doc_rules": [
            {"when": "has_clinical_research", "doc_kind": "ethics_approval", "reason": "涉及临床研究时需提供伦理审查意见"},
            {"when": "has_special_industry_requirement", "doc_kind": "industry_permit", "reason": "涉及特种行业时需提供行业准入资格或许可"},
            {"when": "has_biosafety_activity", "doc_kind": "biosafety_commitment", "reason": "涉及生物安全活动时需提供生物安全承诺书"},
            {"when": "has_cooperation_unit", "doc_kind": "cooperation_agreement", "reason": "存在合作单位时需提供合作协议"},
            {"when": "has_cooperation_unit", "doc_kind": "recommendation_letter", "reason": "存在合作单位时需提供合作方科技管理部门推荐函"},
        ],
        "project_rules": [
            "required_project_fields",
            "registered_date_limit",
            "project_leader_age_check",
            "funding_ratio_check",
            "budget_forbidden_expense_check",
            "performance_metric_count_check",
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
            "policy_review_points_check",
        ],
        "constraints": {
            "registered_after": "2025-01-01",
            "max_execution_period_years": 2,
            "allowed_cooperation_regions": [
                "新疆维吾尔自治区巴音郭楞蒙古自治州",
                "新疆生产建设兵团第二师铁门关市",
                "西藏自治区阿里地区",
            ],
            "min_self_funding_ratio": 1.0,
        },
        "policy_review_points": [
            {"code": "registered_date_limit", "requirement": "单位注册时间在2025年1月1日后。", "automation": "requires_data", "reason": "当前项目上下文未接入注册时间字段"},
            {"code": "funding_ratio_check", "requirement": "申请财政资金与自筹资金比例不符合申报通知要求。", "automation": "requires_data", "reason": "当前未接入申报通知比例阈值和完整经费字段"},
            {"code": "external_status_check", "requirement": "项目存在科研失信、社会失信。", "automation": "auto"},
            {"code": "ethics_approval_required", "requirement": "涉及开展临床研究，未提交伦理审查意见。", "automation": "auto"},
            {"code": "industry_permit_required", "requirement": "涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料。", "automation": "auto"},
            {"code": "biosafety_commitment_required", "requirement": "涉及生物技术研究、开发、应用以及人类遗传资源相关活动的，未提交生物安全承诺书。", "automation": "auto"},
            {"code": "commitment_letter_required", "requirement": "未按要求提交承诺书。", "automation": "auto"},
            {"code": "cooperation_agreement_required", "requirement": "涉及合作单位，承担单位与合作单位未签订正式合作协议（合同）或合作协议不完整不规范。", "automation": "requires_data", "reason": "当前只能基于附件存在性判断，尚未结构化合作单位信息和协议完整性"},
            {"code": "cooperation_region_check", "requirement": "合作单位非新疆维吾尔自治区巴音郭楞蒙古自治州、新疆生产建设兵团第二师铁门关市或西藏自治区阿里地区注册的企事业单位。", "automation": "requires_data", "reason": "当前未接入合作单位注册地区"},
            {"code": "recommendation_letter_required", "requirement": "申报项目未提供合作方科技管理部门推荐函。", "automation": "requires_data", "reason": "当前未稳定识别合作单位场景与推荐函要求触发条件"},
            {"code": "execution_period_limit", "requirement": "执行期超过2年。", "automation": "auto"},
            {"code": "duplicate_submission_check", "requirement": "项目重复申报、多头申报。", "automation": "auto"},
            {"code": "other_policy_compliance", "requirement": "其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题。", "automation": "manual", "reason": "需人工综合复核申报指南和管理办法"},
        ],
    },
    "innovation_base": {
        "label": "科技创新基地项目",
        "guide_names": ["科技创新基地项目"],
        "required_project_fields": [
            "project_id",
            "project_type",
            "project_name",
            "applicant_unit",
            "execution_period_years",
            "year",
        ],
        "required_doc_kinds": ["commitment_letter", "base_staff_proof"],
        "conditional_doc_rules": [
            {"when": "has_clinical_research", "doc_kind": "ethics_approval", "reason": "涉及临床研究时需提供伦理审查意见"},
            {"when": "has_special_industry_requirement", "doc_kind": "industry_permit", "reason": "涉及特种行业时需提供行业准入资格或许可"},
            {"when": "has_biosafety_activity", "doc_kind": "biosafety_commitment", "reason": "涉及生物安全活动时需提供生物安全承诺书"},
            {"when": "has_cooperation_unit", "doc_kind": "cooperation_agreement", "reason": "存在合作单位时需提供合作协议"},
        ],
        "project_rules": [
            "required_project_fields",
            "registered_date_limit",
            "project_leader_age_check",
            "funding_ratio_check",
            "budget_forbidden_expense_check",
            "performance_metric_count_check",
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
            "policy_review_points_check",
        ],
        "constraints": {
            "registered_after": "2025-01-01",
            "max_execution_period_years": 2,
            "funding_ratio_by_applicant_type": {
                "enterprise": 2.0,
                "institution": 1.0,
                "university": 1.0,
                "research_institute": 1.0,
                "hospital": 1.0,
                "default": 1.0,
            },
        },
        "policy_review_points": [
            {"code": "registered_date_limit", "requirement": "单位注册时间在2025年1月1日后。", "automation": "requires_data", "reason": "当前项目上下文未接入注册时间字段"},
            {"code": "funding_ratio_check", "requirement": "申请财政资金与自筹资金比例不符合申报通知要求。", "automation": "requires_data", "reason": "当前未接入申报通知比例阈值和完整经费字段"},
            {"code": "external_status_check", "requirement": "项目存在科研失信、社会失信。", "automation": "auto"},
            {"code": "ethics_approval_required", "requirement": "涉及开展临床研究，未提交伦理审查意见。", "automation": "auto"},
            {"code": "industry_permit_required", "requirement": "涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料。", "automation": "auto"},
            {"code": "biosafety_commitment_required", "requirement": "涉及生物技术研究、开发、应用以及人类遗传资源相关活动的，未提交生物安全承诺书。", "automation": "auto"},
            {"code": "commitment_letter_required", "requirement": "未按要求提交承诺书。", "automation": "auto"},
            {"code": "cooperation_agreement_required", "requirement": "涉及合作单位，合作协议不完整不规范。", "automation": "requires_data", "reason": "当前只能基于附件存在性判断，尚未校验协议完整性"},
            {"code": "platform_scope_check", "requirement": "依托平台不在申报通知支持范围。", "automation": "requires_data", "reason": "当前未接入依托平台字段和支持范围清单"},
            {"code": "base_staff_proof_required", "requirement": "未将单位出具的基地固定人员证明作为附件上传。", "automation": "auto"},
            {"code": "joint_application_check", "requirement": "主办单位为高校、科研院所等事业单位的，未与企业联合申报。", "automation": "requires_data", "reason": "当前未接入联合申报主体结构和合作单位类型"},
            {"code": "execution_period_limit", "requirement": "执行期超过2年。", "automation": "auto"},
            {"code": "duplicate_submission_check", "requirement": "项目重复申报、多头申报。", "automation": "auto"},
            {"code": "other_policy_compliance", "requirement": "其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题。", "automation": "manual", "reason": "需人工综合复核申报指南和管理办法"},
        ],
    },
    "achievement_transformation": {
        "label": "科技成果转化项目",
        "guide_names": ["科技成果转化项目"],
        "required_project_fields": [
            "project_id",
            "project_type",
            "project_name",
            "applicant_unit",
            "execution_period_years",
            "year",
        ],
        "required_doc_kinds": ["commitment_letter"],
        "conditional_doc_rules": [
            {"when": "has_clinical_research", "doc_kind": "ethics_approval", "reason": "涉及临床研究时需提供伦理审查意见"},
            {"when": "has_special_industry_requirement", "doc_kind": "industry_permit", "reason": "涉及特种行业时需提供行业准入资格或许可"},
            {"when": "has_biosafety_activity", "doc_kind": "biosafety_commitment", "reason": "涉及生物安全活动时需提供生物安全承诺书"},
            {"when": "has_cooperation_unit", "doc_kind": "cooperation_agreement", "reason": "存在合作单位时需提供合作协议"},
        ],
        "project_rules": [
            "required_project_fields",
            "registered_date_limit",
            "project_leader_age_check",
            "funding_ratio_check",
            "budget_forbidden_expense_check",
            "performance_metric_count_check",
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "applicant_unit_type_check",
            "external_status_check",
            "policy_review_points_check",
        ],
        "constraints": {
            "registered_after": "2025-01-01",
            "max_execution_period_years": 2,
            "allowed_applicant_unit_types": ["enterprise"],
            "requires_beijing_tianjin_partner": True,
            "requires_cluster_region_match": True,
            "min_self_funding_ratio": 3.0,
        },
        "policy_review_points": [
            {"code": "registered_date_limit", "requirement": "单位注册时间在2025年1月1日后。", "automation": "requires_data", "reason": "当前项目上下文未接入注册时间字段"},
            {"code": "funding_ratio_check", "requirement": "申请财政资金与自筹资金比例不符合申报通知要求。", "automation": "requires_data", "reason": "当前未接入申报通知比例阈值和完整经费字段"},
            {"code": "external_status_check", "requirement": "项目存在科研失信、社会失信。", "automation": "auto"},
            {"code": "ethics_approval_required", "requirement": "涉及开展临床研究，未提交伦理审查意见。", "automation": "auto"},
            {"code": "industry_permit_required", "requirement": "涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料。", "automation": "auto"},
            {"code": "biosafety_commitment_required", "requirement": "涉及生物技术研究、开发、应用以及人类遗传资源相关活动的，未提交生物安全承诺书。", "automation": "auto"},
            {"code": "commitment_letter_required", "requirement": "未按要求提交承诺书。", "automation": "auto"},
            {"code": "cooperation_agreement_required", "requirement": "涉及合作单位，合作协议不完整不规范。", "automation": "requires_data", "reason": "当前只能基于附件存在性判断，尚未校验协议完整性"},
            {"code": "applicant_unit_type_check", "requirement": "申报单位非企业。", "automation": "auto"},
            {"code": "beijing_tianjin_partner_check", "requirement": "京津冀重点产业成果转化项目未有北京或天津合作单位。", "automation": "requires_data", "reason": "当前未接入合作单位注册地区"},
            {"code": "cluster_region_check", "requirement": "特色产业集群成果转化与技术攻关项目申报单位注册地非集群所在区域。", "automation": "requires_data", "reason": "当前未接入集群项目标识和单位注册地区"},
            {"code": "execution_period_limit", "requirement": "执行期超过2年。", "automation": "auto"},
            {"code": "duplicate_submission_check", "requirement": "项目重复申报、多头申报。", "automation": "auto"},
            {"code": "other_policy_compliance", "requirement": "其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题。", "automation": "manual", "reason": "需人工综合复核申报指南和管理办法"},
        ],
    },
    "basic_research": {
        "label": "基础研究项目",
        "guide_names": ["基础研究项目"],
        "required_project_fields": [
            "project_id",
            "project_type",
            "project_name",
            "applicant_unit",
            "execution_period_years",
            "year",
        ],
        "required_doc_kinds": ["commitment_letter"],
        "conditional_doc_rules": [
            {"when": "has_clinical_research", "doc_kind": "ethics_approval", "reason": "涉及临床研究时需提供伦理审查意见"},
            {"when": "has_special_industry_requirement", "doc_kind": "industry_permit", "reason": "涉及特种行业时需提供行业准入资格或许可"},
            {"when": "has_biosafety_activity", "doc_kind": "biosafety_commitment", "reason": "涉及生物安全活动时需提供生物安全承诺书"},
            {"when": "has_cooperation_unit", "doc_kind": "cooperation_agreement", "reason": "存在合作单位时需提供合作协议"},
        ],
        "project_rules": [
            "required_project_fields",
            "registered_date_limit",
            "project_leader_age_check",
            "budget_forbidden_expense_check",
            "performance_metric_count_check",
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
            "policy_review_points_check",
        ],
        "constraints": {
            "registered_after": "2025-01-01",
            "max_execution_period_years": 3,
        },
        "policy_review_points": [
            {"code": "external_status_check", "requirement": "项目存在科研失信、社会失信。", "automation": "auto"},
            {"code": "duplicate_submission_check", "requirement": "项目重复申报、多头申报。", "automation": "auto"},
            {"code": "registered_date_limit", "requirement": "单位注册时间在2025年1月1日后。", "automation": "requires_data", "reason": "当前项目上下文未接入注册时间字段"},
            {"code": "ethics_approval_required", "requirement": "涉及开展临床研究，未提交伦理审查意见。", "automation": "auto"},
            {"code": "industry_permit_required", "requirement": "涉及安全生产等特种行业，未提供相关行业准入资格或许可佐证材料。", "automation": "auto"},
            {"code": "biosafety_commitment_required", "requirement": "涉及生物技术研究、开发、应用以及人类遗传资源相关活动的，未提交生物安全承诺书。", "automation": "auto"},
            {"code": "commitment_letter_required", "requirement": "未按要求提交承诺书。", "automation": "auto"},
            {"code": "cooperation_agreement_required", "requirement": "涉及合作单位，合作协议不完整不规范。", "automation": "requires_data", "reason": "当前只能基于附件存在性判断，尚未校验协议完整性"},
            {"code": "execution_period_limit", "requirement": "执行期超过3年。", "automation": "auto"},
            {"code": "other_policy_compliance", "requirement": "其他不符合计划项目管理办法、申报指南和其他有关规定要求的情况问题。", "automation": "manual", "reason": "需人工综合复核申报指南和管理办法"},
        ],
    },
}


DOC_KIND_TO_DOCUMENT_TYPE: Dict[str, str] = {
    "commitment_letter": "acceptance_report",
    "ethics_approval": "acceptance_report",
    "industry_permit": "acceptance_report",
    "biosafety_commitment": "acceptance_report",
    "cooperation_agreement": "acceptance_report",
    "recommendation_letter": "acceptance_report",
    "retrieval_report": "retrieval_report",
    "acceptance_certificate": "acceptance_report",
    "contributor_form": "award_contributor",
    "patent_certificate": "patent_certificate",
    "award_certificate": "award_certificate",
    "base_staff_proof": "acceptance_report",
    "business_license": "acceptance_report",
    "research_paper": "acceptance_report",
}


ATTACHMENT_KIND_CONFIG: Dict[str, Dict[str, str]] = {
    "commitment_letter": {
        "label": "承诺书",
        "description": "项目申报承诺书、科研诚信承诺书、真实性承诺书等，通常包含签字盖章承诺内容。",
    },
    "ethics_approval": {
        "label": "伦理审查意见",
        "description": "伦理委员会审批意见、伦理批件、伦理审查表等。",
    },
    "industry_permit": {
        "label": "行业准入许可",
        "description": "特种行业资质、行政许可、经营许可、生产许可等。",
    },
    "biosafety_commitment": {
        "label": "生物安全承诺书",
        "description": "涉及生物安全、生物样本、实验安全相关的承诺书或说明材料。",
    },
    "cooperation_agreement": {
        "label": "合作协议",
        "description": "合作协议、合作合同、联合申报协议、任务分工协议等。",
    },
    "recommendation_letter": {
        "label": "推荐函",
        "description": "合作方科技管理部门推荐函、推荐意见函、推荐说明等。",
    },
    "retrieval_report": {
        "label": "检索报告",
        "description": "科技查新报告、文献检索报告、成果检索证明等。",
    },
    "acceptance_certificate": {
        "label": "验收证明",
        "description": "项目验收证书、验收证明、验收结论等。",
    },
    "contributor_form": {
        "label": "完成人情况表",
        "description": "主要完成人情况表、完成人排序说明、成员信息表等。",
    },
    "patent_certificate": {
        "label": "专利证书",
        "description": "专利证书、专利授权通知、知识产权证书等。",
    },
    "award_certificate": {
        "label": "获奖证书",
        "description": "奖励证书、荣誉证书、表彰证明等。",
    },
    "base_staff_proof": {
        "label": "基地固定人员证明",
        "description": "创新基地固定人员名单、聘任证明、人员证明材料等。",
    },
    "business_license": {
        "label": "营业执照（统一社会信用代码证）",
        "description": "营业执照、统一社会信用代码证、事业单位法人证书等主体资格证明材料。",
    },
    "research_paper": {
        "label": "科研论文（发表论文）",
        "description": "已发表或已录用的学术论文、Research Article、期刊论文首页及全文等成果论文材料。",
    },
    "other_supporting_material": {
        "label": "其他支撑材料",
        "description": "确属项目附件，但不属于上述重点材料类别的其他附件。",
    },
    "unknown_attachment": {
        "label": "无法识别",
        "description": "仅在依据现有内容无法可靠判断材料类别时使用。",
    },
}


ATTACHMENT_DOC_KIND_ALIASES: Dict[str, str] = {
    "承诺书": "commitment_letter",
    "伦理审查意见": "ethics_approval",
    "伦理审批": "ethics_approval",
    "行业准入许可": "industry_permit",
    "许可": "industry_permit",
    "生物安全承诺书": "biosafety_commitment",
    "合作协议": "cooperation_agreement",
    "推荐函": "recommendation_letter",
    "检索报告": "retrieval_report",
    "验收证明": "acceptance_certificate",
    "完成人情况表": "contributor_form",
    "专利证书": "patent_certificate",
    "获奖证书": "award_certificate",
    "基地固定人员证明": "base_staff_proof",
    "营业执照": "business_license",
    "营业执照（统一社会信用代码证）": "business_license",
    "统一社会信用代码证": "business_license",
    "事业单位法人证书": "business_license",
    "法人证书": "business_license",
    "科研论文": "research_paper",
    "发表论文": "research_paper",
    "期刊论文": "research_paper",
    "学术论文": "research_paper",
    "research article": "research_paper",
    "journal article": "research_paper",
    "paper": "research_paper",
    "其他支撑材料": "other_supporting_material",
    "其他材料": "other_supporting_material",
    "无法识别": "unknown_attachment",
    "unknown": "unknown_attachment",
}


ATTACHMENT_FILENAME_HINTS: List[tuple[str, str]] = [
    ("承诺书", "commitment_letter"),
    ("伦理", "ethics_approval"),
    ("合作协议", "cooperation_agreement"),
    ("协议", "cooperation_agreement"),
    ("推荐函", "recommendation_letter"),
    ("推荐信", "recommendation_letter"),
    ("检索", "retrieval_report"),
    ("查新", "retrieval_report"),
    ("专利", "patent_certificate"),
    ("主要完成人", "contributor_form"),
    ("完成人情况", "contributor_form"),
    ("证书", "award_certificate"),
    ("许可", "industry_permit"),
    ("生物安全", "biosafety_commitment"),
    ("固定人员", "base_staff_proof"),
    ("营业执照", "business_license"),
    ("统一社会信用代码", "business_license"),
    ("法人证书", "business_license"),
    ("论文", "research_paper"),
    ("research article", "research_paper"),
    ("journal article", "research_paper"),
    ("article", "research_paper"),
    ("doi", "research_paper"),
]


DEFAULT_ATTACHMENT_REVIEW_DOC_KINDS: List[str] = [
    "commitment_letter",
    "recommendation_letter",
]


GUIDE_NAME_TO_PROJECT_TYPE: Dict[str, str] = {
    guide_name: project_type
    for project_type, config in PROJECT_CONFIG.items()
    for guide_name in config.get("guide_names", [])
}


def get_project_types() -> List[str]:
    """获取所有项目类型"""
    return list(PROJECT_CONFIG.keys())


def get_project_config(project_type: str) -> Optional[Dict[str, Any]]:
    """获取项目配置"""
    return PROJECT_CONFIG.get(project_type)


def get_policy_review_points(project_type: str) -> List[Dict[str, Any]]:
    """获取项目类型对应的形式审查要点矩阵"""
    return list(PROJECT_CONFIG.get(project_type, {}).get("policy_review_points", []))


def get_effective_policy_review_points(project_type: str, notice_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """获取项目类型生效的形式审查要点（基础规则 + 通知规则）"""
    base_points = get_policy_review_points(project_type)
    return get_merged_policy_review_points(project_type, base_points, notice_context or {})


def get_project_label(project_type: str) -> str:
    """获取项目类型标签"""
    return PROJECT_CONFIG.get(project_type, {}).get("label", project_type)


def get_attachment_kind_definitions(include_unknown: bool = True) -> List[Dict[str, str]]:
    """获取附件预定义类别"""
    doc_kinds = [
        doc_kind
        for doc_kind in ATTACHMENT_KIND_CONFIG
        if include_unknown or doc_kind != "unknown_attachment"
    ]
    return [
        {
            "doc_kind": doc_kind,
            "label": ATTACHMENT_KIND_CONFIG[doc_kind]["label"],
            "description": ATTACHMENT_KIND_CONFIG[doc_kind]["description"],
        }
        for doc_kind in doc_kinds
    ]


def normalize_attachment_doc_kind(value: str) -> str:
    """归一化附件类别编码"""
    text = str(value or "").strip()
    if not text:
        return "unknown_attachment"
    lowered = text.lower()
    if lowered in ATTACHMENT_KIND_CONFIG:
        return lowered
    if text in ATTACHMENT_KIND_CONFIG:
        return text
    return ATTACHMENT_DOC_KIND_ALIASES.get(text, "unknown_attachment")


def get_attachment_review_doc_kinds() -> List[str]:
    """获取允许进入旧附件审查链的附件类别"""
    raw = os.getenv("REVIEW_ATTACHMENT_REVIEW_DOC_KINDS", "")
    if not raw.strip():
        return DEFAULT_ATTACHMENT_REVIEW_DOC_KINDS.copy()

    values = []
    for item in raw.split(","):
        doc_kind = normalize_attachment_doc_kind(item)
        if doc_kind != "unknown_attachment":
            values.append(doc_kind)
    return values or DEFAULT_ATTACHMENT_REVIEW_DOC_KINDS.copy()


def resolve_project_type(guide_name: str) -> str:
    """根据指南名称解析项目类型"""
    normalized_name = _normalize_guide_name(guide_name)
    if normalized_name in GUIDE_NAME_TO_PROJECT_TYPE:
        return GUIDE_NAME_TO_PROJECT_TYPE[normalized_name]
    for known_name, project_type in GUIDE_NAME_TO_PROJECT_TYPE.items():
        if known_name and known_name in normalized_name:
            return project_type
    return "unknown"


def _normalize_guide_name(guide_name: str) -> str:
    """归一化指南名称，去除编号前缀和多余分隔符"""
    text = str(guide_name or "").strip()
    text = re.sub(r"^[0-9A-Za-z]+[-_—－]+", "", text)
    return text.strip()


def resolve_document_type(doc_kind: str, explicit_document_type: Optional[str] = None) -> str:
    """根据附件类型解析附件级审查类型"""
    if explicit_document_type:
        return explicit_document_type
    return DOC_KIND_TO_DOCUMENT_TYPE.get(doc_kind, "unknown")
