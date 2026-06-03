#!/usr/bin/env python3
"""第三步：宏观研判规则引擎（最小闭环）。

能力：
1. 通用主题维度下的增长-转化风险识别（不限于某两个示例领域）。
2. 人才结构断层识别（人员规模、骨干占比、协作强度）。
3. 输出结构化 findings，供前端、报告生成和 LLM 研判复用。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


DEFAULT_YEAR_A_START = 2023
DEFAULT_YEAR_A_END = 2023
DEFAULT_YEAR_B_START = 2024
DEFAULT_YEAR_B_END = 2024
DEFAULT_TOPIC_EXPR = "coalesce(p.guideName, p.department, p.office, '<未知主题>')"
DEFAULT_MIN_APPLICATIONS = 20
DEFAULT_GROWTH_ALERT_THRESHOLD = 0.30
DEFAULT_LOW_CONVERSION_THRESHOLD = 0.05
DEFAULT_TALENT_MIN_PEOPLE = 8
DEFAULT_TALENT_BACKBONE_RATIO_THRESHOLD = 0.20
DEFAULT_TALENT_COLLAB_RATIO_THRESHOLD = 0.05
DEFAULT_TALENT_SENIOR_RATIO_THRESHOLD = 0.10
DEFAULT_SPIKE_GROWTH_THRESHOLD = 1.00
DEFAULT_SHRINK_ALERT_THRESHOLD = -0.35
DEFAULT_ZERO_OUTPUT_MIN_APPLICATIONS = 30
DEFAULT_CONVERSION_DROP_THRESHOLD = 0.03
DEFAULT_EMERGING_MIN_APPLICATIONS = 15
DEFAULT_EMERGING_GOOD_CONVERSION = 0.12
DEFAULT_PERSISTENT_LOW_CONVERSION_THRESHOLD = 0.04
DEFAULT_HIGH_CONVERSION_THRESHOLD = 0.15
DEFAULT_CONVERSION_RECOVERY_DELTA = 0.04
DEFAULT_OUTPUT_DECLINE_THRESHOLD = -0.20
DEFAULT_CONVERSION_GAP_FACTOR = 0.60
DEFAULT_BRIEF_MAX_FINDINGS = 3
DEFAULT_FAST_MODE = True
DEFAULT_FAST_PROJECT_LIMIT = 30000
DEFAULT_FAST_FOCUS_TOPICS = 80
DEFAULT_FAST_ENABLE_COLLAB = False

RULE_GROUP_MAP = {
    "low_conversion_after_growth": "risk",
    "application_growth_spike": "risk",
    "application_shrink_alert": "risk",
    "zero_output_high_heat": "risk",
    "conversion_drop_alert": "conversion",
    "conversion_efficiency_gap": "conversion",
    "output_decline_with_growth": "conversion",
    "persistent_low_conversion": "conversion",
    "high_growth_high_conversion": "opportunity",
    "emerging_topic_opportunity": "opportunity",
    "high_conversion_stable_scale": "opportunity",
    "conversion_recovery_signal": "opportunity",
    "talent_structure_gap": "talent",
    "senior_talent_shortage": "talent",
    "backbone_absent_risk": "talent",
    "collaboration_network_weak": "talent",
    "senior_backbone_imbalance": "talent",
}


@dataclass
class InsightConfig:
    uri: str
    user: str
    password: str
    database: str
    year_a_start: int
    year_a_end: int
    year_b_start: int
    year_b_end: int
    topic_expr: str
    min_applications: int
    growth_alert_threshold: float
    low_conversion_threshold: float
    talent_min_people: int
    talent_backbone_ratio_threshold: float
    talent_collab_ratio_threshold: float
    brief_max_findings: int
    fast_mode: bool
    fast_project_limit: int
    fast_focus_topics: int
    fast_enable_collab: bool
    output_path: str


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def getenv_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def build_config() -> InsightConfig:
    year_a_start = int(os.getenv("INSIGHT_YEAR_A_START", str(DEFAULT_YEAR_A_START)))
    year_a_end = int(os.getenv("INSIGHT_YEAR_A_END", str(DEFAULT_YEAR_A_END)))
    year_b_start = int(os.getenv("INSIGHT_YEAR_B_START", str(DEFAULT_YEAR_B_START)))
    year_b_end = int(os.getenv("INSIGHT_YEAR_B_END", str(DEFAULT_YEAR_B_END)))

    if year_a_end < year_a_start or year_b_end < year_b_start:
        raise ValueError("年份区间非法：结束年份不能小于开始年份")

    default_output = (
        f"debug_sandbox/macro_insight_{year_a_start}_{year_a_end}_"
        f"to_{year_b_start}_{year_b_end}.json"
    )

    return InsightConfig(
        uri=getenv_required("NEO4J_URI", "neo4j://192.168.0.198:7687"),
        user=getenv_required("NEO4J_USER", "neo4j"),
        password=getenv_required("NEO4J_PASSWORD"),
        database=getenv_required("NEO4J_DATABASE", "neo4j"),
        year_a_start=year_a_start,
        year_a_end=year_a_end,
        year_b_start=year_b_start,
        year_b_end=year_b_end,
        topic_expr=os.getenv("INSIGHT_TOPIC_EXPR", DEFAULT_TOPIC_EXPR),
        min_applications=DEFAULT_MIN_APPLICATIONS,
        growth_alert_threshold=DEFAULT_GROWTH_ALERT_THRESHOLD,
        low_conversion_threshold=DEFAULT_LOW_CONVERSION_THRESHOLD,
        talent_min_people=DEFAULT_TALENT_MIN_PEOPLE,
        talent_backbone_ratio_threshold=DEFAULT_TALENT_BACKBONE_RATIO_THRESHOLD,
        talent_collab_ratio_threshold=DEFAULT_TALENT_COLLAB_RATIO_THRESHOLD,
        brief_max_findings=int(os.getenv("INSIGHT_BRIEF_MAX_FINDINGS", str(DEFAULT_BRIEF_MAX_FINDINGS))),
        fast_mode=env_bool("INSIGHT_FAST_MODE", DEFAULT_FAST_MODE),
        fast_project_limit=max(1000, int(os.getenv("INSIGHT_FAST_PROJECT_LIMIT", str(DEFAULT_FAST_PROJECT_LIMIT)))),
        fast_focus_topics=max(10, int(os.getenv("INSIGHT_FAST_FOCUS_TOPICS", str(DEFAULT_FAST_FOCUS_TOPICS)))),
        fast_enable_collab=env_bool("INSIGHT_FAST_ENABLE_COLLAB", DEFAULT_FAST_ENABLE_COLLAB),
        output_path=os.getenv("INSIGHT_OUTPUT_PATH", default_output),
    )


def ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _topic_metrics_query(topic_expr: str, fast_mode: bool) -> str:
    limit_clause = "LIMIT $project_limit" if fast_mode else ""
    return f"""
    MATCH (p:Project)
    WITH p, toInteger(substring(toString(p.period), 0, 4)) AS y
    WHERE y >= $start_year AND y <= $end_year
    ORDER BY y DESC
    {limit_clause}
    WITH p, y, {topic_expr} AS topic
    OPTIONAL MATCH (p)-[:produces]->(o:Output)
    RETURN topic,
           count(DISTINCT p) AS applications,
           count(DISTINCT o) AS outputs
    """


def _talent_metrics_query(topic_expr: str, use_topic_filter: bool) -> str:
    topic_filter = "WHERE topic IN $topics" if use_topic_filter else ""
    return f"""
    MATCH (person:Person)-[:undertakes]->(p:Project)
    WITH person, p, toInteger(substring(toString(p.period), 0, 4)) AS y
    WHERE y >= $start_year AND y <= $end_year
    WITH person, p, {topic_expr} AS topic
    {topic_filter}
    WITH topic, collect(DISTINCT person) AS persons
    UNWIND persons AS person
    WITH topic,
         persons,
         coalesce(person.`职务`, '') AS title
    WITH topic,
         size(persons) AS people,
         sum(CASE WHEN title CONTAINS '副' THEN 1 ELSE 0 END) AS backbone,
         sum(CASE WHEN title CONTAINS '教授' OR title CONTAINS '研究员' OR title CONTAINS '高工' THEN 1 ELSE 0 END) AS senior
    RETURN topic, people, backbone, senior
    """


def _collab_metrics_query(topic_expr: str, use_topic_filter: bool) -> str:
    topic_expr_collab = topic_expr.replace("p.", "p1.")
    topic_filter = "AND topic IN $topics" if use_topic_filter else ""
    return f"""
    MATCH (a:Person)-[:undertakes]->(p1:Project)
    MATCH (b:Person)-[:undertakes]->(p2:Project)
    WHERE id(a) < id(b) AND (a)-[:collaborates_with]-(b)
    WITH a, b, p1, p2,
         toInteger(substring(toString(p1.period), 0, 4)) AS y1,
         toInteger(substring(toString(p2.period), 0, 4)) AS y2
    WHERE y1 >= $start_year AND y1 <= $end_year AND y2 >= $start_year AND y2 <= $end_year
    WITH {topic_expr_collab} AS topic, count(*) AS collabEdges
    WHERE 1 = 1 {topic_filter}
    RETURN topic, collabEdges
    """


def fetch_window_topic_metrics(session: Any, cfg: InsightConfig, start_year: int, end_year: int) -> dict[str, dict[str, float]]:
    rows = session.run(
        _topic_metrics_query(cfg.topic_expr, cfg.fast_mode),
        {
            "start_year": start_year,
            "end_year": end_year,
            "project_limit": cfg.fast_project_limit,
        },
    )
    data: dict[str, dict[str, float]] = {}
    for row in rows:
        topic = str(row["topic"])
        apps = int(row["applications"] or 0)
        outputs = int(row["outputs"] or 0)
        data[topic] = {
            "applications": apps,
            "outputs": outputs,
            "conversion": (outputs / apps) if apps > 0 else 0.0,
        }
    return data


def fetch_talent_metrics(session: Any, cfg: InsightConfig, topics: list[str] | None = None) -> dict[str, dict[str, float]]:
    use_topic_filter = bool(topics)
    params: dict[str, Any] = {"start_year": cfg.year_b_start, "end_year": cfg.year_b_end}
    if use_topic_filter:
        params["topics"] = topics

    people_rows = session.run(
        _talent_metrics_query(cfg.topic_expr, use_topic_filter),
        params,
    )
    if cfg.fast_mode and not cfg.fast_enable_collab:
        collab_rows = []
    else:
        collab_rows = session.run(_collab_metrics_query(cfg.topic_expr, use_topic_filter), params)

    collab_map = {str(r["topic"]): int(r["collabEdges"] or 0) for r in collab_rows}
    result: dict[str, dict[str, float]] = {}

    for row in people_rows:
        topic = str(row["topic"])
        people = int(row["people"] or 0)
        backbone = int(row["backbone"] or 0)
        senior = int(row["senior"] or 0)
        collab = int(collab_map.get(topic, 0))

        result[topic] = {
            "people": people,
            "backbone": backbone,
            "senior": senior,
            "backboneRatio": (backbone / people) if people > 0 else 0.0,
            "collabEdges": collab,
            "collabPerCapita": (collab / people) if people > 0 else 0.0,
        }

    return result


def _topic_semantic_tokens(topic: str) -> list[str]:
    parts = re.split(r"[;；,，/|、\s]+", str(topic or ""))
    return [x for x in [p.strip() for p in parts] if x and x != "<未知主题>"][:8]


def fetch_topic_knowledge_metrics(
    session: Any,
    cfg: InsightConfig,
    start_year: int,
    end_year: int,
    topics: list[str],
) -> dict[str, dict[str, float]]:
    if not topics:
        return {}

    rel_types = {
        str(r["relationshipType"])
        for r in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    }
    if "involves_concept" not in rel_types:
        return {}

    rows = session.run(
        f"""
        MATCH (p:Project)
        WITH p, toInteger(substring(toString(p.period), 0, 4)) AS y
        WHERE y >= $start_year AND y <= $end_year
        WITH p, {cfg.topic_expr} AS topic
        WHERE topic IN $topics
        OPTIONAL MATCH (p)-[:involves_concept]->(c:Concept)
        RETURN topic,
               count(c) AS conceptLinks,
               count(DISTINCT c) AS uniqueConcepts
        """,
        {
            "start_year": start_year,
            "end_year": end_year,
            "topics": topics,
        },
    )

    out: dict[str, dict[str, float]] = {}
    for row in rows:
        topic = str(row["topic"])
        out[topic] = {
            "conceptLinks": float(row["conceptLinks"] or 0),
            "uniqueConcepts": float(row["uniqueConcepts"] or 0),
        }
    return out


def build_findings(
    cfg: InsightConfig,
    metrics_a: dict[str, dict[str, float]],
    metrics_b: dict[str, dict[str, float]],
    talent: dict[str, dict[str, float]],
    knowledge: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    topics = sorted(set(metrics_a.keys()) | set(metrics_b.keys()) | set(talent.keys()))
    conv_samples_b = [
        float(v.get("conversion", 0.0))
        for v in metrics_b.values()
        if float(v.get("applications", 0.0)) >= float(cfg.min_applications)
    ]
    avg_conv_b = (sum(conv_samples_b) / len(conv_samples_b)) if conv_samples_b else 0.0

    def add_finding(kind: str, severity: str, topic: str, evidence: dict[str, Any], suggestion: str) -> None:
        k = knowledge.get(topic, {})
        concept_links = int(k.get("conceptLinks", 0) or 0)
        unique_concepts = int(k.get("uniqueConcepts", 0) or 0)
        knowledge_semantics = {
            "topic": topic,
            "semanticTokens": _topic_semantic_tokens(topic),
            "conceptLinks": concept_links,
            "uniqueConcepts": unique_concepts,
            "semanticStrength": (
                "high" if unique_concepts >= 8 else "medium" if unique_concepts >= 3 else "low"
            ),
        }
        findings.append(
            {
                "type": kind,
                "severity": severity,
                "topic": topic,
                "evidence": evidence,
                "managementEvidence": evidence,
                "knowledgeSemantics": knowledge_semantics,
                "dualLayerEvidence": {
                    "managementLayer": evidence,
                    "knowledgeLayer": knowledge_semantics,
                },
                "suggestion": suggestion,
            }
        )

    for topic in topics:
        a = metrics_a.get(topic, {"applications": 0, "outputs": 0, "conversion": 0.0})
        b = metrics_b.get(topic, {"applications": 0, "outputs": 0, "conversion": 0.0})

        app_a = float(a["applications"])
        app_b = float(b["applications"])
        out_a = float(a["outputs"])
        out_b = float(b["outputs"])
        conv_a = float(a["conversion"])
        conv_b = float(b["conversion"])
        growth = ((app_b - app_a) / app_a) if app_a > 0 else (1.0 if app_b > 0 else 0.0)
        conv_drop = conv_a - conv_b
        output_growth = ((out_b - out_a) / out_a) if out_a > 0 else (1.0 if out_b > 0 else 0.0)

        if app_b >= cfg.min_applications and growth >= cfg.growth_alert_threshold and conv_b <= cfg.low_conversion_threshold:
            add_finding(
                "low_conversion_after_growth",
                "high",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "growthRate": round(growth, 4),
                    "conversionA": round(conv_a, 4),
                    "conversionB": round(conv_b, 4),
                },
                "该主题呈现高增速低转化，建议下一周期指南进行结构性收敛，并提高落地指标权重。",
            )

        if app_b >= cfg.min_applications and growth >= DEFAULT_SPIKE_GROWTH_THRESHOLD:
            add_finding(
                "application_growth_spike",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "growthRate": round(growth, 4),
                },
                "该主题申报规模出现激增，建议增加过程复核，避免短期跟风扩张。",
            )

        if app_a >= cfg.min_applications and growth <= DEFAULT_SHRINK_ALERT_THRESHOLD:
            add_finding(
                "application_shrink_alert",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "growthRate": round(growth, 4),
                },
                "该主题申报规模明显回落，建议复盘指南导向与组织动员机制。",
            )

        if app_b >= cfg.min_applications and conv_a <= DEFAULT_PERSISTENT_LOW_CONVERSION_THRESHOLD and conv_b <= DEFAULT_PERSISTENT_LOW_CONVERSION_THRESHOLD:
            add_finding(
                "persistent_low_conversion",
                "high",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "conversionA": round(conv_a, 4),
                    "conversionB": round(conv_b, 4),
                },
                "该主题连续两个周期处于低转化状态，建议执行退出评估或重构支持方式。",
            )

        if app_b >= DEFAULT_ZERO_OUTPUT_MIN_APPLICATIONS and out_b <= 0:
            add_finding(
                "zero_output_high_heat",
                "high",
                topic,
                {
                    "applicationsB": int(app_b),
                    "outputsB": int(out_b),
                    "conversionB": round(conv_b, 4),
                },
                "该主题在较高申报规模下仍无成果输出，建议专项核查立项质量与执行机制。",
            )

        if app_b >= cfg.min_applications and conv_drop >= DEFAULT_CONVERSION_DROP_THRESHOLD:
            add_finding(
                "conversion_drop_alert",
                "medium",
                topic,
                {
                    "conversionA": round(conv_a, 4),
                    "conversionB": round(conv_b, 4),
                    "conversionDrop": round(conv_drop, 4),
                    "applicationsB": int(app_b),
                },
                "该主题转化效率较上周期显著下降，建议引入阶段考核与成果导向约束。",
            )

        if app_b >= cfg.min_applications and avg_conv_b > 0 and conv_b < avg_conv_b * DEFAULT_CONVERSION_GAP_FACTOR:
            add_finding(
                "conversion_efficiency_gap",
                "medium",
                topic,
                {
                    "applicationsB": int(app_b),
                    "conversionB": round(conv_b, 4),
                    "avgConversionB": round(avg_conv_b, 4),
                    "gapFactor": round((conv_b / avg_conv_b) if avg_conv_b > 0 else 0.0, 4),
                },
                "该主题转化效率明显低于同周期平均水平，建议做专项诊断并压实绩效考核。",
            )

        if app_b >= cfg.min_applications and growth > 0 and output_growth <= DEFAULT_OUTPUT_DECLINE_THRESHOLD:
            add_finding(
                "output_decline_with_growth",
                "high",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "outputsA": int(out_a),
                    "outputsB": int(out_b),
                    "outputGrowth": round(output_growth, 4),
                },
                "该主题呈现申报增长但成果产出下滑，建议强化中期评估与成果验收约束。",
            )

        if app_a == 0 and app_b >= DEFAULT_EMERGING_MIN_APPLICATIONS and conv_b >= DEFAULT_EMERGING_GOOD_CONVERSION:
            add_finding(
                "emerging_topic_opportunity",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "conversionB": round(conv_b, 4),
                },
                "该主题在本周期形成新增长且转化表现较好，建议纳入重点培育清单。",
            )

        if app_b >= cfg.min_applications and growth >= cfg.growth_alert_threshold and conv_b >= DEFAULT_EMERGING_GOOD_CONVERSION:
            add_finding(
                "high_growth_high_conversion",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "growthRate": round(growth, 4),
                    "conversionB": round(conv_b, 4),
                },
                "该主题呈现高增长高转化双高特征，可作为下一周期示范方向加大支持。",
            )

        if app_b >= cfg.min_applications and growth >= 0 and growth < cfg.growth_alert_threshold and conv_b >= DEFAULT_HIGH_CONVERSION_THRESHOLD:
            add_finding(
                "high_conversion_stable_scale",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "growthRate": round(growth, 4),
                    "conversionB": round(conv_b, 4),
                },
                "该主题在稳定规模下保持高转化，建议作为高质量供给方向持续支持。",
            )

        if app_b >= cfg.min_applications and conv_b >= conv_a + DEFAULT_CONVERSION_RECOVERY_DELTA:
            add_finding(
                "conversion_recovery_signal",
                "medium",
                topic,
                {
                    "applicationsA": int(app_a),
                    "applicationsB": int(app_b),
                    "conversionA": round(conv_a, 4),
                    "conversionB": round(conv_b, 4),
                    "recoveryDelta": round(conv_b - conv_a, 4),
                },
                "该主题转化效率出现恢复信号，建议跟踪其可持续性并总结可复制经验。",
            )

        t = talent.get(topic)
        if not t:
            continue

        people = float(t["people"])
        backbone_ratio = float(t["backboneRatio"])
        collab_per_capita = float(t["collabPerCapita"])
        senior_ratio = (float(t["senior"]) / people) if people > 0 else 0.0

        collab_metric_enabled = (not cfg.fast_mode) or cfg.fast_enable_collab
        collab_risk = collab_metric_enabled and collab_per_capita < cfg.talent_collab_ratio_threshold
        if people >= cfg.talent_min_people and (backbone_ratio < cfg.talent_backbone_ratio_threshold or collab_risk):
            add_finding(
                "talent_structure_gap",
                "medium",
                topic,
                {
                    "people": int(people),
                    "backboneRatio": round(backbone_ratio, 4),
                    "collabPerCapita": round(collab_per_capita, 4),
                    "senior": int(t["senior"]),
                    "backbone": int(t["backbone"]),
                },
                "该主题存在人才结构或协作强度偏弱迹象，建议补充中坚梯队并强化跨团队联合机制。",
            )

        if people >= cfg.talent_min_people and senior_ratio < DEFAULT_TALENT_SENIOR_RATIO_THRESHOLD:
            add_finding(
                "senior_talent_shortage",
                "medium",
                topic,
                {
                    "people": int(people),
                    "senior": int(t["senior"]),
                    "seniorRatio": round(senior_ratio, 4),
                },
                "该主题高级人才占比较低，建议引入高层次人才并完善导师带教机制。",
            )

        if people >= cfg.talent_min_people and int(t["backbone"]) == 0:
            add_finding(
                "backbone_absent_risk",
                "high",
                topic,
                {
                    "people": int(people),
                    "backbone": int(t["backbone"]),
                    "senior": int(t["senior"]),
                },
                "该主题团队缺少中坚骨干，建议针对性补强学术带头人与项目经理型人才。",
            )

        if collab_metric_enabled and people >= cfg.talent_min_people and collab_per_capita < cfg.talent_collab_ratio_threshold * 0.5:
            add_finding(
                "collaboration_network_weak",
                "medium",
                topic,
                {
                    "people": int(people),
                    "collabEdges": int(t["collabEdges"]),
                    "collabPerCapita": round(collab_per_capita, 4),
                },
                "该主题协作网络偏弱，建议引导跨团队联合申报与联合验收机制。",
            )

        if people >= cfg.talent_min_people and senior_ratio >= 0.25 and backbone_ratio < cfg.talent_backbone_ratio_threshold:
            add_finding(
                "senior_backbone_imbalance",
                "medium",
                topic,
                {
                    "people": int(people),
                    "seniorRatio": round(senior_ratio, 4),
                    "backboneRatio": round(backbone_ratio, 4),
                },
                "该主题存在高层次人才与中坚梯队断档并存问题，建议优化团队结构配置。",
            )

    return findings


def group_findings(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "risk": [],
        "opportunity": [],
        "talent": [],
        "conversion": [],
    }
    for item in findings:
        rule_type = str(item.get("type", ""))
        group = RULE_GROUP_MAP.get(rule_type, "risk")
        grouped.setdefault(group, []).append(item)
    return grouped


def build_briefing(cfg: InsightConfig, findings: list[dict[str, Any]], summary: dict[str, int]) -> dict[str, Any]:
    ranked_findings = sorted(
        findings,
        key=lambda item: (
            0 if item["severity"] == "high" else 1,
            item["topic"],
            item["type"],
        ),
    )
    top_findings = ranked_findings[: cfg.brief_max_findings]

    if summary["highRisk"] > 0:
        headline = f"发现 {summary['highRisk']} 个高风险主题，建议优先收敛申报增长快但转化弱的方向。"
    elif summary["mediumRisk"] > 0:
        headline = f"发现 {summary['mediumRisk']} 个结构性偏弱主题，建议提前补齐人才与协作能力。"
    else:
        headline = "未发现明显高风险主题，当前窗口整体保持相对平稳。"

    key_points = []
    for item in top_findings:
        key_points.append(
            {
                "topic": item["topic"],
                "severity": item["severity"],
                "type": item["type"],
                "evidence": item.get("evidence", {}),
                "managementEvidence": item.get("managementEvidence", {}),
                "knowledgeSemantics": item.get("knowledgeSemantics", {}),
                "suggestion": item["suggestion"],
            }
        )

    actions = []
    if summary["highRisk"] > 0:
        actions.append("优先压缩高增长低转化主题的申报扩张，改为聚焦示范性落地项目。")
        actions.append("对高风险主题增加中期验收门槛和过程审查频次。")
    if summary["mediumRisk"] > 0:
        actions.append("补充中坚骨干和跨团队协作机制，避免主题做大后能力跟不上。")
        actions.append("对人才结构偏弱主题建立联合攻关和导师制支持。")
    if not actions:
        actions.append("持续监测下一时间窗的增长、转化和人才协作变化。")

    return {
        "headline": headline,
        "keyPoints": key_points,
        "actions": actions,
    }


def run(cfg: InsightConfig) -> dict[str, Any]:
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session(database=cfg.database) as session:
            metrics_a = fetch_window_topic_metrics(session, cfg, cfg.year_a_start, cfg.year_a_end)
            metrics_b = fetch_window_topic_metrics(session, cfg, cfg.year_b_start, cfg.year_b_end)
            topics_focus: list[str] | None = None
            if cfg.fast_mode:
                merged = sorted(
                    metrics_b.items(),
                    key=lambda item: float(item[1].get("applications", 0.0)),
                    reverse=True,
                )
                topics_focus = [topic for topic, _ in merged[: cfg.fast_focus_topics]]

            try:
                talent = fetch_talent_metrics(session, cfg, topics=topics_focus)
            except Neo4jError as exc:
                if cfg.fast_mode:
                    print(f"[WARN] 快速模式下人才查询失败，已降级为空结果继续产出: {exc}")
                    talent = {}
                else:
                    raise

            topic_set = sorted(set(metrics_a.keys()) | set(metrics_b.keys()))
            try:
                knowledge = fetch_topic_knowledge_metrics(
                    session,
                    cfg,
                    cfg.year_b_start,
                    cfg.year_b_end,
                    topic_set,
                )
            except Neo4jError as exc:
                print(f"[WARN] 知识层语义检索失败，已降级为空结果继续产出: {exc}")
                knowledge = {}

        findings = build_findings(cfg, metrics_a, metrics_b, talent, knowledge)
        grouped_findings = group_findings(findings)

        summary = {
            "totalTopicsA": len(metrics_a),
            "totalTopicsB": len(metrics_b),
            "totalFindings": len(findings),
            "highRisk": sum(1 for f in findings if f["severity"] == "high"),
            "mediumRisk": sum(1 for f in findings if f["severity"] == "medium"),
            "riskTypes": sorted({str(f.get("type", "")) for f in findings if f.get("type")}),
            "groupCounts": {k: len(v) for k, v in grouped_findings.items()},
        }
        briefing = build_briefing(cfg, findings, summary)

        return {
            "meta": {
                "database": cfg.database,
                "windowA": {"start": cfg.year_a_start, "end": cfg.year_a_end},
                "windowB": {"start": cfg.year_b_start, "end": cfg.year_b_end},
                "topicExpr": cfg.topic_expr,
                "threshold": {
                    "minApplications": cfg.min_applications,
                    "growthAlert": cfg.growth_alert_threshold,
                    "lowConversion": cfg.low_conversion_threshold,
                    "talentMinPeople": cfg.talent_min_people,
                    "talentBackboneRatio": cfg.talent_backbone_ratio_threshold,
                    "talentCollabRatio": cfg.talent_collab_ratio_threshold,
                },
                "fastMode": {
                    "enabled": cfg.fast_mode,
                    "projectLimit": cfg.fast_project_limit,
                    "focusTopics": cfg.fast_focus_topics,
                    "collabEnabled": cfg.fast_enable_collab,
                },
                "evidenceLayers": {
                    "managementLayer": ["applications", "outputs", "conversion", "talent", "collab"],
                    "knowledgeLayer": ["topic_semantics", "involves_concept", "concept_links"],
                },
            },
            "summary": summary,
            "briefing": briefing,
            "findings": findings,
            "findingsGrouped": grouped_findings,
            "data": {
                "windowA": metrics_a,
                "windowB": metrics_b,
                "talent": talent,
                "knowledge": knowledge,
            },
        }
    finally:
        driver.close()


def main() -> int:
    try:
        cfg = build_config()
    except Exception as exc:
        print(f"[ERROR] 配置错误: {exc}")
        return 2

    try:
        result = run(cfg)
        ensure_output_dir(cfg.output_path)
        with open(cfg.output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print("[SUCCESS] 第三步完成：通用宏观研判引擎已跑通")
        print(f"[OUTPUT] {cfg.output_path}")
        print(f"[SUMMARY] findings={result['summary']['totalFindings']} high={result['summary']['highRisk']} medium={result['summary']['mediumRisk']}")
        print(f"[BRIEF] {result['briefing']['headline']}")
        return 0
    except Neo4jError as exc:
        print(f"[ERROR] Neo4j 执行失败: {exc}")
        print("请检查 INSIGHT_TOPIC_EXPR 与当前图谱 schema 是否匹配。")
        return 1
    except Exception as exc:
        print(f"[ERROR] 运行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
