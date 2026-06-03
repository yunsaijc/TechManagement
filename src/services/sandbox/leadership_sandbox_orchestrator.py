"""领导视角沙盘推演总编排服务。"""

from __future__ import annotations

import json
import os
import time
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.services.sandbox.briefing_orchestrator_step4 import main as step4_main
from src.services.sandbox.graph_rag_step5 import main as step5_main
from src.services.sandbox.hotspot_migration_step2 import main as step2_main
from src.services.sandbox.leadership_narrative import (
    build_leadership_narrative_package,
    extract_focus_keywords,
    prioritize_topics_for_question,
    rank_migration_links_for_question,
)
from src.services.sandbox.macro_insight_step3 import main as step3_main
from src.services.sandbox.neo4j_gds_preflight import main as step1_main

DEFAULT_OUTPUT_PATH = "debug_sandbox/Q1/leadership_sandbox_forecast.json"
DEFAULT_STEP2_PATH = "debug_sandbox/Q1/hotspot_migration_real_schema_2023_to_2024.json"
DEFAULT_STEP3_PATH = "debug_sandbox/Q1/macro_insight_2023_2023_to_2024_2024.json"
DEFAULT_STEP4_PATH = "debug_sandbox/Q1/leadership_brief_step4.json"
DEFAULT_STEP5_PATH = "debug_sandbox/Q1/graph_rag_answer_step5.json"
DEFAULT_QUESTION = (
    "请从领导视角研判我省近两年科研热点迁移、人才结构与转化效率风险，"
    "并给出下一年度指南调控建议。"
)

MODE_CONFIG: dict[str, dict[str, Any]] = {
    "quick": {
        "reuse_max_age_minutes": 1440,
        "env": {
            "INSIGHT_FAST_MODE": "true",
            "INSIGHT_FAST_PROJECT_LIMIT": "12000",
            "INSIGHT_FAST_FOCUS_TOPICS": "50",
            "INSIGHT_FAST_ENABLE_COLLAB": "false",
            "GRAPHRAG_MAX_HOPS": "2",
            "GRAPHRAG_SEED_LIMIT": "12",
            "GRAPHRAG_SUBGRAPH_NODE_LIMIT": "120",
            "GRAPHRAG_SUBGRAPH_REL_LIMIT": "240",
            "GRAPHRAG_TOP_KEYWORDS": "6",
            "HOTSPOT_MAX_EDGES": "12000",
            "HOTSPOT_PREFERRED_STRATEGY": "project_guide_name",
            "HOTSPOT_TOP_COMMUNITIES": "6",
            "HOTSPOT_COMMUNITY_EDGE_THRESHOLD": "120000",
            "HOTSPOT_ENABLE_GRAPH_PROFILE": "false",
            "SANDBOX_REAL_SNAPSHOT_CACHE_MINUTES": "1440",
        },
    },
    "standard": {
        "reuse_max_age_minutes": 240,
        "env": {
            "INSIGHT_FAST_MODE": "true",
            "INSIGHT_FAST_PROJECT_LIMIT": "30000",
            "INSIGHT_FAST_FOCUS_TOPICS": "80",
            "INSIGHT_FAST_ENABLE_COLLAB": "false",
            "GRAPHRAG_SEED_LIMIT": "24",
            "GRAPHRAG_SUBGRAPH_NODE_LIMIT": "220",
            "GRAPHRAG_SUBGRAPH_REL_LIMIT": "500",
            "GRAPHRAG_TOP_KEYWORDS": "8",
            "HOTSPOT_MAX_EDGES": "40000",
            "HOTSPOT_PREFERRED_STRATEGY": "project_guide_name",
            "HOTSPOT_TOP_COMMUNITIES": "8",
            "HOTSPOT_COMMUNITY_EDGE_THRESHOLD": "160000",
            "HOTSPOT_ENABLE_GRAPH_PROFILE": "false",
            "SANDBOX_REAL_SNAPSHOT_CACHE_MINUTES": "720",
        },
    },
    "deep": {
        "reuse_max_age_minutes": 0,
        "env": {
            "INSIGHT_FAST_MODE": "false",
            "INSIGHT_FAST_ENABLE_COLLAB": "true",
            "GRAPHRAG_SEED_LIMIT": "32",
            "GRAPHRAG_SUBGRAPH_NODE_LIMIT": "320",
            "GRAPHRAG_SUBGRAPH_REL_LIMIT": "700",
            "GRAPHRAG_TOP_KEYWORDS": "10",
            "HOTSPOT_ENABLE_GRAPH_PROFILE": "true",
        },
    },
}


def load_latest_leadership_report() -> dict[str, Any]:
    """读取最新领导推演报告。"""
    return _load_json(DEFAULT_OUTPUT_PATH)


def _is_recent_file(path: str, max_age_minutes: int) -> bool:
    if max_age_minutes <= 0:
        return False
    file_path = Path(path)
    if not file_path.exists():
        return False
    age_seconds = datetime.now(timezone.utc).timestamp() - file_path.stat().st_mtime
    return age_seconds <= max_age_minutes * 60


def _cache_meta_path(output_path: str) -> Path:
    return Path(f"{output_path}.cachemeta.json")


def _read_reuse_key(output_path: str) -> str:
    meta_path = _cache_meta_path(output_path)
    if not meta_path.exists():
        return ""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return str(data.get("reuse_key", "") or "")
    except Exception:
        return ""
    return ""


def _write_reuse_key(output_path: str, reuse_key: str) -> None:
    if not reuse_key:
        return
    meta_path = _cache_meta_path(output_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reuse_key": reuse_key,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _question_fingerprint(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _apply_mode_env(mode: str) -> dict[str, str | None]:
    config = MODE_CONFIG.get(mode, MODE_CONFIG["quick"])
    env_cfg = config.get("env", {})
    old_values: dict[str, str | None] = {}
    for key, value in env_cfg.items():
        old_values[key] = os.getenv(key)
        os.environ[key] = str(value)
    return old_values


def _restore_env(old_values: dict[str, str | None]) -> None:
    for key, value in old_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _run_or_reuse_step(
    step_name: str,
    fn: Any,
    output_path: str,
    allow_reuse: bool,
    reuse_max_age_minutes: int,
    reuse_key: str = "",
) -> dict[str, Any]:
    if allow_reuse and _is_recent_file(output_path, reuse_max_age_minutes):
        if reuse_key:
            old_key = _read_reuse_key(output_path)
            if old_key and old_key == reuse_key:
                return {
                    "step": step_name,
                    "code": 0,
                    "status": "reused",
                    "output": output_path,
                    "reason": f"命中同问题缓存（{reuse_max_age_minutes}分钟内）",
                }
        else:
            return {
                "step": step_name,
                "code": 0,
                "status": "reused",
                "output": output_path,
                "reason": f"使用{reuse_max_age_minutes}分钟内缓存结果",
            }

    code = int(fn())
    if code == 0 and reuse_key:
        _write_reuse_key(output_path, reuse_key)
    return {
        "step": step_name,
        "code": code,
        "status": "ok" if code == 0 else "failed",
        "output": output_path,
    }


def _run_step(step_name: str, fn: Any) -> dict[str, Any]:
    code = int(fn())
    return {"step": step_name, "code": code, "status": "ok" if code == 0 else "failed"}


def _ensure_output_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _load_json(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"raw": data}


def _type_counter(findings: list[dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for item in findings:
        key = str(item.get("type") or "unknown")
        counter[key] += 1
    return counter


def _extract_priority_topics(findings: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    for item in findings:
        if str(item.get("severity", "")).lower() != "high":
            continue
        picked.append(
            {
                "topic": item.get("topic", "<未知主题>"),
                "type": item.get("type", "unknown"),
                "suggestion": item.get("suggestion", ""),
                "evidence": item.get("evidence", {}),
                "managementEvidence": item.get("managementEvidence", item.get("evidence", {})),
                "knowledgeSemantics": item.get("knowledgeSemantics", {}),
            }
        )
        if len(picked) >= limit:
            break
    return picked


def _build_step_output(step: str, payload: dict[str, Any]) -> dict[str, Any]:
    if step == "step2_hotspot":
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        sankey = payload.get("sankey", {}) if isinstance(payload, dict) else {}
        links = sankey.get("links", []) if isinstance(sankey.get("links", []), list) else []
        return {
            "analysisMode": meta.get("analysisMode", ""),
            "windowA": meta.get("windowA", {}),
            "windowB": meta.get("windowB", {}),
            "migrationLinks": len(links),
        }

    if step == "step3_insight":
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        briefing = payload.get("briefing", {}) if isinstance(payload, dict) else {}
        return {
            "totalFindings": int(summary.get("totalFindings", 0) or 0),
            "highRisk": int(summary.get("highRisk", 0) or 0),
            "mediumRisk": int(summary.get("mediumRisk", 0) or 0),
            "headline": briefing.get("headline", ""),
        }

    if step == "step4_briefing":
        brief = payload.get("brief", {}) if isinstance(payload, dict) else {}
        return {
            "headline": brief.get("headline", ""),
            "keyMessages": brief.get("keyMessages", [])[:3] if isinstance(brief.get("keyMessages", []), list) else [],
            "actions": brief.get("actions", [])[:3] if isinstance(brief.get("actions", []), list) else [],
        }

    if step == "step5_graphrag":
        generation = payload.get("generation", {}) if isinstance(payload, dict) else {}
        return {
            "answer": str(generation.get("answer", "")),
            "keyFindings": generation.get("keyFindings", [])[:5] if isinstance(generation.get("keyFindings", []), list) else [],
            "confidence": generation.get("confidence", 0.0),
        }

    return {}


def _build_future_judgement(
    step2: dict[str, Any],
    step3: dict[str, Any],
    step5: dict[str, Any],
    *,
    leadership_question: str = "",
) -> dict[str, Any]:
    summary = step3.get("summary", {}) if isinstance(step3, dict) else {}
    findings = step3.get("findings", []) if isinstance(step3.get("findings", []), list) else []
    focus_kw = extract_focus_keywords(leadership_question)
    grouped = summary.get("groupCounts", {}) if isinstance(summary.get("groupCounts", {}), dict) else {}

    total_findings = int(summary.get("totalFindings", 0) or 0)
    high_risk = int(summary.get("highRisk", 0) or 0)
    medium_risk = int(summary.get("mediumRisk", 0) or 0)
    high_ratio = (high_risk / total_findings) if total_findings > 0 else 0.0

    risk_level = "high" if high_ratio >= 0.45 else ("medium" if high_ratio >= 0.2 else "low")

    type_count = _type_counter(findings)

    signals: list[str] = []
    if int(grouped.get("conversion", 0) or 0) > 0:
        signals.append("转化效率风险持续存在，建议下一年度指南提高成果转化与验收约束权重。")
    if int(grouped.get("talent", 0) or 0) > 0:
        signals.append("人才结构问题密集出现，建议面向关键主题建立骨干人才补强和联合攻关机制。")
    if int(grouped.get("risk", 0) or 0) > 0:
        signals.append("热点扩张与质量不匹配，建议对高增长低转化方向实施结构性收紧。")

    if not signals:
        signals.append("当前未识别到高强度结构性风险，建议维持稳态观察并加强月度监测。")

    recommendations: list[str] = []
    if type_count.get("low_conversion_after_growth", 0) > 0:
        recommendations.append("对高增长低转化主题设置立项配额和中期里程碑淘汰机制。")
    if type_count.get("persistent_low_conversion", 0) > 0:
        recommendations.append("对连续低转化主题启动存量项目复盘，暂停同质化增量申报。")
    if type_count.get("talent_structure_gap", 0) > 0 or type_count.get("backbone_absent_risk", 0) > 0:
        recommendations.append("围绕关键方向建立人才梯队专项，提升高级人才与骨干占比。")
    if not recommendations:
        recommendations.append("建议以季度为单位滚动复评主题质量，动态优化指南方向。")

    rag_meta = step5.get("meta", {}) if isinstance(step5, dict) else {}
    layer_stats = rag_meta.get("layerStats", {}) if isinstance(rag_meta.get("layerStats", {}), dict) else {}
    step2_sankey = step2.get("sankey", {}) if isinstance(step2, dict) else {}
    step2_links = step2_sankey.get("links", []) if isinstance(step2_sankey.get("links", []), list) else []
    migration_link_count = len(step2_links)

    migration_top_links = rank_migration_links_for_question(step2_links, focus_kw)[:12]

    if migration_link_count > 0:
        signals.append(f"热点迁移图识别到 {migration_link_count} 条迁移流，需优先关注头部迁移簇的结构变化。")
    else:
        signals.append("热点迁移流暂未达到阈值，建议在下一轮评估中结合业务口径微调迁移阈值。")

    mgmt_evidence_count = 0
    knowledge_evidence_count = 0
    knowledge_high = 0
    knowledge_medium = 0
    knowledge_low = 0
    for item in findings:
        mgmt = item.get("managementEvidence") if isinstance(item.get("managementEvidence"), dict) else {}
        if mgmt:
            mgmt_evidence_count += 1
        ks = item.get("knowledgeSemantics") if isinstance(item.get("knowledgeSemantics"), dict) else {}
        if ks:
            knowledge_evidence_count += 1
            strength = str(ks.get("semanticStrength", "")).lower()
            if strength == "high":
                knowledge_high += 1
            elif strength == "medium":
                knowledge_medium += 1
            else:
                knowledge_low += 1

    bridge_rel = int(((layer_stats.get("bridge") or {}).get("relationships") or 0))
    management_signals: list[str] = []
    knowledge_signals: list[str] = []
    bridge_signals: list[str] = []

    if mgmt_evidence_count > 0:
        management_signals.append(f"管理层证据覆盖 {mgmt_evidence_count} 条高优先发现，可直接支撑治理动作。")
    else:
        management_signals.append("管理层证据不足，当前结论更多依赖总体趋势判断。")

    if knowledge_evidence_count > 0:
        knowledge_signals.append(
            f"知识层语义已命中 {knowledge_evidence_count} 条发现（高/中/低强度：{knowledge_high}/{knowledge_medium}/{knowledge_low}）。"
        )
    else:
        knowledge_signals.append("知识层语义命中不足，主题归并的语义解释力偏弱。")

    if bridge_rel > 0:
        bridge_signals.append(f"桥接层检索到 {bridge_rel} 条跨层关系，管理结论与知识语义可相互印证。")
    else:
        bridge_signals.append("桥接层关系未形成有效命中，管理层与知识层仍存在解释断点。")

    return {
        "riskLevel": risk_level,
        "riskIndex": round(high_ratio, 4),
        "signals": signals,
        "recommendations": recommendations,
        "summary": {
            "totalFindings": total_findings,
            "highRisk": high_risk,
            "mediumRisk": medium_risk,
            "groupCounts": grouped,
        },
        "retrievalEvidence": {
            "question": rag_meta.get("question", ""),
            "retrievedSeeds": int(rag_meta.get("retrievedSeeds", 0) or 0),
            "retrievedNodes": int(rag_meta.get("retrievedNodes", 0) or 0),
            "retrievedRelationships": int(rag_meta.get("retrievedRelationships", 0) or 0),
            "migrationLinks": migration_link_count,
            "layerStats": layer_stats,
        },
        "evidenceLayers": {
            "management": {
                "signalCount": mgmt_evidence_count,
                "signals": management_signals,
            },
            "knowledge": {
                "signalCount": knowledge_evidence_count,
                "high": knowledge_high,
                "medium": knowledge_medium,
                "low": knowledge_low,
                "signals": knowledge_signals,
            },
            "bridge": {
                "relationships": bridge_rel,
                "signals": bridge_signals,
            },
        },
        "migrationTopLinks": migration_top_links,
        "topRiskTypes": type_count.most_common(5),
        "priorityTopics": prioritize_topics_for_question(_extract_priority_topics(findings, limit=12), focus_kw)[:8],
        "focusKeywords": focus_kw,
        "anchoredQuestion": (leadership_question or "")[:800],
    }


def _timed_run_or_reuse_step(
    step_name: str,
    fn: Any,
    output_path: str,
    allow_reuse: bool,
    reuse_max_age_minutes: int,
    reuse_key: str = "",
) -> dict[str, Any]:
    """带计时的步骤执行封装。"""
    t0 = time.monotonic()
    result = _run_or_reuse_step(step_name, fn, output_path, allow_reuse, reuse_max_age_minutes, reuse_key)
    result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    return result


def run_leadership_sandbox(
    question: str | None = None,
    run_preflight: bool = False,
    mode: str = "quick",
    force_refresh: bool = False,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    pipeline_t0 = time.monotonic()

    def emit(progress: int, step: str, message: str, output: dict[str, Any] | None = None) -> None:
        if progress_cb is None:
            return
        try:
            event: dict[str, Any] = {"progress": progress, "step": step, "message": message}
            if isinstance(output, dict) and output:
                event["output"] = output
            progress_cb(event)
        except Exception:
            pass

    steps: list[dict[str, Any]] = []
    selected_mode = mode if mode in MODE_CONFIG else "quick"
    reuse_max_age_minutes = int(MODE_CONFIG[selected_mode].get("reuse_max_age_minutes", 0))

    emit(5, "init", "初始化推演任务")

    if run_preflight:
        emit(10, "step1_preflight", "正在执行 Step1 预检")
        steps.append(_run_step("step1_preflight", step1_main))
        if steps[-1]["code"] != 0:
            raise RuntimeError("step1_preflight 执行失败")
        emit(15, "step1_preflight", "Step1 预检完成")

    step2_path = os.getenv("HOTSPOT_OUTPUT_PATH", DEFAULT_STEP2_PATH)
    step3_path = os.getenv("INSIGHT_OUTPUT_PATH", DEFAULT_STEP3_PATH)
    step4_path = os.getenv("BRIEFING_OUTPUT_PATH", DEFAULT_STEP4_PATH)
    step5_path = os.getenv("GRAPHRAG_OUTPUT_PATH", DEFAULT_STEP5_PATH)

    old_mode_env = _apply_mode_env(selected_mode)
    allow_reuse = (not force_refresh)

    effective_question = (question or "").strip() or DEFAULT_QUESTION

    old_question = os.getenv("GRAPHRAG_QUESTION")
    os.environ["GRAPHRAG_QUESTION"] = effective_question
    q_fp = _question_fingerprint(effective_question)
    step4_reuse_key = f"{selected_mode}:step4:q={q_fp}"
    step5_reuse_key = f"{selected_mode}:step5:q={q_fp}"

    try:
        # Phase 1: Step2、Step3、Step5 并行；Step2+Step3 完成后即可启动 Step4（与 Step5 尾部重叠）
        emit(20, "parallel_phase1", "正在并行执行 Step2/Step3/Step5")
        heartbeat_seconds = max(2, int(os.getenv("SANDBOX_PROGRESS_HEARTBEAT_SECONDS", "5") or 5))
        parallel_timeout_seconds = max(120, int(os.getenv("SANDBOX_PARALLEL_TIMEOUT_SECONDS", "2400") or 2400))
        parallel_t0 = time.monotonic()

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sandbox-step") as pool:
            fut_step2: Future[dict[str, Any]] = pool.submit(
                _timed_run_or_reuse_step, "step2_hotspot", step2_main,
                step2_path, allow_reuse, reuse_max_age_minutes,
            )
            fut_step3: Future[dict[str, Any]] = pool.submit(
                _timed_run_or_reuse_step, "step3_insight", step3_main,
                step3_path, allow_reuse, reuse_max_age_minutes,
            )
            fut_step5: Future[dict[str, Any]] = pool.submit(
                _timed_run_or_reuse_step, "step5_graphrag", step5_main,
                step5_path, allow_reuse, reuse_max_age_minutes,
                step5_reuse_key,
            )

            future_name_map: dict[Future[dict[str, Any]], str] = {
                fut_step2: "step2_hotspot",
                fut_step3: "step3_insight",
                fut_step5: "step5_graphrag",
            }
            future_results: dict[str, dict[str, Any]] = {}
            target_names = {"step2_hotspot", "step3_insight"}

            while not target_names.issubset(future_results.keys()):
                elapsed = int(time.monotonic() - parallel_t0)
                if elapsed > parallel_timeout_seconds:
                    raise RuntimeError(
                        f"并行阶段超时（>{parallel_timeout_seconds}s）："
                        f"仍在等待 {', '.join(sorted(target_names - set(future_results.keys())))}"
                    )

                pending = [f for f, name in future_name_map.items() if name not in future_results]
                done_set, _ = wait(pending, timeout=heartbeat_seconds, return_when=FIRST_COMPLETED)
                if not done_set:
                    done_names = "、".join(sorted(future_results.keys())) or "无"
                    emit(20, "parallel_phase1", f"并行阶段进行中（已{elapsed}s）：已完成 {done_names}")
                    continue

                for fut in done_set:
                    name = future_name_map[fut]
                    future_results[name] = fut.result()

            step2_result = future_results["step2_hotspot"]
            step3_result = future_results["step3_insight"]

            steps.append(step2_result)
            if step2_result["code"] != 0:
                raise RuntimeError("step2_hotspot 执行失败")
            step2_data = _load_json(step2_path)
            emit(42, "step2_hotspot", "Step2 完成", _build_step_output("step2_hotspot", step2_data))

            steps.append(step3_result)
            if step3_result["code"] != 0:
                raise RuntimeError("step3_insight 执行失败")
            step3_data = _load_json(step3_path)
            emit(48, "step3_insight", "Step3 完成", _build_step_output("step3_insight", step3_data))

            emit(52, "parallel_step4_step5", "Step4 与 Step5 并行（简报 + GraphRAG）")
            fut_step4: Future[dict[str, Any]] = pool.submit(
                _timed_run_or_reuse_step, "step4_briefing", step4_main,
                step4_path, allow_reuse, reuse_max_age_minutes,
                step4_reuse_key,
            )
            # Step4 与 Step5 并行期间继续心跳，避免前端长期停在同一进度
            while "step4_briefing" not in future_results or "step5_graphrag" not in future_results:
                elapsed = int(time.monotonic() - parallel_t0)
                if elapsed > parallel_timeout_seconds:
                    waiting = []
                    if "step4_briefing" not in future_results:
                        waiting.append("step4_briefing")
                    if "step5_graphrag" not in future_results:
                        waiting.append("step5_graphrag")
                    raise RuntimeError(
                        f"并行阶段超时（>{parallel_timeout_seconds}s）：仍在等待 {', '.join(waiting)}"
                    )

                wait_list: list[Future[dict[str, Any]]] = []
                if "step4_briefing" not in future_results:
                    wait_list.append(fut_step4)
                if "step5_graphrag" not in future_results:
                    wait_list.append(fut_step5)

                done_set, _ = wait(wait_list, timeout=heartbeat_seconds, return_when=FIRST_COMPLETED)
                if not done_set:
                    done_names = "、".join(sorted(future_results.keys())) or "无"
                    emit(52, "parallel_step4_step5", f"Step4/5 运行中（已{elapsed}s）：已完成 {done_names}")
                    continue

                for fut in done_set:
                    if fut is fut_step4:
                        future_results["step4_briefing"] = fut.result()
                    elif fut is fut_step5:
                        future_results["step5_graphrag"] = fut.result()

            step5_result = future_results["step5_graphrag"]
            step4_result = future_results["step4_briefing"]

        steps.append(step4_result)
        if step4_result["code"] != 0:
            raise RuntimeError("step4_briefing 执行失败")
        step4_data = _load_json(step4_path)
        emit(72, "step4_briefing", "Step4 完成", _build_step_output("step4_briefing", step4_data))

        steps.append(step5_result)
        if step5_result["code"] != 0:
            raise RuntimeError("step5_graphrag 执行失败")
        step5_data = _load_json(step5_path)
        emit(78, "step5_graphrag", "Step5 完成", _build_step_output("step5_graphrag", step5_data))

    finally:
        if old_question is None:
            os.environ.pop("GRAPHRAG_QUESTION", None)
        else:
            os.environ["GRAPHRAG_QUESTION"] = old_question
        _restore_env(old_mode_env)

    emit(90, "assemble", "正在组装最终报告")

    future = _build_future_judgement(
        step2_data,
        step3_data,
        step5_data,
        leadership_question=effective_question,
    )
    brief = step4_data.get("brief", {}) if isinstance(step4_data, dict) else {}
    step5_gen = step5_data.get("generation", {}) if isinstance(step5_data.get("generation", {}), dict) else {}
    narrative_pkg = build_leadership_narrative_package(
        effective_question,
        step2_data,
        step3_data,
        future,
        step5_gen,
    )

    pipeline_elapsed = round(time.monotonic() - pipeline_t0, 2)

    report = {
        "status": "ok",
        "pipeline": "leadership_forecast_step2_5",
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "mode": selected_mode,
            "forceRefresh": force_refresh,
            "reuseMaxAgeMinutes": reuse_max_age_minutes,
            "question": effective_question,
            "focusKeywords": extract_focus_keywords(effective_question),
            "runPreflight": run_preflight,
            "output": DEFAULT_OUTPUT_PATH,
            "paths": {
                "step2": step2_path,
                "step3": step3_path,
                "step4": step4_path,
                "step5": step5_path,
            },
            "dataSource": step2_data.get("meta", {}).get("dataSource", {}),
            "graphProfile": step2_data.get("meta", {}).get("graphProfile", {}),
            "timing": {
                "totalSeconds": pipeline_elapsed,
                "step2Seconds": step2_result.get("elapsed_seconds", 0),
                "step3Seconds": step3_result.get("elapsed_seconds", 0),
                "step4Seconds": step4_result.get("elapsed_seconds", 0),
                "step5Seconds": step5_result.get("elapsed_seconds", 0),
                "parallelPhase1": "step2 ∥ step3 ∥ step5；step2+3 完成后 step4 ∥ step5",
            },
        },
        "steps": steps,
        "leadershipBrief": {
            "headline": brief.get("headline", "暂无简报结论"),
            "keyMessages": brief.get("keyMessages", []),
            "actions": brief.get("actions", []),
        },
        "futureJudgement": future,
        "leadershipNarrative": narrative_pkg.get("narrative", {}),
        "causalChainHints": narrative_pkg.get("causalHints", []),
        "policySimulationPresets": narrative_pkg.get("policyPresets", []),
        "policyParameterModels": narrative_pkg.get("policyParameterModels", []),
        "policyScenarioComparison": narrative_pkg.get("policyScenarioComparison", []),
        "counterfactualCards": narrative_pkg.get("counterfactualCards", []),
        "raw": {
            "step2": step2_data,
            "step3": {
                "summary": step3_data.get("summary", {}),
                "briefing": step3_data.get("briefing", {}),
            },
            "step5": {
                "meta": step5_data.get("meta", {}),
                "generation": step5_data.get("generation", {}),
            },
        },
    }

    _ensure_output_dir(DEFAULT_OUTPUT_PATH)
    with open(DEFAULT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    emit(100, "done", f"推演完成（总耗时 {pipeline_elapsed}s）")

    return report
