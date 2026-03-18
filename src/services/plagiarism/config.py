"""查重 section 配置

定义不同文档类型需要查重的区域配置。
"""
from typing import Dict, List, Any


PLAGIARISM_SECTION_CONFIG: Dict[str, Dict[str, Any]] = {
    "default": {
        "name": "默认配置",
        "description": "适用于项目申报书类文档",
        "sections": [
            {
                "name": "项目立项背景及意义",
                "start_pattern": r"项目立项背景及意义",
                "end_pattern": r"项目简介",
            },
            {
                "name": "项目简介",
                "start_pattern": r"项目简介",
                "end_pattern": r"第一部分 项目实施内容及目标",
            },
            {
                "name": "第一部分 项目实施内容及目标",
                "start_pattern": r"第一部分\s*项目实施内容及目标",
                "end_pattern": r"第二部分",
            },
            {
                "name": "第二部分 申报单位及合作单位基础",
                "start_pattern": r"第二部分\s*申报单位及合作单位基础",
                "end_pattern": r"第三部分",
            },
            {
                "name": "第三部分 项目实施计划及保障措施和风险分析",
                "start_pattern": r"第三部分\s*项目实施计划及保障措施和风险分析",
                "end_pattern": None,
            },
        ]
    },
}


def get_section_config(doc_type: str = "default") -> Dict[str, Any]:
    """获取指定文档类型的 section 配置
    
    Args:
        doc_type: 文档类型，默认 "default"
        
    Returns:
        section 配置字典
    """
    return PLAGIARISM_SECTION_CONFIG.get(doc_type, PLAGIARISM_SECTION_CONFIG["default"])


def get_all_doc_types() -> List[str]:
    """获取所有支持的文档类型"""
    return list(PLAGIARISM_SECTION_CONFIG.keys())
