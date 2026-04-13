"""
文档类型配置

定义不同文档类型的规则和 LLM 提取配置。
"""
from typing import Any, Dict, List

# 文档类型统一配置
DOCUMENT_CONFIG: Dict[str, Dict[str, Any]] = {
    "retrieval_report": {
        "labels": ["检索报告"],
        "rules": ["stamp", "signature", "prerequisite", "retrieval_report_completeness"],
        "llm_rules": [],
        "llm_extract_fields": [],
    },
    "paper": {
        "labels": ["论文"],
        "rules": ["title_check", "author_check"],
        "llm_rules": [],
        "llm_extract_fields": [],
    },
    "acceptance_report": {
        "labels": ["验收报告"],
        "rules": ["stamp", "signature", "prerequisite"],
        "llm_rules": [],
        "llm_extract_fields": [],
    },
    "patent_certificate": {
        "labels": ["专利证书"],
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": ["专利号", "发明人", "专利权人"],
    },
    "award_certificate": {
        "labels": ["奖励证书"],
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": [],
    },
    "award_contributor": {
        "labels": ["奖励-主要完成人情况表", "主要完成人情况表"],
        "rules": ["signature", "stamp", "work_unit_consistency"],
        "llm_rules": ["signature_name_consistency"],
        "llm_extract_fields": ["姓名", "工作单位", "完成单位", "技术职称", "学历"],
    },
    "unknown": {
        "labels": ["未知"],
        "rules": ["signature", "stamp"],
        "llm_rules": [],
        "llm_extract_fields": [],
    },
}


def get_labels(document_type: str) -> List[str]:
    """获取文档类型的中文名称列表"""
    return DOCUMENT_CONFIG.get(document_type, {}).get("labels", [])


def load_rules(document_type: str) -> List[str]:
    """根据文档类型加载规则列表"""
    return DOCUMENT_CONFIG.get(document_type, {}).get("rules", [])


def load_llm_extract_fields(document_type: str) -> List[str]:
    """根据文档类型加载 LLM 提取字段列表"""
    return DOCUMENT_CONFIG.get(document_type, {}).get("llm_extract_fields", [])


def get_all_document_types() -> List[str]:
    """获取所有支持的文档类型"""
    return list(DOCUMENT_CONFIG.keys())


def get_type_labels_for_llm() -> str:
    """获取所有文档类型的中文名称，用于 LLM 分类 prompt"""
    labels_list = []
    for doc_type, config in DOCUMENT_CONFIG.items():
        if doc_type != "unknown":
            labels_list.extend(config.get("labels", []))
    # 去重
    unique_labels = list(dict.fromkeys(labels_list))
    return "\n".join(f"- {label}" for label in unique_labels)


# 向后兼容：保持原有的 RULES_BY_DOCUMENT
RULES_BY_DOCUMENT = {k: v.get("rules", []) for k, v in DOCUMENT_CONFIG.items()}
