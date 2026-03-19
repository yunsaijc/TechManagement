"""查重 section 配置

定义不同文档类型需要查重的区域配置。
"""
from typing import Dict, List, Any


# 白名单模板短语（不计入重复）
WHITELIST_TEMPLATE_PATTERNS: List[str] = [
    # 政策文件常用开头
    r"为了认真贯彻落实.*?要求",
    r"根据.*?规定",
    r"特制定本.*?",
    r"本办法适用于",
    r"现将.*?情况汇报如下",
    # 金额模板
    r"\d+[万千百亿].*?元",
    r"^\d+\.\d+[^\w]",
]

# 标题行检测模式
HEADING_PATTERNS: List[str] = [
    r"^第[一二三四五六七八九十百]+[章节部分篇]",  # 第一章、第二部分
    r"^[一二三四五六七八九十]、",  # 一、二、三
    r"^\d+\.\d+",  # 1.2.3
    r"^[A-Z][\.、]",  # A. B. C.
    r"^\([a-zA-Z0-9一二三四五六七八九十]+\)",  # (1) (一)
    r"^【[^】]+】",  # 【标题】
    r"^\d+[、\.．:：]\s*\S+",  # 1、项目组织实施机制
]

# 表格相关模式
TABLE_PATTERNS: List[str] = [
    r"^\[表格行\d+\]",  # [表格行1]
    r"^\s*[\u4e00-\u9fa5]+\s*\|\s*[\u4e00-\u9fa5]+",  # "项目 | 金额"
    r"^表格序号",  # 表格表头
]


PLAGIARISM_SECTION_CONFIG: Dict[str, Dict[str, Any]] = {
    "default": {
        "name": "默认配置",
        "description": "适用于项目申报书类文档",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
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


def get_whitelist_patterns(doc_type: str = "default") -> List[str]:
    """获取白名单模板模式"""
    config = get_section_config(doc_type)
    return config.get("whitelist_patterns", WHITELIST_TEMPLATE_PATTERNS)
