"""项目级形式审查配置"""
from typing import Any, Dict, List, Optional


PROJECT_CONFIG: Dict[str, Dict[str, Any]] = {
    "regional_innovation": {
        "label": "区域创新体系建设项目",
        "guide_names": ["区域创新体系建设项目"],
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
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
        ],
        "constraints": {
            "max_execution_period_years": 2,
        },
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
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
        ],
        "constraints": {
            "max_execution_period_years": 2,
        },
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
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "applicant_unit_type_check",
            "external_status_check",
        ],
        "constraints": {
            "max_execution_period_years": 2,
            "allowed_applicant_unit_types": ["enterprise"],
        },
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
            "required_attachments",
            "conditional_attachments",
            "execution_period_limit",
            "external_status_check",
        ],
        "constraints": {
            "max_execution_period_years": 3,
        },
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
}


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


def get_project_label(project_type: str) -> str:
    """获取项目类型标签"""
    return PROJECT_CONFIG.get(project_type, {}).get("label", project_type)


def resolve_project_type(guide_name: str) -> str:
    """根据指南名称解析项目类型"""
    if guide_name in GUIDE_NAME_TO_PROJECT_TYPE:
        return GUIDE_NAME_TO_PROJECT_TYPE[guide_name]
    for known_name, project_type in GUIDE_NAME_TO_PROJECT_TYPE.items():
        if known_name and known_name in guide_name:
            return project_type
    return "unknown"


def resolve_document_type(doc_kind: str, explicit_document_type: Optional[str] = None) -> str:
    """根据附件类型解析附件级审查类型"""
    if explicit_document_type:
        return explicit_document_type
    return DOC_KIND_TO_DOCUMENT_TYPE.get(doc_kind, "unknown")
