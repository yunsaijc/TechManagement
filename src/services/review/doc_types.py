"""统一文档类型注册表。

将项目平台附件类型和奖励平台单文档类型统一到一套 ``doc_type`` 体系中。
"""
from __future__ import annotations

from typing import Any, Dict, List


DOC_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "project_commitment_letter": {
        "platform": "project",
        "zh_label": "承诺书",
        "en_label": "Commitment Letter",
        "aliases": ["commitment_letter", "承诺书"],
        "legacy_doc_kind": "commitment_letter",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "项目申报承诺书、科研诚信承诺书、真实性承诺书等。",
        "remarks": "项目平台附件",
    },
    "project_ethics_approval": {
        "platform": "project",
        "zh_label": "伦理审查意见",
        "en_label": "Ethics Approval",
        "aliases": ["ethics_approval", "伦理审查意见", "伦理审批"],
        "legacy_doc_kind": "ethics_approval",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "伦理委员会审批意见、伦理批件、伦理审查表等。",
        "remarks": "项目平台附件",
    },
    "project_industry_permit": {
        "platform": "project",
        "zh_label": "行业准入许可",
        "en_label": "Industry Permit",
        "aliases": ["industry_permit", "行业准入许可", "许可"],
        "legacy_doc_kind": "industry_permit",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "特种行业资质、行政许可、经营许可、生产许可等。",
        "remarks": "项目平台附件",
    },
    "project_biosafety_commitment": {
        "platform": "project",
        "zh_label": "生物安全承诺书",
        "en_label": "Biosafety Commitment",
        "aliases": ["biosafety_commitment", "生物安全承诺书"],
        "legacy_doc_kind": "biosafety_commitment",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "涉及生物安全、生物样本、实验安全相关的承诺书或说明材料。",
        "remarks": "项目平台附件",
    },
    "project_cooperation_agreement": {
        "platform": "project",
        "zh_label": "合作协议",
        "en_label": "Cooperation Agreement",
        "aliases": ["cooperation_agreement", "合作协议"],
        "legacy_doc_kind": "cooperation_agreement",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "合作协议、合作合同、联合申报协议、任务分工协议等。",
        "remarks": "项目平台附件",
    },
    "project_recommendation_letter": {
        "platform": "project",
        "zh_label": "推荐函",
        "en_label": "Recommendation Letter",
        "aliases": ["recommendation_letter", "推荐函", "推荐信"],
        "legacy_doc_kind": "recommendation_letter",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "合作方科技管理部门推荐函、推荐意见函、推荐说明等。",
        "remarks": "项目平台附件",
    },
    "project_retrieval_report": {
        "platform": "project",
        "zh_label": "检索报告",
        "en_label": "Retrieval Report",
        "aliases": ["retrieval_report", "检索报告", "查新报告"],
        "legacy_doc_kind": "retrieval_report",
        "rules": ["stamp", "signature", "prerequisite", "retrieval_report_completeness"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "科技查新报告、文献检索报告、成果检索证明等。",
        "remarks": "项目平台附件",
    },
    "project_acceptance_certificate": {
        "platform": "project",
        "zh_label": "验收证明",
        "en_label": "Acceptance Certificate",
        "aliases": ["acceptance_certificate", "验收证明"],
        "legacy_doc_kind": "acceptance_certificate",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "项目验收证书、验收证明、验收结论等。",
        "remarks": "项目平台附件",
    },
    "project_patent_certificate": {
        "platform": "project",
        "zh_label": "专利证书",
        "en_label": "Patent Certificate",
        "aliases": ["project_patent_certificate"],
        "legacy_doc_kind": "patent_certificate",
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": ["专利号", "发明人", "专利权人"],
        "description": "专利证书、专利授权通知、知识产权证书等。",
        "remarks": "项目平台附件",
    },
    "reward_patent_certificate": {
        "platform": "reward",
        "zh_label": "专利证书",
        "en_label": "Patent Certificate",
        "aliases": ["patent_certificate", "专利证书"],
        "legacy_doc_kind": "patent_certificate",
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": ["专利号", "发明人", "专利权人"],
        "description": "专利证书、专利授权通知、知识产权证书等。",
        "remarks": "奖励平台材料",
    },
    "reward_award_certificate": {
        "platform": "reward",
        "zh_label": "奖励证书",
        "en_label": "Award Certificate",
        "aliases": ["award_certificate", "奖励证书", "获奖证书"],
        "legacy_doc_kind": "award_certificate",
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "奖励证书、荣誉证书、表彰证明等。",
        "remarks": "奖励平台材料",
    },
    "tjdwyj": {
        "platform": "reward",
        "zh_label": "提名单位意见表",
        "en_label": "Nomination Unit Opinion Form",
        "aliases": ["10.1", "提名单位意见表", "tjdwyj"],
        "legacy_doc_kind": "tjdwyj",
        "rules": [
            "stamp",
            "nomination_unit_stamp_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "奖励项目提名单位意见表。",
        "remarks": "奖励平台材料",
    },
    "gzdwyj": {
        "platform": "reward",
        "zh_label": "候选人工作单位意见",
        "en_label": "Candidate Work Unit Opinion Form",
        "aliases": ["10.2", "候选人工作单位意见", "gzdwyj"],
        "legacy_doc_kind": "gzdwyj",
        "rules": [
            "stamp",
            "candidate_work_unit_stamp_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "奖励项目候选人工作单位意见页。",
        "remarks": "奖励平台材料",
    },
    "wcr": {
        "platform": "reward",
        "zh_label": "主要完成人情况表",
        "en_label": "Award Contributor Form",
        "aliases": [
            "10.3",
            "award_contributor",
            "contributor_form",
            "reward_award_contributor_form",
            "完成人情况表",
            "主要完成人情况表",
            "wcr",
        ],
        "legacy_doc_kind": "wcr",
        "rules": [
            "signature",
            "stamp",
            "award_contributor_signature_consistency",
            "award_contributor_work_unit_stamp_consistency",
            "award_contributor_completion_unit_stamp_consistency",
            "contributor_db_name_consistency",
            "contributor_db_work_unit_consistency",
            "contributor_db_completion_unit_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": ["姓名", "工作单位", "完成单位", "技术职称", "学历"],
        "auto_llm_analysis": True,
        "description": "奖励申报中的主要完成人情况表。",
        "remarks": "奖励平台材料",
    },
    "wjwcr": {
        "platform": "reward",
        "zh_label": "外籍主要完成人情况表",
        "en_label": "Foreign Award Contributor Form",
        "aliases": ["外籍主要完成人情况表", "wjwcr"],
        "legacy_doc_kind": "wjwcr",
        "rules": [
            "signature",
            "stamp",
            "award_contributor_signature_consistency",
            "award_contributor_work_unit_stamp_consistency",
            "award_contributor_completion_unit_stamp_consistency",
            "contributor_db_name_consistency",
            "contributor_db_work_unit_consistency",
            "contributor_db_completion_unit_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": ["姓名", "工作单位", "完成单位", "技术职称", "学历"],
        "auto_llm_analysis": True,
        "description": "奖励申报中的外籍主要完成人情况表。",
        "remarks": "奖励平台材料",
    },
    "wcdw": {
        "platform": "reward",
        "zh_label": "主要完成单位情况表",
        "en_label": "Completion Unit Form",
        "aliases": ["10.4", "主要完成单位情况表", "wcdw"],
        "legacy_doc_kind": "wcdw",
        "rules": [
            "stamp",
            "completion_unit_name_consistency",
            "completion_unit_legal_representative_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": ["单位名称", "法定代表人"],
        "auto_llm_analysis": True,
        "description": "奖励申报中的主要完成单位情况表。",
        "remarks": "奖励平台材料",
    },
    "hzdw": {
        "platform": "reward",
        "zh_label": "河北省内主要合作单位情况表",
        "en_label": "Cooperation Unit Form",
        "aliases": ["10.5", "河北省内主要合作单位情况表", "hzdw"],
        "legacy_doc_kind": "hzdw",
        "rules": [
            "stamp",
            "cooperation_unit_name_consistency",
        ],
        "llm_rules": [],
        "llm_extract_fields": ["单位名称"],
        "auto_llm_analysis": True,
        "description": "奖励申报中的河北省内主要合作单位情况表。",
        "remarks": "奖励平台材料",
    },
    "reward_acceptance_report": {
        "platform": "reward",
        "zh_label": "验收报告",
        "en_label": "Acceptance Report",
        "aliases": ["acceptance_report", "验收报告"],
        "legacy_doc_kind": "acceptance_certificate",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "验收报告、验收结论等。",
        "remarks": "兼容旧单文档类型",
    },
    "reward_research_paper": {
        "platform": "reward",
        "zh_label": "论文",
        "en_label": "Paper",
        "aliases": ["paper", "论文"],
        "legacy_doc_kind": "research_paper",
        "rules": ["title_check", "author_check"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "论文材料。",
        "remarks": "兼容旧单文档类型",
    },
    "project_base_staff_proof": {
        "platform": "project",
        "zh_label": "基地固定人员证明",
        "en_label": "Base Staff Proof",
        "aliases": ["base_staff_proof", "基地固定人员证明"],
        "legacy_doc_kind": "base_staff_proof",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "创新基地固定人员名单、聘任证明、人员证明材料等。",
        "remarks": "项目平台附件",
    },
    "project_business_license": {
        "platform": "project",
        "zh_label": "营业执照（统一社会信用代码证）",
        "en_label": "Business License",
        "aliases": ["business_license", "营业执照", "营业执照（统一社会信用代码证）", "统一社会信用代码证", "法人证书"],
        "legacy_doc_kind": "business_license",
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "营业执照、统一社会信用代码证、事业单位法人证书等。",
        "remarks": "项目平台附件",
    },
    "project_research_paper": {
        "platform": "project",
        "zh_label": "科研论文",
        "en_label": "Research Paper",
        "aliases": ["research_paper", "科研论文", "发表论文", "学术论文"],
        "legacy_doc_kind": "research_paper",
        "rules": ["title_check", "author_check"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "已发表或已录用的学术论文材料。",
        "remarks": "项目平台附件",
    },
    "project_other_supporting_material": {
        "platform": "project",
        "zh_label": "其他支撑材料",
        "en_label": "Other Supporting Material",
        "aliases": ["other_supporting_material", "其他支撑材料", "其他材料"],
        "legacy_doc_kind": "other_supporting_material",
        "rules": [],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "不属于重点材料类别的其他附件。",
        "remarks": "项目平台附件",
    },
    "project_unknown_attachment": {
        "platform": "project",
        "zh_label": "无法识别附件",
        "en_label": "Unknown Attachment",
        "aliases": ["unknown_attachment", "无法识别"],
        "legacy_doc_kind": "unknown_attachment",
        "rules": [],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "仅在依据现有内容无法可靠判断材料类别时使用。",
        "remarks": "项目平台附件",
    },
    "unknown": {
        "platform": "shared",
        "zh_label": "未知",
        "en_label": "Unknown",
        "aliases": ["未知"],
        "legacy_doc_kind": "unknown_attachment",
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": [],
        "description": "未知类型。",
        "remarks": "兜底类型",
    },
}


_DOC_TYPE_ALIAS_MAP: Dict[str, str] = {}
for _doc_type, _config in DOC_TYPE_REGISTRY.items():
    _DOC_TYPE_ALIAS_MAP[_doc_type.lower()] = _doc_type
    for _alias in _config.get("aliases", []):
        alias = str(_alias or "").strip()
        if alias:
            _DOC_TYPE_ALIAS_MAP[alias.lower()] = _doc_type


def normalize_doc_type(value: str, default: str = "unknown") -> str:
    """将输入的 doc_type / 旧 document_type / 旧 doc_kind 归一到统一 doc_type。"""
    text = str(value or "").strip()
    if not text:
        return default
    return _DOC_TYPE_ALIAS_MAP.get(text.lower(), default)


def get_doc_type_config(value: str) -> Dict[str, Any]:
    """获取归一化后的 doc_type 配置。"""
    return DOC_TYPE_REGISTRY.get(normalize_doc_type(value), DOC_TYPE_REGISTRY["unknown"])


def get_doc_type_label(value: str) -> str:
    """获取中文标签。"""
    return str(get_doc_type_config(value).get("zh_label") or normalize_doc_type(value))


def get_doc_type_description(value: str) -> str:
    """获取描述。"""
    return str(get_doc_type_config(value).get("description") or "")


def get_doc_type_platform(value: str) -> str:
    """获取所属平台。"""
    return str(get_doc_type_config(value).get("platform") or "")


def list_supported_doc_types() -> List[str]:
    """列出所有规范 doc_type。"""
    return list(DOC_TYPE_REGISTRY.keys())


def doc_type_to_legacy_doc_kind(value: str) -> str:
    """将规范 doc_type 转回旧附件类别编码。"""
    config = get_doc_type_config(value)
    return str(config.get("legacy_doc_kind") or "")
