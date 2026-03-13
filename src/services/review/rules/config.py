"""
规则配置

定义不同文档类型对应的检查规则。
"""
from typing import List

# 不同文档类型对应的规则列表
RULES_BY_DOCUMENT: dict[str, List[str]] = {
    "retrieval_report": [
        "stamp_check",        # 盖章检查
        "signature_check",    # 签字检查
        "stamp_consistency", # 盖章与单位一致性
        "completeness",     # 完整性检查
    ],
    "paper": [  # 论文
        "title_check",
        "author_check",
    ],
    "acceptance_report": [
        "stamp_check",
        "signature_check",
        "prerequisite",     # 前置条件
    ],
    "patent_certificate": [
        "stamp_check",
        "signature_check",
    ],
    "license": [
        "stamp_check",
        "signature_check",
    ],
    "contract": [
        "stamp_check",
        "signature_check",
    ],
    "award_certificate": [
        "stamp_check",
        "signature_check",
    ],
}


def load_rules(document_type: str) -> List[str]:
    """根据文档类型加载对应规则列表
    
    Args:
        document_type: 文档类型
        
    Returns:
        规则名称列表
    """
    return RULES_BY_DOCUMENT.get(document_type, [])


def get_all_document_types() -> List[str]:
    """获取所有支持的文档类型"""
    return list(RULES_BY_DOCUMENT.keys())
