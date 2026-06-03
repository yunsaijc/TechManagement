"""查重配置。

定义不同文档类型的 section 配置，以及默认 corpus 路径。
"""
from pathlib import Path
from typing import Dict, List, Any


PLAGIARISM_DEFAULT_CORPUS_PATH = Path("/home/tdkx/workspace/tech/data/corpus_local/sbs_5000")
PLAGIARISM_DEFAULT_CORPUS_LOCAL_ROOT = Path("/home/tdkx/workspace/tech/data/corpus_local")
PLAGIARISM_DEFAULT_REMOTE_CORPUS_ROOT = Path("/mnt/remote_corpus")
PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR = Path("/home/tdkx/workspace/tech/data/plagiarism/local_ingest")
PLAGIARISM_KJJH_SOURCE_CORPUS_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism/kjjh_local_ingest_0422")
PLAGIARISM_KJJH_LOCAL_INGEST_DIR = Path("/home/tdkx/ljh/Tech/data/plagiarism/kjjh_local_ingest_runtime")
PLAGIARISM_KJJH_REMOTE_CORPUS_ROOT = Path("/mnt/remote_corpus")
PLAGIARISM_REWARD_CORPUS_ROOT = Path("/home/tdkx/workspace/tech/data/plagiarism/corpus_reward")
PLAGIARISM_REWARD_LOCAL_INGEST_DIR = Path("/home/tdkx/workspace/tech/data/plagiarism/reward_local_ingest")
PLAGIARISM_REWARD_FILE_LOCAL_INGEST_DIR = Path("/home/tdkx/workspace/tech/data/plagiarism/file_local_ingest")
PLAGIARISM_REWARD_UPLOAD_WINDOWS_ROOT = r"K:\FJCL\static\rpw"
PLAGIARISM_REWARD_UPLOAD_WINDOWS_YEAR_DIR_TEMPLATE = r"K:\FJCL\static\rpw\zmcl{year}\{xmtjbh}"
PLAGIARISM_REWARD_UPLOAD_WINDOWS_FILE_TEMPLATE = r"K:\FJCL\static\rpw\zmcl{year}\{xmtjbh}\{file_name}"
PLAGIARISM_REWARD_UPLOAD_ALLOWED_EXTENSIONS: tuple[str, ...] = (".doc", ".docx")
PLAGIARISM_DEFAULT_INDEX_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_index.json"
PLAGIARISM_DEFAULT_SQLITE_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_index.db"
PLAGIARISM_DEFAULT_MANIFEST_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_manifest.json"
PLAGIARISM_DEFAULT_CHECKPOINT_PATH = PLAGIARISM_DEFAULT_LOCAL_INGEST_DIR / "corpus_refresh_checkpoint.json"
PLAGIARISM_KJJH_INDEX_PATH = PLAGIARISM_KJJH_LOCAL_INGEST_DIR / "corpus_index.json"
PLAGIARISM_KJJH_SQLITE_PATH = PLAGIARISM_KJJH_LOCAL_INGEST_DIR / "corpus_index.db"
PLAGIARISM_KJJH_MANIFEST_PATH = PLAGIARISM_KJJH_LOCAL_INGEST_DIR / "corpus_manifest.json"
PLAGIARISM_KJJH_CHECKPOINT_PATH = PLAGIARISM_KJJH_LOCAL_INGEST_DIR / "corpus_refresh_checkpoint.json"
PLAGIARISM_REWARD_INDEX_PATH = PLAGIARISM_REWARD_LOCAL_INGEST_DIR / "reward_corpus_index.json"
PLAGIARISM_REWARD_SQLITE_PATH = PLAGIARISM_REWARD_LOCAL_INGEST_DIR / "reward_corpus_index.db"
PLAGIARISM_REWARD_MANIFEST_PATH = PLAGIARISM_REWARD_LOCAL_INGEST_DIR / "reward_corpus_manifest.json"
PLAGIARISM_REWARD_CHECKPOINT_PATH = PLAGIARISM_REWARD_LOCAL_INGEST_DIR / "reward_corpus_checkpoint.json"


PLAGIARISM_REWARD_DICT_CONFIG: Dict[str, Dict[str, str]] = {
    "xmjj": {
        "label": "项目简介",
        "table": "t_xm_jjlx",
        "field": "xmjj_html",
    },
    "cxd": {
        "label": "项目创新点",
        "table": "t_xm_cxd",
        "field": "jscxd",
        "order_field": "XH",
    },
    "zscq": {
        "label": "知识产权名称",
        "table": "t_xm_zscqml",
        "field": "sqxmmc",
        "order_field": "CQXH",
    },
    "jhmc": {
        "label": "主要计划项目名称",
        "table": "t_xm_ktlb",
        "field": "xmmc",
        "order_field": "XH",
    },
}

PLAGIARISM_REWARD_SCOPE_CONFIG: Dict[str, str] = {
    "dn": "当年已提名项目",
    "lshj": "历史获奖项目",
}

PLAGIARISM_REWARD_SCOPE_TABLE: str = "ps_xmpsxx"


def build_reward_upload_windows_dir(year: str, xmtjbh: str) -> str:
    """构造上传文件查重分支使用的 K 盘提名材料目录。"""
    return PLAGIARISM_REWARD_UPLOAD_WINDOWS_YEAR_DIR_TEMPLATE.format(
        year=str(year).strip(),
        xmtjbh=str(xmtjbh).strip(),
    )


def build_reward_upload_windows_file_path(year: str, xmtjbh: str, file_name: str) -> str:
    """构造上传文件查重分支使用的 K 盘提名材料文件路径。"""
    return PLAGIARISM_REWARD_UPLOAD_WINDOWS_FILE_TEMPLATE.format(
        year=str(year).strip(),
        xmtjbh=str(xmtjbh).strip(),
        file_name=str(file_name).strip(),
    )


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
    # 国家奖提名书固定模板标题/说明语（不计入有效重复）
    r"^\s*四[、，,\.．]\s*项目详细内容\s*[（(]\s*不超过6页\s*[）)]\s*$",
    r"^\s*[（(]\s*立项背景[、，,]\s*主要科技创新[、，,].*?知识产权及标准规范等情况[，,]\s*备注[：:]\s*总页数不超过6页\s*[）)]\s*$",
    r"^\s*一[、，,\.．]\s*立项背景\s*$",
]

PLAGIARISM_REWARD_FIELD_EXTRA_TEMPLATE_PATTERNS: List[str] = [
    r"^\s*(?:推广应用|示范应用|应用推广)[，,]?\s*累计实现新增(?:销售收入|营业收入|产值|利润|利税|税收|经济效益)",
    r"^\s*累计实现新增(?:销售收入|营业收入|产值|利润|利税|税收|经济效益)",
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

# file_local_ingest/zmcl2007–zmcl2025 国家奖提名材料：doc/docx 解析后常见「单行化」、表格占位
# （[表格表头n]）及历版标题差异。仅作 primary_scope 起点（勿依赖 (?m)^ 行首）。
_ZMCL_HEADING_SEP = r"[、\.\u3001．]"
_REWARD_ZMCL_PRIMARY_START_PATTERN: str = (
    r"(?:"
    r"[四4４]\s*" + _ZMCL_HEADING_SEP + r"\s*项目详细内容(?:\s*[（(][^）)]{0,120}[）)])?"
    r"|项目详细内容\s*[（(][^）)]{0,120}[）)]"
    r"|二\s*" + _ZMCL_HEADING_SEP + r"\s*(?:详细\s*)?科学技术内容"
    r"|二\s*" + _ZMCL_HEADING_SEP + r"\s*主要科技创新"
    r"|[2二２]\s*" + _ZMCL_HEADING_SEP + r"\s*详细\s*科学技术内容"
    r"|(?:[1一１]\s*" + _ZMCL_HEADING_SEP + r"\s*立项背景(?:与总体思路)?"
    r"(?:\s*[：:（(]|[（(][^）)]{0,60}[）)])?)"
    r"|（一）\s*立项背景"
    r"|[（(]一[））]\s*立项背景"
    r"|[（(]?一[）)]\s*(?:立项背景|总体思路|技术思路|技术方案)"
    r"|一\s*" + _ZMCL_HEADING_SEP + r"\s*(?:立项背景(?:与总体思路)?|总体思路|技术思路|技术方案)"
    r"|[1一１]\s*" + _ZMCL_HEADING_SEP + r"\s*(?:总体思路|技术思路|技术方案)"
    r"|[1-3]\s*" + _ZMCL_HEADING_SEP + r"\s*(?:科技创新点|重要科学发现|主要科技创新|主要技术发明"
    r"|技术思路|技术方案|实施效果|详细科学技术内容)"
    r"|发明及创新点|主要技术发明点|主要技术发明内容"
    r")"
)


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
    "hebei_nsfc_2026": {
        "name": "河北省自然科学基金申报书（2026）",
        "description": "适用于河北省自然科学基金申报书正文查重",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        "sections": [
            {
                "name": "一、立论依据",
                "start_pattern": r"一\s*[、\.．]\s*立论依据",
                "end_pattern": r"3\s*[、\.．]\s*主要参考文献目录",
            },
            {
                "name": "二、研究内容、研究目标、拟解决的关键科学问题、创新点及预期成果",
                "start_pattern": r"二\s*[、\.．]\s*研究内容、研究目标、拟解决的关键科学问题、创新点及预期成果",
                "end_pattern": r"三\s*[、\.．]\s*研究方案及可行性分析",
            },
            {
                "name": "三、研究方案及可行性分析",
                "start_pattern": r"三\s*[、\.．]\s*研究方案及可行性分析",
                "end_pattern": r"四\s*[、\.．]\s*研究基础与工作条件",
            },
        ],
    },
    "xxnr": {
        "name": "科技奖励提名材料（国家奖 zmcl 语料）",
        "description": (
            "适用于 file_local_ingest/zmcl2007–zmcl2025 及同结构上传 doc/docx；"
            "正文入口兼容「四、项目详细内容」「1./一、立项背景」「2．详细科学技术内容」「二、主要科技创新」等历版与解析单行化文本。"
        ),
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        # primary_scope 存在时 SectionExtractor 不会读取 sections；宽入口匹配后截取至文末。
        "primary_scope": {
            "start_pattern": _REWARD_ZMCL_PRIMARY_START_PATTERN,
        },
    },
    "msbzyshaqxtcxzxwsjk": {
        "name": "民生保障与社会安全协同创新专项（卫生健康）",
        "description": "适用于民生保障与社会安全协同创新专项（卫生健康）正文查重",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        "primary_scope": {
            "start_pattern": r"项目立项背景及意义",
            "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
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
                "end_pattern": r"第一部分\s*国内外现状及趋势分析",
            },
            {
                "name": "第一部分 国内外现状及趋势分析",
                "start_pattern": r"第一部分\s*国内外现状及趋势分析",
                "end_pattern": r"第二部分\s*研究内容",
            },
            {
                "name": "第二部分 研究内容",
                "start_pattern": r"第二部分\s*研究内容",
                "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
            },
        ],
    },
    "kjyfptzx": {
        "name": "科技研发平台专项",
        "description": "适用于科技研发平台专项正文查重",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        "primary_scope": {
            "start_pattern": r"项目立项背景及意义",
            "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
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
                "end_pattern": r"第一部分\s*国内外现状及趋势分析",
            },
            {
                "name": "第一部分 国内外现状及趋势分析",
                "start_pattern": r"第一部分\s*国内外现状及趋势分析",
                "end_pattern": r"第二部分\s*研究内容",
            },
            {
                "name": "第二部分 研究内容",
                "start_pattern": r"第二部分\s*研究内容",
                "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
            },
        ],
    },
    "swyycycxzxzyydlhyjcx": {
        "name": "生物医药产业创新专项（中医药定量化研究创新）",
        "description": "适用于生物医药产业创新专项（中医药定量化研究创新）正文查重",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        "primary_scope": {
            "start_pattern": r"项目立项背景及意义",
            "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
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
                "end_pattern": r"第一部分\s*国内外现状及趋势分析",
            },
            {
                "name": "第一部分 国内外现状及趋势分析",
                "start_pattern": r"第一部分\s*国内外现状及趋势分析",
                "end_pattern": r"第二部分\s*研究内容",
            },
            {
                "name": "第二部分 研究内容",
                "start_pattern": r"第二部分\s*研究内容",
                "end_pattern": r"第三部分\s*申报单位及合作单位研究基础",
            },
        ],
    },
    "gsprctdjszx": {
        "name": "高水平人才团队建设专项",
        "description": "适用于高水平人才团队建设专项正文查重",
        "whitelist_patterns": WHITELIST_TEMPLATE_PATTERNS,
        "heading_patterns": HEADING_PATTERNS,
        "table_patterns": TABLE_PATTERNS,
        "primary_scope": {
            "start_pattern": r"(?:#{1,6}\s*)?三\s*[、\.．]\s*(?:近三年\s*人才飞地成效情况|项目基本情况)",
            "end_pattern": r"(?:#{1,6}\s*)?五\s*[、\.．]\s*项目绩效评价考核目标及指标",
        },
        "sections": [
            {
                "name": "三、近三年人才飞地成效情况 / 项目基本情况",
                "start_pattern": r"(?:#{1,6}\s*)?三\s*[、\.．]\s*(?:近三年\s*人才飞地成效情况|项目基本情况)",
                "end_pattern": r"(?:#{1,6}\s*)?四\s*[、\.．]\s*(?:未来\s*[2二两]\s*年发展规划|申报单位[、,，]?\s*合作单位经费预算明细表)",
            },
            {
                "name": "四、未来2年发展规划 / 申报单位、合作单位经费预算明细表",
                "start_pattern": r"(?:#{1,6}\s*)?四\s*[、\.．]\s*(?:未来\s*[2二两]\s*年发展规划|申报单位[、,，]?\s*合作单位经费预算明细表)",
                "end_pattern": r"(?:#{1,6}\s*)?五\s*[、\.．]\s*项目绩效评价考核目标及指标",
            },
        ],
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
