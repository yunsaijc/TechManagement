"""领导沙盘「将来时」叙事、问题锚定与政策仿真提示（可演进层）。

说明：
- 完整因果发现 / 反事实仿真引擎需独立研究与数据，此处提供可落地的：关键词锚定、
  规则链提示、定性政策杠杆与可选 LLM 叙事增强。
"""

from __future__ import annotations

import json
import re
from typing import Any

_DOMAIN_HINTS = [
    "固态电池", "量子", "人工智能", "芯片", "生物医药", "新材料", "新能源",
    "基金", "项目", "主题", "指南", "转化", "风险", "增长", "申报", "人才", "验收",
]

_TYPE_CAUSAL_LABEL: dict[str, str] = {
    "low_conversion_after_growth": "申报增长 → 成果转化偏弱",
    "persistent_low_conversion": "连续周期 → 低转化锁定",
    "talent_structure_gap": "主题规模 → 人才结构缺口",
    "backbone_absent_risk": "团队构成 → 骨干断层",
    "conversion_drop_alert": "上周期转化 → 本周期下滑",
    "application_growth_spike": "申报规模 → 短期激增",
}


def extract_focus_keywords(question: str, max_k: int = 10) -> list[str]:
    """从领导自然语言问题中提取检索/锚定用词（中文短语 + 领域词）。"""
    q = (question or "").strip()
    if not q:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for hint in _DOMAIN_HINTS:
        if hint in q and hint not in seen:
            seen.add(hint)
            found.append(hint)
            if len(found) >= max_k:
                return found

    tokens = re.findall(r"[\u4e00-\u9fff]{2,12}", q)
    for t in tokens:
        if len(t) < 2 or t in {"我省", "近两年", "下一年度", "领导视角", "请从", "并给出"}:
            continue
        if t not in seen:
            seen.add(t)
            found.append(t)
        if len(found) >= max_k:
            break
    return found[:max_k]


def _link_text_blob(link: dict[str, Any]) -> str:
    parts = [
        str(link.get("sourceKeyword", "") or ""),
        str(link.get("targetKeyword", "") or ""),
        str(link.get("source", "") or ""),
        str(link.get("target", "") or ""),
    ]
    return " ".join(parts)


def _keyword_hit_score(text: str, keywords: list[str]) -> float:
    if not text or not keywords:
        return 0.0
    score = 0.0
    for kw in keywords:
        if kw and kw in text:
            score += float(len(kw))
    return score


def rank_migration_links_for_question(
    links: list[dict[str, Any]],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """在强度排序基础上，按与领导问题的字面关联加权（不改变 Step2 原始全量链路）。"""

    def _base_triple(link: dict[str, Any]) -> tuple[float, float, float]:
        v = float(link.get("value") or 0)
        j = float(link.get("jaccard") or 0)
        raw = float(
            link["rawOverlap"]
            if "rawOverlap" in link and link.get("rawOverlap") is not None
            else (link.get("raw_overlap") or 0)
        )
        return (v, j, raw)

    def _sort_key(link: dict[str, Any]) -> tuple[float, float, float, float]:
        base = _base_triple(link)
        bonus = _keyword_hit_score(_link_text_blob(link), keywords) * 0.01
        return (base[0] + bonus, base[1], base[2])

    return sorted(links, key=_sort_key, reverse=True)


def prioritize_topics_for_question(
    topics: list[dict[str, Any]],
    keywords: list[str],
) -> list[dict[str, Any]]:
    if not keywords:
        return topics
    scored = []
    for item in topics:
        t = str(item.get("topic", "") or "")
        s = _keyword_hit_score(t, keywords)
        scored.append((s, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored]


def build_causal_chain_hints(findings: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """由规则发现构造可解释的「假设因果链」提示（非统计因果推断证明）。"""
    out: list[dict[str, Any]] = []
    for item in findings[:80]:
        if len(out) >= limit:
            break
        if str(item.get("severity", "")).lower() != "high":
            continue
        typ = str(item.get("type", "") or "")
        topic = str(item.get("topic", "") or "")
        chain = _TYPE_CAUSAL_LABEL.get(typ, "多因素 → 结构性风险")
        ev = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        out.append(
            {
                "topic": topic,
                "findingType": typ,
                "chainHypothesis": chain,
                "evidenceSummary": ev,
                "disclaimer": "基于图谱统计与规则引擎的假设链，需业务复核与专项因果验证。",
            }
        )
    return out


def build_policy_simulation_presets(
    findings: list[dict[str, Any]],
    group_counts: dict[str, Any],
) -> list[dict[str, Any]]:
    """定性政策杠杆与预期方向（非数值反事实仿真）。"""
    presets: list[dict[str, Any]] = []
    tc: dict[str, int] = {}
    for item in findings:
        k = str(item.get("type", "") or "")
        tc[k] = tc.get(k, 0) + 1

    if tc.get("low_conversion_after_growth", 0) > 0 or int(group_counts.get("conversion", 0) or 0) > 5:
        presets.append(
            {
                "id": "tighten_guide_quota",
                "title": "指南与配额收紧（试点）",
                "intervention": "对高增长低转化主题压缩立项配额，提高中期验收与转化里程碑权重。",
                "expectedDirection": "抑制低效扩张，短期申报量可能回落，长期转化结构有望改善。",
                "caveats": "未建模跨部门博弈与产业外溢；需配套考核口径调整。",
            }
        )
    if tc.get("talent_structure_gap", 0) > 0 or int(group_counts.get("talent", 0) or 0) > 5:
        presets.append(
            {
                "id": "talent_pilot",
                "title": "骨干人才与联合攻关专项",
                "intervention": "对人才断层主题强制联合申报比例与导师/带头人配置。",
                "expectedDirection": "协作边与人才节点在子图中增厚，人才类发现条数预期下降。",
                "caveats": "人才引进滞后于指南周期；仿真为定性方向。",
            }
        )
    if not presets:
        presets.append(
            {
                "id": "steady_monitor",
                "title": "稳态监测与滚动复盘",
                "intervention": "维持当前指南结构，按季度滚动复评主题质量与迁移路径。",
                "expectedDirection": "风险信号提前暴露，避免政策大起大落。",
                "caveats": "对突发热点响应偏慢。",
            }
        )
    return presets


def build_policy_parameter_models(
    presets: list[dict[str, Any]],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """将政策建议转成主体/客体/工具/目标四元组，便于参数化建模展示。"""
    focus_topic = keywords[0] if keywords else "重点主题"
    models: list[dict[str, Any]] = []
    for p in presets[:4]:
        pid = str(p.get("id", "") or "")
        title = str(p.get("title", "") or "政策方案")
        intervention = str(p.get("intervention", "") or "")
        expected = str(p.get("expectedDirection", "") or "")

        if "talent" in pid or "人才" in title:
            subject = "省级科技管理部门 + 牵头高校院所"
            obj = f"{focus_topic}相关团队与骨干人才结构"
            tool = "联合申报约束 + 人才配比要求 + 协同考核"
            target = "降低人才断层风险并提升协同产出"
        elif "tighten" in pid or "收紧" in title:
            subject = "指南管理部门 + 评审组织"
            obj = f"{focus_topic}相关项目组合"
            tool = "配额调节 + 中期里程碑 + 验收转化权重"
            target = "抑制低效扩张并提升转化效率"
        else:
            subject = "科技管理部门"
            obj = f"{focus_topic}相关主题"
            tool = intervention or "滚动监测 + 季度复盘"
            target = expected or "稳定风险并优化资源配置"

        models.append(
            {
                "id": f"{pid or 'policy'}_param",
                "title": title,
                "subject": subject,
                "object": obj,
                "tool": tool,
                "target": target,
            }
        )
    return models


def build_policy_scenario_comparison(
    future_judgement: dict[str, Any],
    presets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造保守/平衡/激进三档政策组合的量化对比（启发式，可后续替换为真实仿真）。"""
    base_risk = float(future_judgement.get("riskIndex", 0.0) or 0.0)
    base_risk = max(0.05, min(0.95, base_risk))
    preset_strength = max(1, len(presets))
    # 强度因子：有更多可执行政策时，平衡/激进方案改善幅度可适度增加
    strength = min(1.35, 0.9 + preset_strength * 0.12)

    scenarios = [
        {
            "id": "conservative",
            "name": "保守方案",
            "description": "小幅调节配额与验收口径，优先控制执行扰动。",
            "riskDeltaPct": -round(5 * strength, 1),
            "conversionDeltaPct": round(3 * strength, 1),
            "talentGapDeltaPct": -round(2.5 * strength, 1),
            "confidence": 0.78,
        },
        {
            "id": "balanced",
            "name": "平衡方案",
            "description": "同步推进指南结构优化与人才协同补强，兼顾短期与中期效果。",
            "riskDeltaPct": -round(11 * strength, 1),
            "conversionDeltaPct": round(7 * strength, 1),
            "talentGapDeltaPct": -round(6 * strength, 1),
            "confidence": 0.72,
        },
        {
            "id": "aggressive",
            "name": "激进方案",
            "description": "强约束收紧低效方向并快速重配资源，短期波动较大。",
            "riskDeltaPct": -round(17 * strength, 1),
            "conversionDeltaPct": round(10 * strength, 1),
            "talentGapDeltaPct": -round(8 * strength, 1),
            "confidence": 0.64,
        },
    ]

    out: list[dict[str, Any]] = []
    for s in scenarios:
        post_risk = base_risk * (1 + float(s["riskDeltaPct"]) / 100.0)
        post_risk = max(0.01, min(0.99, post_risk))
        out.append(
            {
                **s,
                "baseRiskIndex": round(base_risk, 3),
                "postRiskIndex": round(post_risk, 3),
            }
        )
    return out


def build_counterfactual_cards(
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for s in scenarios:
        cards.append(
            {
                "scenarioId": s.get("id"),
                "title": f"{s.get('name', '方案')}的反事实结果",
                "beforeAfter": f"风险指数 {s.get('baseRiskIndex', '-')} → {s.get('postRiskIndex', '-')}",
                "effects": [
                    f"风险变化：{s.get('riskDeltaPct', 0)}%",
                    f"转化效率变化：{s.get('conversionDeltaPct', 0)}%",
                    f"人才断层变化：{s.get('talentGapDeltaPct', 0)}%",
                ],
                "confidence": s.get("confidence", 0.6),
            }
        )
    return cards


def _rule_future_bullets(question: str, findings: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    high = [f for f in findings if str(f.get("severity", "")).lower() == "high"][:4]
    for f in high:
        topic = str(f.get("topic", "") or "某主题")
        typ = str(f.get("type", "") or "")
        sug = str(f.get("suggestion", "") or "")[:120]
        label = _TYPE_CAUSAL_LABEL.get(typ, "结构性风险")
        bullets.append(f"「{topic}」{label}：{sug}")
    if not bullets:
        bullets.append("当前窗口未检出高强度规则命中，建议结合业务口径扩大监测主题或下调阈值后重跑。")
    bullets.append(f"领导关切锚定：{question[:160]}{'…' if len(question) > 160 else ''}")
    tot = int(summary.get("totalFindings", 0) or 0)
    bullets.append(f"研判覆盖：共 {tot} 条规则发现，可作为下一年度指南讨论会的量化附件。")
    return bullets[:6]


def _llm_narrative_enhance(question: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from langchain_core.prompts import ChatPromptTemplate
    except ModuleNotFoundError:
        return None
    try:
        from src.services.sandbox.sandbox_llm import build_sandbox_llm
    except ModuleNotFoundError:
        return None

    llm = build_sandbox_llm("narrative")
    if llm is None:
        return None

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是省级科技管理决策支持专家。只根据输入的结构化证据写「将来时」管理叙事，"
                "禁止编造数据中不存在的主题名或数字。输出严格 JSON 对象，键："
                "headline（一句话）, bullets（字符串数组，3~5 条）, nextYearActions（字符串数组，2~4 条）。",
            ),
            ("human", "领导问题：{question}\n\n证据摘要(JSON)：{payload}\n\n请输出 JSON。"),
        ]
    )
    try:
        chain = prompt | llm
        resp = chain.invoke({"question": question, "payload": json.dumps(payload, ensure_ascii=False)[:6000]})
        raw_content = getattr(resp, "content", resp)
        text = str(raw_content)
    except Exception as exc:
        print(f"[WARN] 领导叙事 LLM 调用失败: {exc}")
        return None

    if isinstance(text, list):
        text = "\n".join(str(x) for x in text)
    text = text.strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(text[i : j + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "headline": str(data.get("headline", "")).strip(),
        "bullets": [str(x).strip() for x in (data.get("bullets") or []) if str(x).strip()][:6],
        "nextYearActions": [str(x).strip() for x in (data.get("nextYearActions") or []) if str(x).strip()][:6],
        "source": "llm",
    }


def build_leadership_narrative_package(
    question: str,
    step2: dict[str, Any],
    step3: dict[str, Any],
    future_judgement: dict[str, Any],
    step5_generation: dict[str, Any],
) -> dict[str, Any]:
    """组装叙事包、因果链提示与政策仿真预设。"""
    keywords = extract_focus_keywords(question)
    findings = step3.get("findings", []) if isinstance(step3.get("findings", []), list) else []
    summary = future_judgement.get("summary", {}) if isinstance(future_judgement.get("summary", {}), dict) else {}
    grouped = summary.get("groupCounts", {}) if isinstance(summary.get("groupCounts", {}), dict) else {}

    rule_bullets = _rule_future_bullets(question, findings, summary)
    compact = {
        "focusKeywords": keywords,
        "riskLevel": future_judgement.get("riskLevel"),
        "groupCounts": grouped,
        "topRiskTypes": future_judgement.get("topRiskTypes"),
        "priorityTopics": future_judgement.get("priorityTopics"),
        "signals": (future_judgement.get("signals") or [])[:5],
        "graphRagAnswerPreview": (step5_generation.get("answer") or "")[:400],
    }
    llm_block = _llm_narrative_enhance(question, compact)
    merged_bullets = rule_bullets
    headline_out: str | None = None
    next_actions: list[str] | None = None
    if isinstance(llm_block, dict) and llm_block.get("bullets"):
        merged_bullets = list(llm_block["bullets"])
        headline_out = str(llm_block.get("headline") or "").strip() or None
        na = llm_block.get("nextYearActions")
        if isinstance(na, list) and na:
            next_actions = [str(x).strip() for x in na if str(x).strip()]

    narrative = {
        "focusKeywords": keywords,
        "ruleNarrativeBullets": rule_bullets,
        "llmNarrative": llm_block,
        "mergedBullets": merged_bullets,
        "headline": headline_out,
        "nextYearActions": next_actions,
        "maturityNote": (
            "当前为「图谱统计 + 规则 + LLM 叙事」的可演进实现；结构化因果估计与政策组合数值仿真需后续专项接入。"
        ),
    }

    policy_presets = build_policy_simulation_presets(findings, grouped)
    policy_param_models = build_policy_parameter_models(policy_presets, keywords)
    scenario_compare = build_policy_scenario_comparison(future_judgement, policy_presets)
    counterfactual_cards = build_counterfactual_cards(scenario_compare)

    return {
        "narrative": narrative,
        "causalHints": build_causal_chain_hints(findings),
        "policyPresets": policy_presets,
        "policyParameterModels": policy_param_models,
        "policyScenarioComparison": scenario_compare,
        "counterfactualCards": counterfactual_cards,
    }
