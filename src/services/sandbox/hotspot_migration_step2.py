#!/usr/bin/env python3
"""第二步：科研热点迁移最小闭环实现。

能力：
1. 基于两个时间窗构建主题图投影。
2. 运行 Leiden 社区发现识别热点簇。
3. 计算跨时间窗社区迁移流（可用于 Sankey）。
4. 输出机器可读 JSON 与自动研判摘要。

注意：
- 默认 Cypher 模板基于常见标签 Topic/Project/HAS_TOPIC。
- Step2 参数采用代码内默认配置，不依赖 HOTSPOT_* 环境变量。
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

try:
    from src.common.database import get_xkfl_repo
except ModuleNotFoundError:
    get_xkfl_repo = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 自动加载项目根目录 .env
load_dotenv(PROJECT_ROOT / ".env")


SESSION_KWARGS = {
    "notifications_disabled_classifications": ["DEPRECATION"],
}

SANDBOX_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SANDBOX_DIR / "output" / "step2"

DEFAULT_YEAR_A_START = 2023
DEFAULT_YEAR_A_END = 2023
DEFAULT_YEAR_B_START = 2024
DEFAULT_YEAR_B_END = 2024
DEFAULT_PREFERRED_STRATEGY = "project_topic_signature_fast"
DEFAULT_MIN_OVERLAP = 1
DEFAULT_MIN_JACCARD = 0.01
DEFAULT_MAX_EDGES = 150000
DEFAULT_TOP_COMMUNITIES = 8
DEFAULT_OUTPUT_PATH = str(DEFAULT_OUTPUT_DIR / "hotspot_migration_real_schema_2023_to_2024.json")
DEFAULT_COMMUNITY_EDGE_THRESHOLD = 200000
FAST_ATTRIBUTE_GROUP_CAP = 320
ATTRIBUTE_GROUP_CAP = 250
FORCED_COMMUNITY_TARGET_MIN = 150
FORCED_COMMUNITY_TARGET_MAX = 200
FORCED_COMMUNITY_TARGET_IDEAL = 175
DEFAULT_LITE_TOP_COMMUNITIES = 20
DEFAULT_LITE_TOP_LINKS = 20

SCI_KG_LABELS = [
    "Concept",
    "Dataset",
    "DisciplineL1",
    "DisciplineL2",
    "DisciplineL3",
    "Method",
    "Policy",
    "SciEntity",
    "Theory",
    "Entity",
]

MGMT_KG_LABELS = [
    "Person",
    "Organization",
    "Org",
    "Project",
    "Output",
    "Paper",
    "Venue",
    "Fund/Program",
]

MGMT_CORE_RELATIONS = [
    "works_for",
    "undertakes",
    "produces",
    "authored_by",
    "funded_by",
    "published_in",
    "collaborates_with",
    "reviews",
]

SCI_RELATIONS = [
    "RELATES_TO_DISCIPLINE",
    "SUB_OF",
    "WD_FIELD_OF_WORK",
    "WD_INSTANCE_OF",
    "WD_MAIN_SUBJECT",
    "WD_PART_OF",
    "WD_RELEVANT_TOPIC",
    "WD_STUDIES",
    "WD_SUBCLASS_OF",
    "WD_TOPIC_MAIN_CATEGORY",
]

BRIDGE_RELATIONS = ["involves_concept"]

PROJECT_YEAR_EXPR = (
    "toInteger(p.year_norm)"
)
PROJECT1_YEAR_EXPR = (
    "toInteger(p1.year_norm)"
)
PROJECT2_YEAR_EXPR = (
    "toInteger(p2.year_norm)"
)


def _subject_code_expr(var_name: str) -> str:
    return (
        f"CASE "
        f"WHEN {var_name}.ssxk1 IS NOT NULL AND trim(toString({var_name}.ssxk1)) <> '' "
        f"THEN trim(toString({var_name}.ssxk1)) "
        f"WHEN {var_name}.ssxk2 IS NOT NULL AND trim(toString({var_name}.ssxk2)) <> '' "
        f"THEN trim(toString({var_name}.ssxk2)) "
        f"ELSE NULL END"
    )


PROJECT_SUBJECT_CODE_EXPR = _subject_code_expr("p")
PROJECT1_SUBJECT_CODE_EXPR = _subject_code_expr("p1")
PROJECT2_SUBJECT_CODE_EXPR = _subject_code_expr("p2")

_SUBJECT_CACHE: dict[str, str] | None = None


def _project_text_expr(var_name: str) -> str:
    return (
        "toLower("
        "coalesce("
        f"toString({var_name}.projectName), '') + ' ' + "
        f"coalesce(toString({var_name}.`项目简介`), '') + ' ' + "
        f"coalesce(toString({var_name}.`研究内容`), '') + ' ' + "
        f"coalesce(toString({var_name}.guideName), '') + ' ' + "
        f"coalesce(toString({var_name}.name), '') + ' ' + "
        f"coalesce(toString({var_name}.title), '')"
        ")"
        ")"
    )


def _broad_subject_expr(var_name: str) -> str:
    text_expr = _project_text_expr(var_name)
    return (
        "CASE "
        f"WHEN {text_expr} CONTAINS '中医' OR {text_expr} CONTAINS '中药' OR {text_expr} CONTAINS '医方' "
        f"OR {text_expr} CONTAINS '针灸' "
        "THEN '中医药' "
        f"WHEN {text_expr} CONTAINS '癌' OR {text_expr} CONTAINS '肿瘤' OR {text_expr} CONTAINS '细胞' "
        f"OR {text_expr} CONTAINS '免疫' OR {text_expr} CONTAINS '临床' OR {text_expr} CONTAINS '疾病' "
        f"OR {text_expr} CONTAINS '病理' OR {text_expr} CONTAINS '药效' OR {text_expr} CONTAINS '肝' "
        f"OR {text_expr} CONTAINS '胃' OR {text_expr} CONTAINS '关节炎' OR {text_expr} CONTAINS '神经' "
        f"OR {text_expr} CONTAINS '帕金森' OR {text_expr} CONTAINS '纤维化' OR {text_expr} CONTAINS '炎症' "
        f"OR {text_expr} CONTAINS '巨噬细胞' "
        "THEN '医学' "
        f"WHEN {text_expr} CONTAINS '农业' OR {text_expr} CONTAINS '作物' OR {text_expr} CONTAINS '种质' "
        f"OR {text_expr} CONTAINS '育种' OR {text_expr} CONTAINS '畜禽' OR {text_expr} CONTAINS '绵羊' "
        f"OR {text_expr} CONTAINS '植物' OR {text_expr} CONTAINS '林业' "
        "THEN '农业' "
        f"WHEN {text_expr} CONTAINS '地理' OR {text_expr} CONTAINS '遥感' OR {text_expr} CONTAINS '测绘' "
        f"OR {text_expr} CONTAINS '地球' OR {text_expr} CONTAINS '地质' OR {text_expr} CONTAINS '气象' "
        f"OR {text_expr} CONTAINS '海洋' OR {text_expr} CONTAINS '水文' OR {text_expr} CONTAINS '流域' "
        f"OR {text_expr} CONTAINS '冰川' OR {text_expr} CONTAINS '土壤' "
        "THEN '地理' "
        f"WHEN {text_expr} CONTAINS '环境' OR {text_expr} CONTAINS '生态' OR {text_expr} CONTAINS '污染' "
        f"OR {text_expr} CONTAINS '碳' OR {text_expr} CONTAINS '减排' "
        "THEN '环境' "
        f"WHEN {text_expr} CONTAINS '化学' OR {text_expr} CONTAINS '催化' "
        f"OR {text_expr} CONTAINS '合成' OR {text_expr} CONTAINS '电化学' OR {text_expr} CONTAINS '有机' "
        f"OR {text_expr} CONTAINS '无机' "
        "THEN '化学' "
        f"WHEN {text_expr} CONTAINS '材料' OR {text_expr} CONTAINS '纳米' OR {text_expr} CONTAINS '薄膜' "
        f"OR {text_expr} CONTAINS '晶体' OR {text_expr} CONTAINS '陶瓷' OR {text_expr} CONTAINS '复合' "
        f"OR {text_expr} CONTAINS '涂层' "
        "THEN '材料' "
        f"WHEN {text_expr} CONTAINS '物理' OR {text_expr} CONTAINS '量子' OR {text_expr} CONTAINS '光学' "
        f"OR {text_expr} CONTAINS '激光' OR {text_expr} CONTAINS '磁' OR {text_expr} CONTAINS '等离子' "
        "THEN '物理' "
        f"WHEN {text_expr} CONTAINS '数学' OR {text_expr} CONTAINS '统计' OR {text_expr} CONTAINS '代数' "
        f"OR {text_expr} CONTAINS '几何' OR {text_expr} CONTAINS '拓扑' OR {text_expr} CONTAINS '微分方程' "
        f"OR {text_expr} CONTAINS '小波' OR {text_expr} CONTAINS '算子' "
        "THEN '数学' "
        f"WHEN {text_expr} CONTAINS '人工智能' OR {text_expr} CONTAINS 'ai' OR {text_expr} CONTAINS '算法' "
        f"OR {text_expr} CONTAINS '数据' OR {text_expr} CONTAINS '软件' OR {text_expr} CONTAINS '计算机' "
        f"OR {text_expr} CONTAINS '网络' OR {text_expr} CONTAINS '信息' OR {text_expr} CONTAINS '模型' "
        "THEN '信息' "
        f"WHEN {text_expr} CONTAINS '电子' OR {text_expr} CONTAINS '通信' OR {text_expr} CONTAINS '传感' "
        f"OR {text_expr} CONTAINS '芯片' OR {text_expr} CONTAINS '半导体' OR {text_expr} CONTAINS '电路' "
        "THEN '电子' "
        f"WHEN {text_expr} CONTAINS '机械' OR {text_expr} CONTAINS '制造' OR {text_expr} CONTAINS '装备' "
        f"OR {text_expr} CONTAINS '工程' OR {text_expr} CONTAINS '结构' OR {text_expr} CONTAINS '控制' "
        f"OR {text_expr} CONTAINS '机器人' "
        "THEN '工程' "
        f"WHEN {text_expr} CONTAINS '能源' OR {text_expr} CONTAINS '电池' OR {text_expr} CONTAINS '储能' "
        f"OR {text_expr} CONTAINS '光伏' OR {text_expr} CONTAINS '氢能' OR {text_expr} CONTAINS '燃料电池' "
        "THEN '能源' "
        f"WHEN {text_expr} CONTAINS '经济' OR {text_expr} CONTAINS '管理' OR {text_expr} CONTAINS '金融' "
        f"OR {text_expr} CONTAINS '政策' OR {text_expr} CONTAINS '治理' OR {text_expr} CONTAINS '转移转化' "
        "THEN '管理' "
        "ELSE '其他' END"
    )


def _topic_signature_expr(var_name: str) -> str:
    text_expr = _project_text_expr(var_name)
    return (
        "CASE "
        f"WHEN {text_expr} CONTAINS '蜘蛛' THEN '蜘蛛多样性' "
        f"WHEN {text_expr} CONTAINS '生物多样性' THEN '生物多样性' "
        f"WHEN {text_expr} CONTAINS '生态安全' THEN '生态安全' "
        f"WHEN {text_expr} CONTAINS '生态评估' THEN '生态评估' "
        f"WHEN {text_expr} CONTAINS '碳收支' THEN '碳收支' "
        f"WHEN {text_expr} CONTAINS '遥感' THEN '遥感' "
        f"WHEN {text_expr} CONTAINS '土壤' THEN '土壤' "
        f"WHEN {text_expr} CONTAINS '气候' THEN '气候' "
        f"WHEN {text_expr} CONTAINS '湿地' THEN '湿地生态' "
        f"WHEN {text_expr} CONTAINS '流域' THEN '流域生态' "
        f"WHEN {text_expr} CONTAINS '中药材' THEN '中药材' "
        f"WHEN {text_expr} CONTAINS '胃癌' THEN '胃癌' "
        f"WHEN {text_expr} CONTAINS '食管癌' THEN '食管癌' "
        f"WHEN {text_expr} CONTAINS '乳腺癌' THEN '乳腺癌' "
        f"WHEN {text_expr} CONTAINS '肝细胞癌' THEN '肝癌' "
        f"WHEN {text_expr} CONTAINS '肿瘤' THEN '肿瘤' "
        f"WHEN {text_expr} CONTAINS '中医药' OR {text_expr} CONTAINS '中医' THEN '中医药' "
        f"WHEN {text_expr} CONTAINS '免疫' THEN '免疫' "
        f"WHEN {text_expr} CONTAINS '细胞' THEN '细胞' "
        f"WHEN {text_expr} CONTAINS '外泌体' THEN '外泌体' "
        f"WHEN {text_expr} CONTAINS '炎症' THEN '炎症' "
        f"WHEN {text_expr} CONTAINS '纤维化' THEN '纤维化' "
        f"WHEN {text_expr} CONTAINS '帕金森' THEN '帕金森病' "
        f"WHEN {text_expr} CONTAINS '脑损伤' THEN '脑损伤修复' "
        f"WHEN {text_expr} CONTAINS '诊断' THEN '智能诊断' "
        f"WHEN {text_expr} CONTAINS '人工智能' OR {text_expr} CONTAINS ' ai' OR {text_expr} CONTAINS 'ai ' THEN '人工智能' "
        f"WHEN {text_expr} CONTAINS '算法' THEN '算法模型' "
        f"WHEN {text_expr} CONTAINS '数据' THEN '数据分析' "
        f"WHEN {text_expr} CONTAINS '纳米' THEN '纳米材料' "
        f"WHEN {text_expr} CONTAINS '材料' THEN '材料' "
        f"WHEN {text_expr} CONTAINS '半导体' THEN '半导体' "
        f"WHEN {text_expr} CONTAINS '芯片' THEN '芯片' "
        f"WHEN {text_expr} CONTAINS '光伏' THEN '光伏' "
        f"WHEN {text_expr} CONTAINS '电池' THEN '电池储能' "
        f"WHEN {text_expr} CONTAINS '储能' THEN '储能' "
        f"WHEN {text_expr} CONTAINS '量子' THEN '量子物理' "
        f"WHEN {text_expr} CONTAINS '激光' THEN '激光光学' "
        f"WHEN {text_expr} CONTAINS '算子' THEN '算子理论' "
        f"WHEN {text_expr} CONTAINS '小波' THEN '小波分析' "
        f"WHEN {text_expr} CONTAINS '统计' THEN '统计数学' "
        f"WHEN {text_expr} CONTAINS '绵羊' THEN '绵羊育种' "
        f"WHEN {text_expr} CONTAINS '育种' THEN '育种' "
        f"WHEN {text_expr} CONTAINS '作物' THEN '作物科学' "
        f"WHEN {text_expr} CONTAINS '污染' THEN '污染治理' "
        f"WHEN {text_expr} CONTAINS '生态' THEN '生态研究' "
        f"WHEN {text_expr} CONTAINS '地理' THEN '地理研究' "
        f"WHEN {text_expr} CONTAINS '化学' THEN '化学研究' "
        f"WHEN {text_expr} CONTAINS '管理' OR {text_expr} CONTAINS '治理' OR {text_expr} CONTAINS '转移转化' THEN '科技治理' "
        f"ELSE {_broad_subject_expr(var_name)} END"
    )


PROJECT_BROAD_SUBJECT_EXPR = f"({_broad_subject_expr('p')})"
PROJECT_TOPIC_SIGNATURE_EXPR = f"({_topic_signature_expr('p')})"

DEFAULT_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project)<-[:undertakes]-(person:Person)-[:undertakes]->"
    "(p2:Project)-[:funded_by]->(f2:`Fund/Program`) "
    "WHERE id(f1) < id(f2) "
    "WITH f1, f2, person, "
    f"{PROJECT1_YEAR_EXPR} AS y1, "
    f"{PROJECT2_YEAR_EXPR} AS y2 "
    "WHERE y1 >= {start_year} AND y1 <= {end_year} "
    "AND y2 >= {start_year} AND y2 <= {end_year} "
    "RETURN id(f1) AS source, id(f2) AS target, count(DISTINCT person) AS weight"
)

DEFAULT_GUIDE_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_GUIDE_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.guideName IS NOT NULL AND p1.guideName = p2.guideName "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

DEFAULT_DEPARTMENT_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_DEPARTMENT_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.department IS NOT NULL AND p1.department = p2.department "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

DEFAULT_OFFICE_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
    "RETURN DISTINCT id(f) AS id"
)

DEFAULT_OFFICE_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    "AND p1.office IS NOT NULL AND p1.office = p2.office "
    f"AND {PROJECT1_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT1_YEAR_EXPR} <= {{end_year}} "
    f"AND {PROJECT2_YEAR_EXPR} >= {{start_year}} "
    f"AND {PROJECT2_YEAR_EXPR} <= {{end_year}} "
    "RETURN id(f1) AS source, id(f2) AS target, count(*) AS weight"
)

RELATION_CHAIN_REQUIRED = ["undertakes", "produces", "authored_by", "funded_by"]

RELATION_CHAIN_NODE_TEMPLATE = (
    "MATCH (f:`Fund/Program`)<-[:funded_by]-(p:Project) "
    f"WITH f, {PROJECT_YEAR_EXPR} AS y "
    "WHERE y >= {start_year} AND y <= {end_year} "
    "RETURN DISTINCT id(f) AS id"
)

RELATION_CHAIN_REL_TEMPLATE = (
    "MATCH (f1:`Fund/Program`)<-[:funded_by]-(p1:Project), "
    "(f2:`Fund/Program`)<-[:funded_by]-(p2:Project) "
    "WHERE id(f1) < id(f2) "
    f"WITH f1, f2, p1, p2, {PROJECT1_YEAR_EXPR} AS y1, {PROJECT2_YEAR_EXPR} AS y2 "
    "WHERE y1 >= {start_year} AND y1 <= {end_year} "
    "AND y2 >= {start_year} AND y2 <= {end_year} "
    "OPTIONAL MATCH (p1)<-[:undertakes]-(u:Person)-[:undertakes]->(p2) "
    "WITH f1, f2, p1, p2, collect(DISTINCT id(u)) AS undertake_people "
    "OPTIONAL MATCH (p1)-[:produces]->(o1)<-[:authored_by]-(a:Person)-[:authored_by]->(o2)<-[:produces]-(p2) "
    "WITH f1, f2, undertake_people, collect(DISTINCT id(a)) AS author_people "
    "WITH f1, f2, toFloat(size(undertake_people) + size(author_people)) AS weight "
    "WHERE weight > 0 "
    "RETURN id(f1) AS source, id(f2) AS target, weight"
)


@dataclass
class HotspotConfig:
    uri: str
    user: str
    password: str
    database: str
    year_a_start: int
    year_a_end: int
    year_b_start: int
    year_b_end: int
    node_query_template: str
    rel_query_template: str
    min_overlap_count: int
    min_jaccard: float
    top_community_count: int
    output_path: str
    preferred_strategy: str
    community_edge_threshold: int
    max_edges: int
    require_real_data: bool
    min_total_nodes: int
    min_total_relationships: int
    min_project_count: int
    min_undertakes_count: int
    min_year_norm_ratio: float


@dataclass
class ProjectionStrategy:
    name: str
    description: str
    node_query_template: str
    rel_query_template: str
    node_label_fields: list[str]


def log_progress(stage: str, message: str, **fields: Any) -> None:
    parts = [f"{key}={value}" for key, value in fields.items() if value is not None]
    suffix = f" | {' '.join(parts)}" if parts else ""
    print(f"[STEP2][{stage}] {message}{suffix}")


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_subject_cache() -> dict[str, str]:
    global _SUBJECT_CACHE
    if _SUBJECT_CACHE is not None:
        return _SUBJECT_CACHE

    subject_cache: dict[str, str] = {}
    if get_xkfl_repo is None:
        _SUBJECT_CACHE = subject_cache
        return subject_cache

    try:
        repo = get_xkfl_repo()
        for row in repo.list_all_zrjj():
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if code and name:
                subject_cache[code] = name

        for row in repo.list_all():
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if code and name and code not in subject_cache:
                subject_cache[code] = name
    except Exception as exc:
        log_progress("subject", "subject cache load failed", error=str(exc))

    _SUBJECT_CACHE = subject_cache
    return subject_cache


def resolve_subject_name(code: str | None) -> str:
    value = str(code or "").strip()
    if not value:
        return ""
    return load_subject_cache().get(value, value)


def format_subject_display(code: str | None) -> str:
    value = str(code or "").strip()
    if not value:
        return ""
    name = resolve_subject_name(value)
    return f"{value}-{name}" if name and name != value else value


def _normalize_project_text(*values: Any) -> str:
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


TOPIC_SIGNATURE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("生物多样性", ("生物多样性",)),
    ("生物多样性", ("蜘蛛",)),
    ("生态安全评估", ("生态安全",)),
    ("生态评估", ("生态评估",)),
    ("碳收支", ("碳收支",)),
    ("遥感空间分析", ("遥感",)),
    ("土壤环境评估", ("土壤",)),
    ("气候变化", ("气候",)),
    ("湿地生态保护", ("湿地",)),
    ("流域生态评估", ("流域",)),
    ("中药材开发", ("中药材",)),
    ("胃癌", ("胃癌",)),
    ("食管癌", ("食管癌",)),
    ("乳腺癌", ("乳腺癌",)),
    ("肝癌", ("肝细胞癌",)),
    ("肿瘤发生机制", ("肿瘤",)),
    ("中医药", ("中医药", "中医", "中药", "医方", "针灸")),
    ("免疫调控", ("免疫",)),
    ("细胞机制", ("细胞",)),
    ("外泌体", ("外泌体",)),
    ("炎症调控", ("炎症",)),
    ("纤维化", ("纤维化",)),
    ("帕金森病", ("帕金森",)),
    ("脑损伤修复", ("脑损伤",)),
    ("分子诊断", ("诊断",)),
    ("人工智能", ("人工智能", " ai", "ai ", "ai辅助")),
    ("预测建模", ("算法",)),
    ("数据分析", ("数据",)),
    ("纳米材料制备", ("纳米",)),
    ("半导体器件", ("半导体",)),
    ("芯片设计", ("芯片",)),
    ("光伏材料", ("光伏",)),
    ("电池储能", ("电池",)),
    ("储能技术", ("储能",)),
    ("量子计算", ("量子",)),
    ("激光光学", ("激光",)),
    ("算子理论", ("算子",)),
    ("小波分析", ("小波",)),
    ("统计建模", ("统计",)),
    ("绵羊育种", ("绵羊",)),
    ("作物育种", ("育种",)),
    ("作物科学", ("作物",)),
    ("污染治理", ("污染",)),
    ("生态评估", ("生态",)),
    ("地表过程建模", ("地理",)),
    ("有机合成", ("化学",)),
    ("科技治理", ("管理", "治理", "转移转化")),
]

BROAD_SUBJECT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("中医药", ("中医", "中药", "医方", "针灸")),
    ("疾病机制", ("癌", "肿瘤", "细胞", "免疫", "临床", "疾病", "病理", "药效", "肝", "胃", "关节炎", "神经", "帕金森", "纤维化", "炎症", "巨噬细胞")),
    ("农业育种", ("农业", "作物", "种质", "育种", "畜禽", "绵羊", "植物", "林业")),
    ("自然地理过程", ("地理", "遥感", "测绘", "地球", "地质", "气象", "海洋", "水文", "流域", "冰川", "土壤")),
    ("生态环境治理", ("环境", "生态", "污染", "碳", "减排")),
    ("催化反应机理", ("化学", "催化", "合成", "电化学", "有机", "无机")),
    ("材料制备", ("材料", "纳米", "薄膜", "晶体", "陶瓷", "复合", "涂层")),
    ("量子光学", ("物理", "量子", "光学", "激光", "磁", "等离子")),
    ("数学建模", ("数学", "统计", "代数", "几何", "拓扑", "微分方程", "小波", "算子")),
    ("人工智能", ("人工智能", "ai", "算法", "数据", "软件", "计算机", "网络", "信息", "模型")),
    ("电子器件", ("电子", "通信", "传感", "芯片", "半导体", "电路")),
    ("智能装备", ("机械", "制造", "装备", "工程", "结构", "控制", "机器人")),
    ("储能材料", ("能源", "电池", "储能", "光伏", "氢能", "燃料电池")),
    ("科技治理", ("经济", "管理", "金融", "政策", "治理", "转移转化")),
]


def infer_project_broad_subject(text: str) -> str:
    normalized = _normalize_project_text(text)
    for label, keywords in BROAD_SUBJECT_RULES:
        if any(keyword in normalized for keyword in keywords):
            return label
    return "其他"


def infer_project_topic_signature(text: str) -> str:
    normalized = _normalize_project_text(text)
    for label, keywords in TOPIC_SIGNATURE_RULES:
        if any(keyword in normalized for keyword in keywords):
            return label
    return infer_project_broad_subject(normalized)


def _collect_python_group_projection(
    session: Any,
    start: int,
    end: int,
    classifier: Any,
    group_cap: int,
) -> tuple[list[int], list[dict[str, float]]]:
    rows = session.run(
        """
        MATCH (p:Project)
        WITH p, toInteger(p.year_norm) AS y
        WHERE y >= $start_year AND y <= $end_year
        RETURN id(p) AS node_id,
               p.projectName AS project_name,
               p.guideName AS guide_name,
               p.`项目简介` AS project_intro,
               p.`研究内容` AS research_content
        """,
        {"start_year": start, "end_year": end},
    )

    groups: dict[str, list[int]] = {}
    node_ids: list[int] = []
    for row in rows:
        node_id = int(row["node_id"])
        node_ids.append(node_id)
        text = _normalize_project_text(
            row["project_name"],
            row["project_intro"],
            row["research_content"],
            row["guide_name"],
        )
        group_name = classifier(text)
        groups.setdefault(group_name, []).append(node_id)

    edges: list[dict[str, float]] = []
    for ids in groups.values():
        limited = ids[:group_cap]
        for i in range(len(limited) - 1):
            for j in range(i + 1, len(limited)):
                edges.append({"source": limited[i], "target": limited[j], "weight": 1.0})

    return sorted(set(node_ids)), edges


def aggregate_projects_by_topic_signature(
    session: Any,
    start: int,
    end: int,
    top_community_count: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    rows = session.run(
        """
        MATCH (p:Project)
        WITH p, toInteger(p.year_norm) AS y
        WHERE y >= $start_year AND y <= $end_year
        RETURN id(p) AS node_id,
               p.projectName AS project_name,
               p.`项目简介` AS project_intro,
               p.`研究内容` AS research_content,
               p.guideName AS guide_name
        """,
        {"start_year": start, "end_year": end},
    )

    groups: dict[str, list[int]] = {}
    for row in rows:
        node_id = int(row["node_id"])
        text = _normalize_project_text(
            row["project_name"],
            row["project_intro"],
            row["research_content"],
            row["guide_name"],
        )
        topic_signature = infer_project_topic_signature(text)
        groups.setdefault(topic_signature, []).append(node_id)

    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    summary: dict[int, dict[str, Any]] = {}
    synthetic_edge_count = 0
    for idx, (topic_signature, node_ids) in enumerate(ranked):
        unique_nodes = sorted(set(node_ids))
        size = len(unique_nodes)
        synthetic_edge_count += size * max(0, size - 1) // 2
        summary[idx + 1] = {
            "communityId": idx + 1,
            "size": size,
            "nodeIds": unique_nodes,
            "keywordSet": [topic_signature],
            "topKeywords": [topic_signature],
            "rank": idx + 1,
            "isTopCommunity": idx < top_community_count,
        }

    return summary, {
        "nodeCount": sum(len(set(node_ids)) for node_ids in groups.values()),
        "relationshipCount": int(synthetic_edge_count),
    }


def build_config() -> HotspotConfig:
    year_a_start = DEFAULT_YEAR_A_START
    year_a_end = DEFAULT_YEAR_A_END
    year_b_start = DEFAULT_YEAR_B_START
    year_b_end = DEFAULT_YEAR_B_END

    if year_a_end < year_a_start or year_b_end < year_b_start:
        raise ValueError("年份区间非法：结束年份不能小于开始年份")

    return HotspotConfig(
        uri=getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=getenv_required("NEO4J_USER", "neo4j"),
        password=getenv_required("NEO4J_PASSWORD"),
        database=getenv_required("NEO4J_DATABASE", "neo4j"),
        year_a_start=year_a_start,
        year_a_end=year_a_end,
        year_b_start=year_b_start,
        year_b_end=year_b_end,
        node_query_template=DEFAULT_NODE_TEMPLATE,
        rel_query_template=DEFAULT_REL_TEMPLATE,
        min_overlap_count=DEFAULT_MIN_OVERLAP,
        min_jaccard=DEFAULT_MIN_JACCARD,
        top_community_count=DEFAULT_TOP_COMMUNITIES,
        output_path=DEFAULT_OUTPUT_PATH,
        preferred_strategy=DEFAULT_PREFERRED_STRATEGY,
        community_edge_threshold=DEFAULT_COMMUNITY_EDGE_THRESHOLD,
        max_edges=DEFAULT_MAX_EDGES,
        require_real_data=env_bool("SANDBOX_REQUIRE_REAL_DATA", True),
        min_total_nodes=max(1, int(os.getenv("SANDBOX_REAL_MIN_TOTAL_NODES", "1000000"))),
        min_total_relationships=max(1, int(os.getenv("SANDBOX_REAL_MIN_TOTAL_RELATIONSHIPS", "1000000"))),
        min_project_count=max(1, int(os.getenv("SANDBOX_REAL_MIN_PROJECTS", "1000"))),
        min_undertakes_count=max(1, int(os.getenv("SANDBOX_REAL_MIN_UNDERTAKES", "1000"))),
        min_year_norm_ratio=max(0.0, min(1.0, float(os.getenv("SANDBOX_REAL_MIN_YEAR_NORM_RATIO", "0.95")))),
    )


def verify_real_data_snapshot(session: Any, cfg: HotspotConfig) -> dict[str, Any]:
    labels = sorted([str(r["label"]) for r in session.run("CALL db.labels() YIELD label RETURN label")])
    rel_types = sorted([str(r["relationshipType"]) for r in session.run(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    )])

    total_nodes = int(session.run("MATCH (n) RETURN count(n) AS c").single()["c"])
    total_relationships = int(session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"])
    project_count = int(session.run("MATCH (p:Project) RETURN count(p) AS c").single()["c"])
    year_norm_filled = int(session.run(
        "MATCH (p:Project) RETURN sum(CASE WHEN p.year_norm IS NOT NULL THEN 1 ELSE 0 END) AS c"
    ).single()["c"] or 0)
    undertakes_count = int(session.run("MATCH ()-[r:undertakes]->() RETURN count(r) AS c").single()["c"])
    year_norm_ratio = (year_norm_filled / project_count) if project_count > 0 else 0.0

    required_labels = ["Project", "Person", "Output", "Fund/Program"]
    required_rels = ["undertakes", "funded_by", "produces"]
    missing_labels = [x for x in required_labels if x not in labels]
    missing_rels = [x for x in required_rels if x not in rel_types]

    checks = {
        "totalNodes": {
            "actual": total_nodes,
            "minRequired": cfg.min_total_nodes,
            "ok": total_nodes >= cfg.min_total_nodes,
        },
        "totalRelationships": {
            "actual": total_relationships,
            "minRequired": cfg.min_total_relationships,
            "ok": total_relationships >= cfg.min_total_relationships,
        },
        "projectCount": {
            "actual": project_count,
            "minRequired": cfg.min_project_count,
            "ok": project_count >= cfg.min_project_count,
        },
        "yearNormCoverage": {
            "actual": round(year_norm_ratio, 6),
            "filled": year_norm_filled,
            "total": project_count,
            "minRequired": cfg.min_year_norm_ratio,
            "ok": year_norm_ratio >= cfg.min_year_norm_ratio,
        },
        "undertakesCount": {
            "actual": undertakes_count,
            "minRequired": cfg.min_undertakes_count,
            "ok": undertakes_count >= cfg.min_undertakes_count,
        },
    }

    verified = (not missing_labels) and (not missing_rels) and all(v["ok"] for v in checks.values())
    return {
        "verified": verified,
        "requireRealData": cfg.require_real_data,
        "requiredLabels": required_labels,
        "requiredRelationshipTypes": required_rels,
        "missingLabels": missing_labels,
        "missingRelationshipTypes": missing_rels,
        "checks": checks,
    }


def _quote_label(label: str) -> str:
    return f"`{label}`" if "/" in label else label


def _count_nodes_by_labels(session: Any, labels: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        row = session.run(
            f"MATCH (n:{_quote_label(label)}) RETURN count(n) AS c"
        ).single()
        counts[label] = int(row["c"] or 0) if row else 0
    return counts


def _count_relationships_by_types(session: Any, rel_types: list[str]) -> dict[str, int]:
    existing_rel_types = {
        str(r["relationshipType"])
        for r in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    }
    counts: dict[str, int] = {}
    for rel_type in rel_types:
        if rel_type not in existing_rel_types:
            counts[rel_type] = 0
            continue
        row = session.run(
            f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS c"
        ).single()
        counts[rel_type] = int(row["c"] or 0) if row else 0
    return counts


def collect_dual_layer_profile(session: Any) -> dict[str, Any]:
    sci_label_counts = _count_nodes_by_labels(session, SCI_KG_LABELS)
    mgmt_label_counts = _count_nodes_by_labels(session, MGMT_KG_LABELS)
    mgmt_rel_counts = _count_relationships_by_types(session, MGMT_CORE_RELATIONS)
    sci_rel_counts = _count_relationships_by_types(session, SCI_RELATIONS)
    bridge_rel_counts = _count_relationships_by_types(session, BRIDGE_RELATIONS)

    def _present_items(count_map: dict[str, int]) -> list[str]:
        return [name for name, count in count_map.items() if count > 0]

    def _missing_items(count_map: dict[str, int]) -> list[str]:
        return [name for name, count in count_map.items() if count <= 0]

    management_ready = len(_present_items(mgmt_label_counts)) >= 4 and len(_present_items(mgmt_rel_counts)) >= 3
    scientific_ready = len(_present_items(sci_label_counts)) >= 4 and len(_present_items(sci_rel_counts)) >= 2
    bridge_ready = bridge_rel_counts.get("involves_concept", 0) > 0

    reliability_notes: list[str] = []
    if not bridge_ready:
      reliability_notes.append("知识层与管理层之间尚未建立 involves_concept 桥接，结论主要依赖管理层属性与关系近似。")
    if mgmt_rel_counts.get("published_in", 0) <= 0:
      reliability_notes.append("期刊/会议发表链路未建，成果传播与载体分布判断仍不完整。")
    if mgmt_rel_counts.get("reviews", 0) <= 0:
      reliability_notes.append("评审活动链路未建，专家评审影响与评审结构无法闭环。")
    if mgmt_label_counts.get("Output", 0) <= 0 and mgmt_label_counts.get("Paper", 0) <= 0:
      reliability_notes.append("成果层覆盖不足，产出转化与作者协同判断会偏弱。")
    if sci_label_counts.get("Concept", 0) <= 0:
      reliability_notes.append("科学知识层核心概念节点不足，语义桥接和主题归并可靠性有限。")

    return {
        "scientificLayer": {
            "labels": sci_label_counts,
            "presentLabels": _present_items(sci_label_counts),
            "missingLabels": _missing_items(sci_label_counts),
            "ready": scientific_ready,
        },
        "managementLayer": {
            "labels": mgmt_label_counts,
            "presentLabels": _present_items(mgmt_label_counts),
            "missingLabels": _missing_items(mgmt_label_counts),
            "ready": management_ready,
        },
        "bridgeLayer": {
            "relationships": bridge_rel_counts,
            "ready": bridge_ready,
            "missingRelationships": _missing_items(bridge_rel_counts),
        },
        "relations": {
            "managementCore": mgmt_rel_counts,
            "scientificCore": sci_rel_counts,
            "bridge": bridge_rel_counts,
        },
        "overallReady": management_ready and scientific_ready and bridge_ready,
        "reliabilityNotes": reliability_notes,
    }


def build_strategy_catalog() -> list[ProjectionStrategy]:
    return [
        ProjectionStrategy(
            name="project_topic_signature_fast",
            description="快速模式：按项目标题与简介提炼细粒度主题签名，并按主题签名聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_TOPIC_SIGNATURE_EXPR} AS topic_signature "
                "WHERE y >= {start_year} AND y <= {end_year} AND topic_signature IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_TOPIC_SIGNATURE_EXPR} AS topic_signature "
                "WHERE y >= {start_year} AND y <= {end_year} AND topic_signature IS NOT NULL "
                f"WITH topic_signature AS grp, collect(id(p))[0..{FAST_ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["projectName", "guideName", "项目简介", "研究内容"],
        ),
        ProjectionStrategy(
            name="project_topic_signature",
            description="按项目标题与简介提炼细粒度主题签名，并按主题签名聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_TOPIC_SIGNATURE_EXPR} AS topic_signature "
                "WHERE y >= {start_year} AND y <= {end_year} AND topic_signature IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_TOPIC_SIGNATURE_EXPR} AS topic_signature "
                "WHERE y >= {start_year} AND y <= {end_year} AND topic_signature IS NOT NULL "
                f"WITH topic_signature AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["projectName", "guideName", "项目简介", "研究内容"],
        ),
        ProjectionStrategy(
            name="project_broad_subject_fast",
            description="快速模式：按项目名称与指南文本推断大类学科，并按大类学科聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_BROAD_SUBJECT_EXPR} AS broad_subject "
                "WHERE y >= {start_year} AND y <= {end_year} AND broad_subject IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_BROAD_SUBJECT_EXPR} AS broad_subject "
                "WHERE y >= {start_year} AND y <= {end_year} AND broad_subject IS NOT NULL "
                f"WITH broad_subject AS grp, collect(id(p))[0..{FAST_ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["projectName", "guideName", "department", "office"],
        ),
        ProjectionStrategy(
            name="project_broad_subject",
            description="按项目名称与指南文本推断大类学科，并按大类学科聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_BROAD_SUBJECT_EXPR} AS broad_subject "
                "WHERE y >= {start_year} AND y <= {end_year} AND broad_subject IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_BROAD_SUBJECT_EXPR} AS broad_subject "
                "WHERE y >= {start_year} AND y <= {end_year} AND broad_subject IS NOT NULL "
                f"WITH broad_subject AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["projectName", "guideName", "department", "office"],
        ),
        ProjectionStrategy(
            name="project_subject_code_fast",
            description="快速模式：按 Project.ssxk1/ssxk2 学科代码共现构图，适合按学科领域聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_SUBJECT_CODE_EXPR} AS subject_code "
                "WHERE y >= {start_year} AND y <= {end_year} AND subject_code IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_SUBJECT_CODE_EXPR} AS subject_code "
                "WHERE y >= {start_year} AND y <= {end_year} AND subject_code IS NOT NULL "
                f"WITH subject_code AS grp, collect(id(p))[0..{FAST_ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["ssxk1", "ssxk2", "projectName", "guideName"],
        ),
        ProjectionStrategy(
            name="project_subject_code",
            description="按 Project.ssxk1/ssxk2 学科代码共现构图，适合按学科领域聚合热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_SUBJECT_CODE_EXPR} AS subject_code "
                "WHERE y >= {start_year} AND y <= {end_year} AND subject_code IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y, {PROJECT_SUBJECT_CODE_EXPR} AS subject_code "
                "WHERE y >= {start_year} AND y <= {end_year} AND subject_code IS NOT NULL "
                f"WITH subject_code AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["ssxk1", "ssxk2", "projectName", "guideName"],
        ),
        ProjectionStrategy(
            name="project_guide_name_fast",
            description="快速模式：按 Project.guideName 共现构图，并将组内规模控制在约 300-350 项目的粗粒度范围，兼顾速度与簇规模。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                f"WITH p.guideName AS grp, collect(id(p))[0..{FAST_ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["guideName", "projectName", "department", "office"],
        ),
        ProjectionStrategy(
            name="relation_chain_priority",
            description="关系链优先（undertakes+produces+authored_by+funded_by）迁移口径。",
            node_query_template=RELATION_CHAIN_NODE_TEMPLATE,
            rel_query_template=RELATION_CHAIN_REL_TEMPLATE,
            node_label_fields=["name", "基金名称", "label", "title"],
        ),
        ProjectionStrategy(
            name="project_guide_name",
            description="按 Project.guideName 共现构图，适合识别主题热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.guideName IS NOT NULL "
                f"WITH p.guideName AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["guideName", "projectName", "department", "office"],
        ),
        ProjectionStrategy(
            name="project_department",
            description="按 Project.department 共现构图，适合识别部门科研方向迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.department IS NOT NULL "
                f"WITH p.department AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["department", "projectName", "guideName", "office"],
        ),
        ProjectionStrategy(
            name="project_office",
            description="按 Project.office 共现构图，适合识别区域/单位热点迁移。",
            node_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
                "RETURN DISTINCT id(p) AS id"
            ),
            rel_query_template=(
                "MATCH (p:Project) "
                f"WITH p, {PROJECT_YEAR_EXPR} AS y "
                "WHERE y >= {start_year} AND y <= {end_year} AND p.office IS NOT NULL "
                f"WITH p.office AS grp, collect(id(p))[0..{ATTRIBUTE_GROUP_CAP}] AS ids "
                "WHERE size(ids) > 1 "
                "UNWIND range(0, size(ids) - 2) AS i "
                "UNWIND range(i + 1, size(ids) - 1) AS j "
                "RETURN ids[i] AS source, ids[j] AS target, 1.0 AS weight"
            ),
            node_label_fields=["office", "projectName", "guideName", "department"],
        ),
        ProjectionStrategy(
            name="topic_template",
            description="兼容旧的 Topic/HAS_TOPIC 模板。",
            node_query_template=DEFAULT_NODE_TEMPLATE,
            rel_query_template=DEFAULT_REL_TEMPLATE,
            node_label_fields=["name", "title", "keyword", "subject", "label"],
        ),
    ]


def _relation_chain_readiness(graph_profile: dict[str, Any]) -> dict[str, Any]:
    rel_counts = ((graph_profile.get("relations") or {}).get("managementCore") or {})
    missing = [name for name in RELATION_CHAIN_REQUIRED if int(rel_counts.get(name, 0) or 0) <= 0]
    return {
        "ready": not missing,
        "required": RELATION_CHAIN_REQUIRED,
        "missing": missing,
        "counts": {name: int(rel_counts.get(name, 0) or 0) for name in RELATION_CHAIN_REQUIRED},
    }


def drop_graph_if_exists(session: Any, graph_name: str) -> None:
    session.run(
        """
        CALL gds.graph.exists($graph_name)
        YIELD exists
        WITH exists
        WHERE exists
        CALL gds.graph.drop($graph_name, false)
        YIELD graphName
        RETURN graphName
        """,
        {"graph_name": graph_name},
    ).consume()


def build_projection(
    session: Any,
    cfg: HotspotConfig,
    graph_name: str,
    strategy: ProjectionStrategy,
    start: int,
    end: int,
) -> dict[str, int]:
    log_progress(
        "projection",
        "start projection build",
        graph_name=graph_name,
        strategy=strategy.name,
        start=start,
        end=end,
    )
    python_group_projection = strategy.name.startswith("project_topic_signature") or strategy.name.startswith("project_broad_subject")
    if python_group_projection:
        classifier = infer_project_topic_signature if strategy.name.startswith("project_topic_signature") else infer_project_broad_subject
        group_cap = FAST_ATTRIBUTE_GROUP_CAP if strategy.name.endswith("_fast") else ATTRIBUTE_GROUP_CAP
        node_ids, rel_rows = _collect_python_group_projection(session, start, end, classifier, group_cap)
        if cfg.max_edges > 0:
            rel_rows = rel_rows[: cfg.max_edges]
        node_query = "UNWIND $node_ids AS id RETURN id"
        rel_query = (
            "UNWIND $rel_rows AS rel "
            "RETURN toInteger(rel.source) AS source, toInteger(rel.target) AS target, toFloat(rel.weight) AS weight"
        )
        projection_params = {"graph_name": graph_name, "node_ids": node_ids, "rel_rows": rel_rows}
    else:
        node_query = strategy.node_query_template.format(start_year=start, end_year=end)
        rel_query_base = strategy.rel_query_template.format(start_year=start, end_year=end)

        # 统一关系采样上限，避免大图投影在关系侧失控。
        if cfg.max_edges > 0:
            rel_query = (
                "CALL { "
                + rel_query_base
                + f" }} RETURN source, target, weight LIMIT {cfg.max_edges}"
            )
        else:
            rel_query = rel_query_base
        projection_params = {"graph_name": graph_name}

    drop_graph_if_exists(session, graph_name)

    projection_query = f"""
    CALL {{
        CALL {{
            {node_query}
        }}
        RETURN id AS source, null AS target, 0.0 AS weight, true AS node_only
        UNION ALL
        CALL {{
            {rel_query}
        }}
        RETURN source AS source, target AS target, coalesce(weight, 1.0) AS weight, false AS node_only
    }}
    WITH gds.graph.project(
        $graph_name,
        source,
        target,
        CASE
            WHEN node_only THEN {{}}
            ELSE {{
                relationshipType: 'RELATED',
                relationshipProperties: {{weight: toFloat(weight)}}
            }}
        END,
        {{readConcurrency: 4}}
    ) AS g
    RETURN g.nodeCount AS nodeCount, g.relationshipCount AS relationshipCount
    """

    try:
        row = session.run(
            projection_query,
            projection_params,
        ).single()
    except Neo4jError as exc:
        # 兼容旧版 GDS，避免升级窗口期功能中断。
        print(f"[WARN] 新版 Cypher 投影失败，回退旧写法: {exc}")
        row = session.run(
            """
            CALL gds.graph.project.cypher(
                $graph_name,
                $node_query,
                $rel_query,
                {validateRelationships: false}
            )
            YIELD nodeCount, relationshipCount
            RETURN nodeCount, relationshipCount
            """,
            {
                "graph_name": graph_name,
                "node_query": node_query,
                "rel_query": rel_query,
                "node_ids": projection_params.get("node_ids"),
                "rel_rows": projection_params.get("rel_rows"),
            },
        ).single()

    if not row:
        raise RuntimeError(f"图投影失败: {graph_name}")

    stats = {
        "nodeCount": int(row["nodeCount"]),
        "relationshipCount": int(row["relationshipCount"]),
    }
    log_progress(
        "projection",
        "projection ready",
        graph_name=graph_name,
        nodeCount=stats["nodeCount"],
        relationshipCount=stats["relationshipCount"],
    )
    return stats


def select_strategy(
    session: Any,
    cfg: HotspotConfig,
    windows: list[tuple[int, int]],
    graph_profile: dict[str, Any],
) -> tuple[ProjectionStrategy, list[dict[str, Any]], dict[str, Any]]:
    catalog = build_strategy_catalog()
    ordered = catalog
    relation_gate = _relation_chain_readiness(graph_profile)

    catalog_by_name = {item.name: item for item in catalog}

    if cfg.preferred_strategy != "auto":
        preferred = [item for item in catalog if item.name == cfg.preferred_strategy]
        if preferred:
            fast_fallback_names = [
                "project_topic_signature_fast",
                "project_topic_signature",
                "project_broad_subject_fast",
                "project_broad_subject",
                "project_subject_code_fast",
                "project_subject_code",
                "project_guide_name_fast",
                "project_guide_name",
                "project_department",
                "project_office",
                "topic_template",
            ]
            fast_fallbacks = [
                catalog_by_name[name]
                for name in fast_fallback_names
                if name in catalog_by_name and name != preferred[0].name
            ]
            ordered = preferred + fast_fallbacks
    else:
        attrs = [
            catalog_by_name["project_topic_signature_fast"],
            catalog_by_name["project_topic_signature"],
            catalog_by_name["project_broad_subject_fast"],
            catalog_by_name["project_broad_subject"],
            catalog_by_name["project_subject_code_fast"],
            catalog_by_name["project_subject_code"],
            catalog_by_name["project_guide_name_fast"],
            catalog_by_name["project_guide_name"],
            catalog_by_name["project_department"],
            catalog_by_name["project_office"],
            catalog_by_name["topic_template"],
        ]
        relation_first = [catalog_by_name["relation_chain_priority"]]
        ordered = attrs + relation_first if relation_gate["ready"] else attrs

    attempts: list[dict[str, Any]] = []
    for strategy in ordered:
        log_progress("strategy", "try strategy", strategy=strategy.name)
        window_stats: list[dict[str, Any]] = []
        try:
            for start, end in windows:
                if strategy.name.startswith("project_topic_signature"):
                    _, stats = aggregate_projects_by_topic_signature(session, start, end, cfg.top_community_count)
                else:
                    graph_name = f"hotspot_probe_{strategy.name}_{start}_{end}_{uuid.uuid4().hex[:6]}"
                    stats = build_projection(session, cfg, graph_name, strategy, start, end)
                    drop_graph_if_exists(session, graph_name)
                window_stats.append({
                    "window": {"start": start, "end": end},
                    "nodeCount": stats["nodeCount"],
                    "relationshipCount": stats["relationshipCount"],
                })

            attempts.append({"strategy": strategy.name, "windows": window_stats})
            if all(item["nodeCount"] > 0 and item["relationshipCount"] > 0 for item in window_stats):
                log_progress(
                    "strategy",
                    "selected strategy",
                    strategy=strategy.name,
                    description=strategy.description,
                )
                return strategy, window_stats, {
                    "preferredMode": cfg.preferred_strategy,
                    "relationChainGate": relation_gate,
                    "fallbackToAttribute": strategy.name != "relation_chain_priority",
                    "orderedStrategies": [item.name for item in ordered],
                    "selectedStrategy": strategy.name,
                }
        except Exception as exc:
            log_progress("strategy", "strategy failed", strategy=strategy.name, error=str(exc))
            attempts.append({"strategy": strategy.name, "error": str(exc), "windows": window_stats})
            continue

    raise RuntimeError(f"未找到可用的热点迁移策略，尝试记录: {attempts}")


def run_community_detection(session: Any, graph_name: str, prefer_louvain: bool = False) -> tuple[list[dict[str, int]], str]:
    log_progress(
        "community",
        "start community detection",
        graph_name=graph_name,
        preferred="louvain" if prefer_louvain else "leiden",
    )
    leiden_queries = [
        """
        CALL gds.leiden.stream($graph_name, {relationshipWeightProperty: 'weight'})
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
        """
        CALL gds.leiden.stream($graph_name)
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
    ]

    last_error: Exception | None = None
    louvain_queries = [
        """
        CALL gds.louvain.stream($graph_name, {relationshipWeightProperty: 'weight'})
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
        """
        CALL gds.louvain.stream($graph_name)
        YIELD nodeId, communityId
        RETURN nodeId, communityId
        """,
    ]

    louvain_error: Exception | None = None
    ordered_queries = louvain_queries + leiden_queries if prefer_louvain else leiden_queries + louvain_queries

    for query in ordered_queries:
        try:
            rows = [
                {"nodeId": int(r["nodeId"]), "communityId": int(r["communityId"])}
                for r in session.run(query, {"graph_name": graph_name})
            ]
            algorithm = "louvain" if "louvain" in query.lower() else "leiden"
            log_progress(
                "community",
                "community detection complete",
                graph_name=graph_name,
                algorithm=algorithm,
                assignments=len(rows),
            )
            return rows, algorithm
        except Exception as exc:
            if "leiden" in query.lower():
                last_error = exc
            else:
                louvain_error = exc
            continue

    raise RuntimeError(f"社区检测执行失败: leiden={last_error}; louvain={louvain_error}")


def fetch_node_names(session: Any, node_ids: list[int], strategy: ProjectionStrategy) -> dict[int, str]:
    if not node_ids:
        return {}

    if strategy.name.startswith("project_topic_signature"):
        rows = session.run(
            """
            UNWIND $ids AS nid
            MATCH (n:Project)
            WHERE id(n) = nid
            RETURN nid AS node_id,
                   n.projectName AS project_name,
                   n.`项目简介` AS project_intro,
                   n.`研究内容` AS research_content,
                   n.guideName AS guide_name
            """,
            {"ids": node_ids},
        )
        result: dict[int, str] = {}
        for row in rows:
            result[int(row["node_id"])] = infer_project_topic_signature(
                _normalize_project_text(
                    row["project_name"],
                    row["project_intro"],
                    row["research_content"],
                    row["guide_name"],
                )
            )
        return result

    if strategy.name.startswith("project_broad_subject"):
        rows = session.run(
            """
            UNWIND $ids AS nid
            MATCH (n:Project)
            WHERE id(n) = nid
            RETURN nid AS node_id,
                   n.projectName AS project_name,
                   n.`项目简介` AS project_intro,
                   n.`研究内容` AS research_content,
                   n.guideName AS guide_name
            """,
            {"ids": node_ids},
        )
        result: dict[int, str] = {}
        for row in rows:
            result[int(row["node_id"])] = infer_project_broad_subject(
                _normalize_project_text(
                    row["project_name"],
                    row["project_intro"],
                    row["research_content"],
                    row["guide_name"],
                )
            )
        return result

    if strategy.name.startswith("project_subject_code"):
        query = f"""
            UNWIND $ids AS nid
            MATCH (n:Project)
            WHERE id(n) = nid
            RETURN nid AS node_id,
                   {_subject_code_expr("n")} AS subject_code,
                   coalesce(n.projectName, n.guideName, toString(id(n))) AS fallback_name
        """
        rows = session.run(query, {"ids": node_ids})
        result: dict[int, str] = {}
        for row in rows:
            node_id = int(row["node_id"])
            subject_code = str(row["subject_code"] or "").strip()
            fallback_name = str(row["fallback_name"] or node_id)
            result[node_id] = format_subject_display(subject_code) or fallback_name
        return result

    fields = [
        *strategy.node_label_fields,
        "name",
        "title",
        "projectName",
        "guideName",
        "department",
        "office",
        "display_name_zh",
        "label_zh",
        "基金名称",
    ]
    label_exprs: list[str] = []
    for field in fields:
        if field in {"基金名称"}:
            label_exprs.append(f"n.`{field}`")
        else:
            label_exprs.append(f"n.{field}")

    label_exprs.append("toString(id(n))")

    query = """
        UNWIND $ids AS nid
        MATCH (n)
        WHERE id(n) = nid
        RETURN nid AS node_id,
               coalesce(
                   {label_exprs}
               ) AS node_name
        """.replace("{label_exprs}", ",\n                   ".join(label_exprs))

    rows = session.run(
        query,
        {"ids": node_ids},
    )
    return {int(r["node_id"]): str(r["node_name"]) for r in rows}


def summarize_communities(
    session: Any,
    assignments: list[dict[str, int]],
    top_community_count: int,
    strategy: ProjectionStrategy,
) -> dict[int, dict[str, Any]]:
    log_progress(
        "community",
        "summarize communities",
        strategy=strategy.name,
        assignments=len(assignments),
        topCommunityCount=top_community_count,
    )
    comm_map: dict[int, set[int]] = {}
    for row in assignments:
        comm_map.setdefault(row["communityId"], set()).add(row["nodeId"])

    all_node_ids = sorted({row["nodeId"] for row in assignments})
    name_map = fetch_node_names(session, all_node_ids, strategy)

    summary: dict[int, dict[str, Any]] = {}
    ranked = sorted(comm_map.items(), key=lambda item: len(item[1]), reverse=True)

    for idx, (cid, node_set) in enumerate(ranked):
        names = [name_map.get(nid, str(nid)) for nid in sorted(node_set)]
        keyword_set = sorted({str(name).strip() for name in names if str(name).strip()})
        summary[cid] = {
            "communityId": cid,
            "size": len(node_set),
            "nodeIds": sorted(node_set),
            "keywordSet": keyword_set,
            "topKeywords": names[:8],
            "rank": idx + 1,
            "isTopCommunity": idx < top_community_count,
        }

    return summary


def _split_display_name(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "", ""
    if "-" in value:
        left, right = value.split("-", 1)
        return left.strip(), right.strip()
    return "", value


def _community_similarity_score(base: dict[str, Any], candidate: dict[str, Any]) -> int:
    base_name = _community_display_name(base)
    cand_name = _community_display_name(candidate)
    if base_name == cand_name:
        return 10000

    base_code, base_label = _split_display_name(base_name)
    cand_code, cand_label = _split_display_name(cand_name)
    score = 0
    if base_label and cand_label and base_label == cand_label:
        score += 3000
    if base_code and cand_code and base_code == cand_code:
        score += 1200

    base_keywords = set(str(x).strip() for x in (base.get("keywordSet", []) or []) if str(x).strip())
    cand_keywords = set(str(x).strip() for x in (candidate.get("keywordSet", []) or []) if str(x).strip())
    overlap = len(base_keywords & cand_keywords)
    if overlap > 0:
        score += 200 * overlap
    return score


def _merge_community_bucket(items: list[dict[str, Any]], merged_id: int) -> dict[str, Any]:
    node_ids: list[int] = []
    keyword_values: list[str] = []
    keyword_counter: Counter[str] = Counter()
    source_ids: list[int] = []

    for item in items:
        node_ids.extend(int(node_id) for node_id in (item.get("nodeIds", []) or []))
        source_ids.append(int(item.get("communityId", 0) or 0))
        display_name = _community_display_name(item)
        if display_name:
            keyword_counter[display_name] += max(1, int(item.get("size", 0) or 0))
            keyword_values.append(display_name)
        for keyword in item.get("topKeywords", []) or []:
            text = str(keyword).strip()
            if not text:
                continue
            keyword_counter[text] += 1
            keyword_values.append(text)
        for keyword in item.get("keywordSet", []) or []:
            text = str(keyword).strip()
            if not text:
                continue
            keyword_values.append(text)

    ordered_keywords = [name for name, _ in keyword_counter.most_common(8)]
    merged = {
        "communityId": int(merged_id),
        "size": len(sorted(set(node_ids))),
        "nodeIds": sorted(set(node_ids)),
        "keywordSet": sorted({text for text in keyword_values if text}),
        "topKeywords": ordered_keywords or _dedup_keywords(keyword_values, limit=8),
        "mergedFromCommunityIds": sorted(source_ids),
        "mergedFromCount": len(items),
    }
    return merged


def force_merge_communities(
    communities: dict[int, dict[str, Any]],
    top_community_count: int,
    target_min_size: int = FORCED_COMMUNITY_TARGET_MIN,
    target_max_size: int = FORCED_COMMUNITY_TARGET_MAX,
    target_ideal_size: int = FORCED_COMMUNITY_TARGET_IDEAL,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    ordered = sorted(
        communities.values(),
        key=lambda item: (-int(item.get("size", 0) or 0), _community_display_name(item)),
    )
    if not ordered:
        return {}, {
            "enabled": True,
            "targetMinSize": int(target_min_size),
            "targetMaxSize": int(target_max_size),
            "targetIdealSize": int(target_ideal_size),
            "rawCommunityCount": 0,
            "mergedCommunityCount": 0,
        }

    remaining = ordered[:]
    buckets: list[list[dict[str, Any]]] = []

    while remaining:
        seed = remaining.pop(0)
        bucket = [seed]
        bucket_size = int(seed.get("size", 0) or 0)

        if bucket_size < target_min_size:
            while remaining and bucket_size < target_min_size:
                best_idx = -1
                best_key: tuple[int, int, int, int] | None = None
                for idx, candidate in enumerate(remaining):
                    candidate_size = int(candidate.get("size", 0) or 0)
                    merged_size = bucket_size + candidate_size
                    overshoot = max(0, merged_size - target_max_size)
                    distance = abs(target_ideal_size - merged_size)
                    similarity = max(_community_similarity_score(item, candidate) for item in bucket)
                    candidate_key = (
                        -overshoot,
                        similarity,
                        -distance,
                        -candidate_size,
                    )
                    if best_key is None or candidate_key > best_key:
                        best_key = candidate_key
                        best_idx = idx

                if best_idx < 0:
                    break

                selected = remaining.pop(best_idx)
                bucket.append(selected)
                bucket_size += int(selected.get("size", 0) or 0)

                if bucket_size >= target_min_size:
                    break

        buckets.append(bucket)

    if len(buckets) > 1:
        too_small = [idx for idx, bucket in enumerate(buckets) if sum(int(item.get("size", 0) or 0) for item in bucket) < target_min_size]
        for bucket_idx in reversed(too_small):
            if len(buckets) <= 1:
                break
            bucket = buckets.pop(bucket_idx)
            bucket_size = sum(int(item.get("size", 0) or 0) for item in bucket)

            best_target_idx = 0
            best_target_key: tuple[int, int] | None = None
            for idx, target_bucket in enumerate(buckets):
                target_size = sum(int(item.get("size", 0) or 0) for item in target_bucket)
                merged_size = target_size + bucket_size
                overshoot = max(0, merged_size - target_max_size)
                similarity = max(
                    _community_similarity_score(left, right)
                    for left in bucket
                    for right in target_bucket
                ) if target_bucket else 0
                candidate_key = (-overshoot, similarity)
                if best_target_key is None or candidate_key > best_target_key:
                    best_target_key = candidate_key
                    best_target_idx = idx

            buckets[best_target_idx].extend(bucket)

    merged_items = [
        _merge_community_bucket(bucket, idx + 1)
        for idx, bucket in enumerate(buckets)
    ]
    merged_items.sort(key=lambda item: int(item.get("size", 0) or 0), reverse=True)

    merged_summary: dict[int, dict[str, Any]] = {}
    for idx, item in enumerate(merged_items):
        community_id = idx + 1
        item["communityId"] = community_id
        item["rank"] = idx + 1
        item["isTopCommunity"] = idx < top_community_count
        merged_summary[community_id] = item

    return merged_summary, {
        "enabled": True,
        "targetMinSize": int(target_min_size),
        "targetMaxSize": int(target_max_size),
        "targetIdealSize": int(target_ideal_size),
        "rawCommunityCount": len(communities),
        "mergedCommunityCount": len(merged_summary),
    }


def build_migration(
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    min_overlap_count: int,
    min_jaccard: float,
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []

    for cid_a, info_a in comm_a.items():
        set_a = set(info_a.get("keywordSet", []))
        basis = "keywordSet"
        if not set_a:
            set_a = {str(x) for x in info_a.get("nodeIds", [])}
            basis = "nodeIds"
        if not set_a:
            continue

        for cid_b, info_b in comm_b.items():
            set_b = set(info_b.get("keywordSet", []))
            if not set_b:
                set_b = {str(x) for x in info_b.get("nodeIds", [])}
            if not set_b:
                continue

            overlap = len(set_a & set_b)
            if overlap < min_overlap_count:
                continue

            jaccard = overlap / len(set_a | set_b)
            if jaccard < min_jaccard:
                continue

            weighted_overlap = overlap
            weighted_jaccard = jaccard
            source_size_metric = len(set_a)
            target_size_metric = len(set_b)

            # 快速主题直聚合模式下，每个簇通常只有一个主题标签。
            # 这里把边强度提升为两年该主题的项目规模，避免所有边都退化成 1。
            if (
                basis == "keywordSet"
                and len(set_a) == 1
                and len(set_b) == 1
                and next(iter(set_a)) == next(iter(set_b))
            ):
                source_comm_size = int(info_a.get("size", 0) or 0)
                target_comm_size = int(info_b.get("size", 0) or 0)
                weighted_overlap = max(1, min(source_comm_size, target_comm_size))
                weighted_jaccard = (
                    weighted_overlap / max(source_comm_size, target_comm_size)
                    if max(source_comm_size, target_comm_size) > 0
                    else 0.0
                )
                source_size_metric = source_comm_size
                target_size_metric = target_comm_size

            links.append(
                {
                    "source": str(cid_a),
                    "target": str(cid_b),
                    "overlap": int(weighted_overlap),
                    "jaccard": round(weighted_jaccard, 4),
                    "sourceSize": int(source_size_metric),
                    "targetSize": int(target_size_metric),
                    "basis": basis,
                }
            )

    links.sort(key=lambda x: (x["overlap"], x["jaccard"]), reverse=True)
    return links


def build_migration_with_fallback(
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    min_overlap_count: int,
    min_jaccard: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    attempts = [
        {"minOverlapCount": int(min_overlap_count), "minJaccard": float(min_jaccard), "reason": "configured"},
        {"minOverlapCount": 1, "minJaccard": 0.005, "reason": "fallback_relaxed_jaccard"},
        {"minOverlapCount": 1, "minJaccard": 0.0, "reason": "fallback_no_jaccard"},
    ]

    dedup: list[dict[str, Any]] = []
    seen: set[tuple[int, float]] = set()
    for item in attempts:
        key = (int(item["minOverlapCount"]), float(item["minJaccard"]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)

    trace: list[dict[str, Any]] = []
    for item in dedup:
        log_progress(
            "migration",
            "try migration threshold",
            minOverlapCount=int(item["minOverlapCount"]),
            minJaccard=float(item["minJaccard"]),
            reason=str(item["reason"]),
        )
        links = build_migration(
            comm_a,
            comm_b,
            int(item["minOverlapCount"]),
            float(item["minJaccard"]),
        )
        trace.append(
            {
                "minOverlapCount": int(item["minOverlapCount"]),
                "minJaccard": float(item["minJaccard"]),
                "reason": str(item["reason"]),
                "linkCount": len(links),
            }
        )
        if links:
            log_progress(
                "migration",
                "migration links ready",
                linkCount=len(links),
                minOverlapCount=int(item["minOverlapCount"]),
                minJaccard=float(item["minJaccard"]),
            )
            return links, item, trace

    log_progress("migration", "no migration links found after fallback")
    return [], dedup[-1], trace


def generate_brief(
    cfg: HotspotConfig,
    comm_a: dict[int, dict[str, Any]],
    comm_b: dict[int, dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []

    top_a = sorted(comm_a.values(), key=lambda x: x["size"], reverse=True)[:3]
    top_b = sorted(comm_b.values(), key=lambda x: x["size"], reverse=True)[:3]

    lines.append(
        f"时间窗A({cfg.year_a_start}-{cfg.year_a_end})识别到 {len(comm_a)} 个主题簇，"
        f"时间窗B({cfg.year_b_start}-{cfg.year_b_end})识别到 {len(comm_b)} 个主题簇。"
    )

    if top_a:
        lines.append(
            "A窗头部簇关键词：" + "；".join(
                [f"C{c['communityId']}[{', '.join(c['topKeywords'][:3])}]" for c in top_a]
            )
        )

    if top_b:
        lines.append(
            "B窗头部簇关键词：" + "；".join(
                [f"C{c['communityId']}[{', '.join(c['topKeywords'][:3])}]" for c in top_b]
            )
        )

    if links:
        top_links = links[:3]
        lines.append(
            "主要迁移流：" + "；".join(
                [
                    f"C{l['source']}→C{l['target']}"
                    f"(overlap={l['overlap']}, jaccard={l['jaccard']})"
                    for l in top_links
                ]
            )
        )
    else:
        lines.append("未识别到满足阈值的迁移流，建议在代码默认参数中适当降低 overlap/jaccard 阈值。")

    return lines


def ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _dedup_keywords(values: list[Any], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _extract_community_id(raw_id: str | None, prefix: str) -> int | None:
    if not raw_id:
        return None
    value = str(raw_id)
    if value.startswith(prefix):
        value = value[len(prefix):]
    try:
        return int(value)
    except Exception:
        return None


def _period_label(window: dict[str, Any], fallback: str) -> str:
    start = window.get("start")
    end = window.get("end")
    if start and end and start == end:
        return f"{start}年"
    if start and end:
        return f"{start}-{end}年"
    if start:
        return f"{start}年"
    return fallback


def _community_display_name(item: dict[str, Any]) -> str:
    keywords = _dedup_keywords(item.get("topKeywords", []) or item.get("keywordSet", []), limit=3)
    if keywords:
        return keywords[0]
    community_id = item.get("communityId")
    return f"热点分组{community_id}" if community_id is not None else "未命名方向"


def _graph_scale_text(projection: dict[str, Any]) -> str:
    return (
        f"{int(projection.get('nodeCount', 0) or 0)} 个项目节点，"
        f"{int(projection.get('relationshipCount', 0) or 0)} 条项目关联"
    )


def _build_group_rows(items: list[dict[str, Any]], period_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        name = _community_display_name(item)
        keywords = _dedup_keywords(item.get("topKeywords", []) or item.get("keywordSet", []), limit=5)
        size = int(item.get("size", 0) or 0)
        rows.append(
            {
                "rank": int(item.get("rank", 0) or 0),
                "name": name,
                "keywords": keywords,
                "projectCount": size,
                "description": f"{period_label}中，该方向形成了约 {size} 个项目构成的重点分组。",
            }
        )
    return rows


def _build_change_rows(
    links: list[dict[str, Any]],
    comm_map_a: dict[int, dict[str, Any]],
    comm_map_b: dict[int, dict[str, Any]],
    end_period_label: str,
    top_links: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        source_id = _extract_community_id(link.get("source"), "A-")
        target_id = _extract_community_id(link.get("target"), "B-")
        source_comm = comm_map_a.get(source_id or -1, {})
        target_comm = comm_map_b.get(target_id or -1, {})
        source_name = _community_display_name(source_comm) if source_comm else "未命名方向"
        target_name = _community_display_name(target_comm) if target_comm else "未命名方向"
        dedup_key = (source_name, target_name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        overlap = int(link.get("value", 0) or 0)
        if source_name == target_name:
            description = f"“{source_name}”在 {end_period_label} 继续保持活跃，属于延续性较强的方向。"
        else:
            description = f"关注重点由“{source_name}”延伸到“{target_name}”，说明研究关注点出现了转移。"

        if overlap > 1:
            description += f" 这种变化在样本中出现了 {overlap} 次关联。"

        rows.append(
            {
                "rank": len(rows) + 1,
                "from": source_name,
                "to": target_name,
                "description": description,
            }
        )
        if len(rows) >= top_links:
            break
    return rows


def _build_friendly_summary(
    start_period_label: str,
    end_period_label: str,
    window_a: list[dict[str, Any]],
    window_b: list[dict[str, Any]],
    top_window_a: list[dict[str, Any]],
    top_window_b: list[dict[str, Any]],
    key_changes: list[dict[str, Any]],
) -> list[str]:
    top_a_names = [row["name"] for row in _build_group_rows(top_window_a[:3], start_period_label)]
    top_b_names = [row["name"] for row in _build_group_rows(top_window_b[:3], end_period_label)]

    lines = [
        f"本次对 {start_period_label} 和 {end_period_label} 的项目关系做了对比分析，"
        f"{start_period_label}识别出 {len(window_a)} 个热点分组，{end_period_label}识别出 {len(window_b)} 个热点分组。"
    ]
    if top_a_names:
        lines.append(f"{start_period_label}较受关注的方向主要包括：{'、'.join(top_a_names)}。")
    if top_b_names:
        lines.append(f"{end_period_label}较受关注的方向主要包括：{'、'.join(top_b_names)}。")
    if key_changes:
        lines.append(key_changes[0]["description"])
    else:
        lines.append("本次对比中没有识别出特别明显的重点领域变化趋势。")
    return lines
    value = str(raw_id)
    if value.startswith(prefix):
        value = value[len(prefix):]
    try:
        return int(value)
    except Exception:
        return None


def build_lite_result(
    result: dict[str, Any],
    output_path: str,
    top_communities: int = DEFAULT_LITE_TOP_COMMUNITIES,
    top_links: int = DEFAULT_LITE_TOP_LINKS,
) -> dict[str, Any]:
    meta = result.get("meta", {}) or {}
    projection = result.get("projection", {}) or {}
    communities = result.get("communities", {}) or {}
    sankey = result.get("sankey", {}) or {}
    window_a = communities.get("windowA", []) or []
    window_b = communities.get("windowB", []) or []
    links = sankey.get("links", []) or []

    top_window_a = sorted(window_a, key=lambda x: int(x.get("size", 0) or 0), reverse=True)[:top_communities]
    top_window_b = sorted(window_b, key=lambda x: int(x.get("size", 0) or 0), reverse=True)[:top_communities]
    top_links_list = sorted(links, key=lambda x: float(x.get("value", 0) or 0), reverse=True)[:top_links]

    comm_map_a = {int(item.get("communityId")): item for item in window_a if item.get("communityId") is not None}
    comm_map_b = {int(item.get("communityId")): item for item in window_b if item.get("communityId") is not None}
    projection_a = projection.get("windowA", {}) or {}
    projection_b = projection.get("windowB", {}) or {}
    start_period_label = _period_label(meta.get("windowA", {}) or {}, "起始年份")
    end_period_label = _period_label(meta.get("windowB", {}) or {}, "对比年份")
    key_changes = _build_change_rows(top_links_list, comm_map_a, comm_map_b, end_period_label, top_links)
    top_groups_a = _build_group_rows(top_window_a, start_period_label)
    top_groups_b = _build_group_rows(top_window_b, end_period_label)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceOutputPath": output_path,
        "summary": {
            "cards": [
                {"label": f"{start_period_label}热点分组数", "value": len(window_a)},
                {"label": f"{end_period_label}热点分组数", "value": len(window_b)},
                {"label": "重点领域方向", "value": len(key_changes)},
            ],
        },
        "overview": {
            "startPeriod": start_period_label,
            "comparisonPeriod": end_period_label,
            "analysisMethod": "先按项目之间的关联关系做分组，再比较两个年份里哪些方向更集中、哪些方向发生了变化。",
            "graphScale": [
                {"label": f"{start_period_label}分析图规模", "value": _graph_scale_text(projection_a)},
                {"label": f"{end_period_label}分析图规模", "value": _graph_scale_text(projection_b)},
            ],
        },
        "topGroups": {
            start_period_label: top_groups_a,
            end_period_label: top_groups_b,
        },
        "keyChanges": key_changes,
        "insightDraft": _build_friendly_summary(
            start_period_label,
            end_period_label,
            window_a,
            window_b,
            top_window_a,
            top_window_b,
            key_changes,
        ),
    }


def build_companion_output_paths(output_path: str) -> dict[str, str]:
    path = Path(output_path)
    stem = path.stem
    return {
        "cluster_nodes_html": str(path.with_name(f"{stem}.cluster_nodes.html")),
    }


def run(cfg: HotspotConfig) -> dict[str, Any]:
    log_progress(
        "run",
        "start hotspot migration run",
        yearA=f"{cfg.year_a_start}-{cfg.year_a_end}",
        yearB=f"{cfg.year_b_start}-{cfg.year_b_end}",
        preferredStrategy=cfg.preferred_strategy,
    )
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    run_suffix = uuid.uuid4().hex[:8]
    graph_a = f"hotspot_{cfg.year_a_start}_{cfg.year_a_end}_{run_suffix}"
    graph_b = f"hotspot_{cfg.year_b_start}_{cfg.year_b_end}_{run_suffix}"
    stale_graph_a = f"hotspot_{cfg.year_a_start}_{cfg.year_a_end}"
    stale_graph_b = f"hotspot_{cfg.year_b_start}_{cfg.year_b_end}"

    try:
        with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
            log_progress("run", "verify real data snapshot")
            data_source = verify_real_data_snapshot(session, cfg)
            log_progress(
                "run",
                "real data snapshot checked",
                verified=bool(data_source.get("verified", False)),
            )

            log_progress("run", "collect graph profile")
            graph_profile = collect_dual_layer_profile(session)
            log_progress(
                "run",
                "graph profile collected",
                overallReady=bool(graph_profile.get("overallReady", False)),
            )
            if cfg.require_real_data and not bool(data_source.get("verified", False)):
                raise RuntimeError(f"真实数据校验失败: {data_source}")

            # 清理旧版固定命名遗留图，避免 catalog 残留干扰。
            log_progress("run", "drop stale graphs", graphA=stale_graph_a, graphB=stale_graph_b)
            drop_graph_if_exists(session, stale_graph_a)
            drop_graph_if_exists(session, stale_graph_b)

            log_progress("run", "select projection strategy")
            selected_strategy, probe_windows, strategy_selection = select_strategy(
                session,
                cfg,
                [
                    (cfg.year_a_start, cfg.year_a_end),
                    (cfg.year_b_start, cfg.year_b_end),
                ],
                graph_profile,
            )
            log_progress(
                "run",
                "projection strategy selected",
                strategy=selected_strategy.name,
            )

            if selected_strategy.name.startswith("project_topic_signature"):
                community_algorithm = "direct_topic_grouping"
                log_progress("run", "aggregate topics directly for window A")
                comm_a, proj_a = aggregate_projects_by_topic_signature(
                    session,
                    cfg.year_a_start,
                    cfg.year_a_end,
                    cfg.top_community_count,
                )
                log_progress("run", "aggregate topics directly for window B")
                comm_b, proj_b = aggregate_projects_by_topic_signature(
                    session,
                    cfg.year_b_start,
                    cfg.year_b_end,
                    cfg.top_community_count,
                )
                if proj_a["nodeCount"] == 0 or proj_b["nodeCount"] == 0:
                    raise RuntimeError("至少一个时间窗聚合为空，请检查模板或年份区间")
                merge_meta_a = {
                    "enabled": False,
                    "mode": "direct_topic_grouping",
                    "rawCommunityCount": len(comm_a),
                    "mergedCommunityCount": len(comm_a),
                }
                merge_meta_b = {
                    "enabled": False,
                    "mode": "direct_topic_grouping",
                    "rawCommunityCount": len(comm_b),
                    "mergedCommunityCount": len(comm_b),
                }
            else:
                log_progress("run", "build projection for window A", graph=graph_a)
                proj_a = build_projection(session, cfg, graph_a, selected_strategy, cfg.year_a_start, cfg.year_a_end)
                log_progress("run", "build projection for window B", graph=graph_b)
                proj_b = build_projection(session, cfg, graph_b, selected_strategy, cfg.year_b_start, cfg.year_b_end)

                if proj_a["nodeCount"] == 0 or proj_b["nodeCount"] == 0:
                    raise RuntimeError("至少一个时间窗投影为空，请检查模板或年份区间")

                prefer_louvain = max(proj_a["relationshipCount"], proj_b["relationshipCount"]) >= cfg.community_edge_threshold
                community_algorithm = "louvain" if prefer_louvain else "leiden"
                log_progress("run", "run community detection for window A", graph=graph_a, algorithm=community_algorithm)
                assign_a, algorithm_a = run_community_detection(session, graph_a, prefer_louvain=prefer_louvain)
                log_progress("run", "run community detection for window B", graph=graph_b, algorithm=community_algorithm)
                assign_b, algorithm_b = run_community_detection(session, graph_b, prefer_louvain=prefer_louvain)
                community_algorithm = algorithm_a if algorithm_a == algorithm_b else f"{algorithm_a}/{algorithm_b}"

                log_progress("run", "summarize communities for window A")
                raw_comm_a = summarize_communities(session, assign_a, cfg.top_community_count, selected_strategy)
                log_progress("run", "summarize communities for window B")
                raw_comm_b = summarize_communities(session, assign_b, cfg.top_community_count, selected_strategy)
                log_progress("run", "force merge communities for window A", rawCount=len(raw_comm_a))
                comm_a, merge_meta_a = force_merge_communities(raw_comm_a, cfg.top_community_count)
                log_progress("run", "force merge communities for window B", rawCount=len(raw_comm_b))
                comm_b, merge_meta_b = force_merge_communities(raw_comm_b, cfg.top_community_count)

            log_progress("run", "build migration links")
            links, effective_threshold, threshold_attempts = build_migration_with_fallback(
                comm_a,
                comm_b,
                cfg.min_overlap_count,
                cfg.min_jaccard,
            )
            log_progress("run", "generate insight draft", linkCount=len(links))
            brief = generate_brief(cfg, comm_a, comm_b, links)

        result = {
            "meta": {
                "database": cfg.database,
                "analysisMode": selected_strategy.name,
                "analysisDescription": selected_strategy.description,
                "communityAlgorithm": community_algorithm,
                "windowA": {"start": cfg.year_a_start, "end": cfg.year_a_end},
                "windowB": {"start": cfg.year_b_start, "end": cfg.year_b_end},
                "threshold": {
                    "minOverlapCount": cfg.min_overlap_count,
                    "minJaccard": cfg.min_jaccard,
                    "maxEdges": cfg.max_edges,
                },
                "effectiveThreshold": {
                    "minOverlapCount": int(effective_threshold["minOverlapCount"]),
                    "minJaccard": float(effective_threshold["minJaccard"]),
                    "reason": str(effective_threshold["reason"]),
                },
                "thresholdAttempts": threshold_attempts,
                "probeWindows": probe_windows,
                "strategySelection": strategy_selection,
                "dataSource": data_source,
                "graphProfile": graph_profile,
                "communityPostprocess": {
                    "enabled": True,
                    "targetMinSize": FORCED_COMMUNITY_TARGET_MIN,
                    "targetMaxSize": FORCED_COMMUNITY_TARGET_MAX,
                    "targetIdealSize": FORCED_COMMUNITY_TARGET_IDEAL,
                    "windowA": merge_meta_a,
                    "windowB": merge_meta_b,
                },
            },
            "projection": {
                "windowA": proj_a,
                "windowB": proj_b,
            },
            "communities": {
                "windowA": sorted(comm_a.values(), key=lambda x: x["rank"]),
                "windowB": sorted(comm_b.values(), key=lambda x: x["rank"]),
            },
            "sankey": {
                "nodes": [
                    *[
                        {"id": f"A-{c['communityId']}", "label": f"A-C{c['communityId']}", "size": c["size"]}
                        for c in sorted(comm_a.values(), key=lambda x: x["rank"])
                    ],
                    *[
                        {"id": f"B-{c['communityId']}", "label": f"B-C{c['communityId']}", "size": c["size"]}
                        for c in sorted(comm_b.values(), key=lambda x: x["rank"])
                    ],
                ],
                "links": [
                    {
                        "source": f"A-{l['source']}",
                        "target": f"B-{l['target']}",
                        "value": l["overlap"],
                        "jaccard": l["jaccard"],
                    }
                    for l in links
                ],
            },
            "insightDraft": brief,
        }
        log_progress(
            "run",
            "run complete",
            communityCountA=len(comm_a),
            communityCountB=len(comm_b),
            linkCount=len(links),
        )
        return result
    finally:
        try:
            log_progress("cleanup", "drop temporary graphs", graphA=graph_a, graphB=graph_b)
            with driver.session(database=cfg.database, **SESSION_KWARGS) as session:
                drop_graph_if_exists(session, graph_a)
                drop_graph_if_exists(session, graph_b)
        except Exception as exc:
            print(f"[WARN] Step2 清理临时图失败: {exc}")
        driver.close()


def main() -> int:
    try:
        log_progress("main", "build config")
        cfg = build_config()
        log_progress("main", "config ready", output=cfg.output_path, preferredStrategy=cfg.preferred_strategy)
    except Exception as exc:
        print(f"[ERROR] 配置错误: {exc}")
        return 2

    try:
        result = run(cfg)
        log_progress("main", "ensure output directory", output=cfg.output_path)
        ensure_output_dir(cfg.output_path)
        log_progress("main", "write output json", output=cfg.output_path)
        with open(cfg.output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        companion_paths = build_companion_output_paths(cfg.output_path)
        lite_result = build_lite_result(result, cfg.output_path)

        from src.services.sandbox.hotspot_migration_cluster_node_builder import (
            build_cluster_node_html_from_result,
        )

        log_progress("main", "write cluster nodes html", output=companion_paths["cluster_nodes_html"])
        build_cluster_node_html_from_result(
            result,
            companion_paths["cluster_nodes_html"],
            lite_payload=lite_result,
        )

        print("[SUCCESS] 第二步完成：热点迁移最小闭环已跑通")
        print(f"[OUTPUT] {cfg.output_path}")
        print(f"[OUTPUT_CLUSTER_HTML] {companion_paths['cluster_nodes_html']}")
        for line in result.get("insightDraft", []):
            print(f"[INSIGHT] {line}")
        return 0
    except Neo4jError as exc:
        print(f"[ERROR] Neo4j 执行失败: {exc}")
        print("请检查 Step2 代码默认模板是否与图谱 schema 一致。")
        return 1
    except Exception as exc:
        print(f"[ERROR] 运行失败: {exc}")
        print("请检查年份区间、模板 Cypher 与数据是否匹配。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
