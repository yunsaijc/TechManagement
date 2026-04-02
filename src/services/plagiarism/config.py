"""查重配置。

定义不同文档类型的 section 配置，以及默认 corpus 路径。
"""
from pathlib import Path
from typing import Dict, List, Any


PLAGIARISM_DEFAULT_CORPUS_PATH = Path("/home/tdkx/workspace/tech/data/corpus_local/sbs_5000")
PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR = Path("/home/tdkx/workspace/tech/data/plagiarism/local_ingest")
PLAGIARISM_DEFAULT_INDEX_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_index.json"
PLAGIARISM_DEFAULT_SQLITE_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_index.db"
PLAGIARISM_DEFAULT_MANIFEST_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_manifest.json"
PLAGIARISM_DEFAULT_CHECKPOINT_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_refresh_checkpoint.json"


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
        "description": "适用于当前项目申报书正文查重范围",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        # primary-only：仅抽取用户确认的正文检测区
        # 范围：
        # 项目立项背景及意义
        # 项目简介
        # 一、项目实施内容
        # 二、项目实施对受援地产业或相关行业领域带动促进作用
        # 三、项目实施预期技术指标及创新点
        # 四、项目实施预期经济社会效益
        # 到“五、项目实施的预期绩效目标”标题截止（该标题及后续不纳入检测）
        "primary_scope": {
            "start_pattern": r"项目立项背景及意义",
            "end_pattern": r"五\s*[、\.．]\s*项目实施的预期绩效目标",
        },
        "sections": [
            {
                "name": "项目立项背景及意义",
                "start_pattern": r"项目立项背景及意义",
                "end_pattern": r"项目简介",
            },
            {
                "name": "项目简介",
                "start_pattern": r"项目简介",
                "end_pattern": r"第一部分\s*项目实施内容及目标",
            },
            {
                "name": "一、项目实施内容",
                "start_pattern": r"一\s*[、\.．]\s*项目实施内容",
                "end_pattern": r"二\s*[、\.．]\s*项目实施对受援地产业或相关行业领域带动促进作用",
            },
            {
                "name": "二、项目实施对受援地产业或相关行业领域带动促进作用",
                "start_pattern": r"二\s*[、\.．]\s*项目实施对受援地产业或相关行业领域带动促进作用",
                "end_pattern": r"三\s*[、\.．]\s*项目实施预期技术指标及创新点",
            },
            {
                "name": "三、项目实施预期技术指标及创新点",
                "start_pattern": r"三\s*[、\.．]\s*项目实施预期技术指标及创新点",
                "end_pattern": r"四\s*[、\.．]\s*项目实施预期经济社会效益",
            },
            {
                "name": "四、项目实施预期经济社会效益",
                "start_pattern": r"四\s*[、\.．]\s*项目实施预期经济社会效益",
                "end_pattern": r"五\s*[、\.．]\s*项目实施的预期绩效目标",
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
