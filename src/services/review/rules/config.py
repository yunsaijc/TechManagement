"""
统一 doc_type 审查配置。

配置源使用统一 ``doc_type`` 注册表，旧 ``document_type`` / ``doc_kind`` 会先归一再读取。
"""
from typing import Any, Dict, List

from src.services.review.doc_types import DOC_TYPE_REGISTRY, get_doc_type_config, normalize_doc_type


DOCUMENT_CONFIG: Dict[str, Dict[str, Any]] = {
    doc_type: {
        "labels": [config["zh_label"], *config.get("aliases", [])],
        "rules": list(config.get("rules", [])),
        "llm_rules": list(config.get("llm_rules", [])),
        "llm_extract_fields": list(config.get("llm_extract_fields", [])),
        "auto_llm_analysis": bool(config.get("auto_llm_analysis", False)),
        "platform": config.get("platform", ""),
        "description": config.get("description", ""),
        "remarks": config.get("remarks", ""),
    }
    for doc_type, config in DOC_TYPE_REGISTRY.items()
}


def get_labels(doc_type: str) -> List[str]:
    """获取文档类型的标签列表。"""
    return DOCUMENT_CONFIG.get(normalize_doc_type(doc_type), {}).get("labels", [])


def load_rules(doc_type: str) -> List[str]:
    """根据统一 doc_type 加载规则列表。"""
    return DOCUMENT_CONFIG.get(normalize_doc_type(doc_type), {}).get("rules", [])


def load_llm_extract_fields(doc_type: str) -> List[str]:
    """根据统一 doc_type 加载 LLM 提取字段列表。"""
    return DOCUMENT_CONFIG.get(normalize_doc_type(doc_type), {}).get("llm_extract_fields", [])


def get_all_document_types() -> List[str]:
    """获取所有支持的规范 doc_type。"""
    return list(DOCUMENT_CONFIG.keys())


def get_type_labels_for_llm() -> str:
    """获取所有文档类型中文名称，用于 LLM 分类 prompt。"""
    labels_list: List[str] = []
    for doc_type in DOCUMENT_CONFIG:
        if doc_type == "unknown":
            continue
        labels_list.append(str(get_doc_type_config(doc_type).get("zh_label", "")))
    unique_labels = [label for label in dict.fromkeys(labels_list) if label]
    return "\n".join(f"- {label}" for label in unique_labels)


RULES_BY_DOCUMENT = {k: v.get("rules", []) for k, v in DOCUMENT_CONFIG.items()}
