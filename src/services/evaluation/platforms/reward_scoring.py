"""奖励平台评分口径校准。

奖励项目是已完成成果评审，不能直接套计划项目的进度、预算、ROI 等口径。
本模块只在 platform=reward 时接入，把已解析的提名书证据转成奖种对应的维度结果。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from src.common.models.evaluation import CheckItem, CheckResult


@dataclass(frozen=True)
class EvidenceSignal:
    """一个可用于生成判断句的证据信号。"""

    label: str
    text: str
    source: str
    source_text: str = ""
    highlight_text: str = ""
    strength: str = "strong"

    def to_payload(self) -> Dict[str, str]:
        return {
            "claim": self.label,
            "basis": self.text,
            "source_section": self.source,
            "source_text": self.source_text,
            "highlight_text": self.highlight_text,
            "strength": self.strength,
        }


NATURAL_SCIENCE_DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "feasibility": {
        "name": "科学方法与证据链",
        "items": [
            ("研究方法清晰度", 0.35),
            ("实验验证支撑", 0.35),
            ("成果论证完整性", 0.30),
        ],
    },
    "innovation": {
        "name": "原创科学发现",
        "items": [
            ("原创发现", 0.45),
            ("学术新颖性", 0.35),
            ("科学价值", 0.20),
        ],
    },
    "team": {
        "name": "完成人与单位支撑",
        "items": [
            ("完成人贡献", 0.40),
            ("完成单位支撑", 0.30),
            ("研究基础", 0.30),
        ],
    },
    "outcome": {
        "name": "代表性成果",
        "items": [
            ("代表性论文", 0.40),
            ("引用与同行认可", 0.35),
            ("证明材料对应", 0.25),
        ],
    },
    "social_benefit": {
        "name": "学科与社会影响",
        "items": [
            ("学科推动作用", 0.45),
            ("行业基础支撑", 0.30),
            ("同行评价", 0.25),
        ],
    },
    "economic_benefit": {
        "name": "应用价值参考",
        "items": [
            ("应用场景", 0.35),
            ("潜在转化价值", 0.30),
            ("效益表述合理性", 0.35),
        ],
    },
    "risk_control": {
        "name": "申报风险与争议控制",
        "items": [
            ("材料真实性声明", 0.35),
            ("知识产权与保密风险", 0.30),
            ("公示与争议情况", 0.35),
        ],
    },
    "schedule": {
        "name": "成果完成度",
        "items": [
            ("成果已完成程度", 0.45),
            ("证明材料闭环", 0.35),
            ("后续应用基础", 0.20),
        ],
    },
    "compliance": {
        "name": "形式合规与材料完整性",
        "items": [
            ("提名声明", 0.35),
            ("附件完整性", 0.35),
            ("公示与合规风险", 0.30),
        ],
    },
}


def apply_reward_scoring_adjustments(
    check_results: List[CheckResult],
    sections: Dict[str, str],
    options: Dict[str, Any],
) -> List[CheckResult]:
    """按奖励奖种修正评分结果。

    当前先落地自然科学奖。其他奖种仍保留原结果，只给降级项打上不计入总分标记。
    """

    if str(options.get("platform") or "").strip().lower() != "reward":
        return check_results

    award_type_code = str(options.get("award_type_code") or "").strip()
    marked = [_mark_degraded_excluded(item) for item in check_results]
    if award_type_code != "2":
        return marked

    evidence = _build_natural_science_evidence(sections)
    original_by_dimension = {item.dimension: item for item in marked}
    adjusted: List[CheckResult] = []
    for dimension in [item.dimension for item in marked]:
        spec = NATURAL_SCIENCE_DIMENSIONS.get(dimension)
        if not spec:
            adjusted.append(original_by_dimension[dimension])
            continue
        adjusted.append(_build_natural_science_result(dimension, spec, evidence, original_by_dimension[dimension]))
    return adjusted


def _mark_degraded_excluded(check_result: CheckResult) -> CheckResult:
    details = dict(check_result.details or {})
    if details.get("degraded"):
        details["exclude_from_total"] = True
        details["exclude_reason"] = "模型评审未正常生成，奖励平台不把兜底分计入正式总分"
        check_result.details = details
    return check_result


def _build_natural_science_result(
    dimension: str,
    spec: Dict[str, Any],
    evidence: Dict[str, Any],
    original: CheckResult,
) -> CheckResult:
    score, basis_signals, issues, highlights = _score_natural_science_dimension(dimension, evidence)
    basis = [signal.text for signal in basis_signals]
    items = [
        CheckItem(name=name, score=score, weight=weight, comment=_item_comment(name, basis, issues))
        for name, weight in spec["items"]
    ]
    details = dict(original.details or {})
    details.pop("exclude_from_total", None)
    details.pop("exclude_reason", None)
    details.pop("degraded", None)
    details.update(
        {
            "reward_scoring_adjusted": True,
            "award_type_code": "2",
            "award_type_name": "自然科学奖",
            "original_score": original.score,
            "evidence_basis": basis,
            "evidence_items": [signal.to_payload() for signal in basis_signals],
            "evidence_sections": evidence["hit_sections"],
        }
    )
    return CheckResult(
        dimension=dimension,
        dimension_name=str(spec["name"]),
        score=score,
        confidence=0.78 if basis else 0.55,
        opinion=_dimension_opinion(dimension, score, basis_signals, issues),
        issues=issues,
        highlights=highlights,
        items=items,
        details=details,
    )


def _build_natural_science_evidence(sections: Dict[str, str]) -> Dict[str, Any]:
    names = {
        "nomination": ("提名意见",),
        "summary": ("项目简介", "项目简介（限1200字）"),
        "discovery": ("重要科学发现", "主要科学发现"),
        "detail": ("项目详细内容", "项目详细内容（不超过6页）"),
        "papers": ("代表性论文", "代表性论文(专著)目录"),
        "citations": ("被他人引用", "代表性论文(专著)被他人引用情况"),
        "objective": ("客观评价", "客观评价（不超过2页）"),
        "attachments": ("主要附件目录", "附件目录"),
        "publicity": ("公示", "公示材料"),
        "members": ("主要完成人", "主要完成人情况表"),
        "units": ("主要完成单位", "主要完成单位情况表"),
        "ip": ("知识产权", "标准规范"),
    }
    evidence: Dict[str, Any] = {"hit_sections": []}
    for key, patterns in names.items():
        text, hits = _collect_sections(sections, patterns)
        evidence[key] = text
        evidence[f"{key}_hits"] = hits
        evidence["hit_sections"].extend(hits)

    all_text = "\n".join(str(value) for value in sections.values())
    evidence["all_text"] = all_text
    evidence["paper_count"] = _first_int_around(evidence["papers"], ("代表性论文", "论文", "专著"))
    evidence["sci_count"] = _first_int_around(all_text, ("SCI", "sci"))
    evidence["citation_count"] = _first_int_around(all_text, ("引用", "被引"))
    evidence["other_citation_count"] = _first_int_around(all_text, ("他引",))
    evidence["has_new_discovery"] = _has_any(evidence["discovery"] + evidence["nomination"], ("新种", "发现", "首次", "揭示"))
    evidence["has_vaccine_or_validation"] = _has_any(all_text, ("疫苗", "免疫保护", "验证", "评价", "实验", "生物学特性"))
    evidence["has_statement"] = _has_any(all_text, ("声明", "真实有效", "无争议", "知识产权", "保密"))
    evidence["has_publicity"] = bool(evidence["publicity"]) or "公示" in all_text
    return evidence


def _score_natural_science_dimension(
    dimension: str,
    evidence: Dict[str, Any],
) -> Tuple[float, List[EvidenceSignal], List[str], List[str]]:
    basis: List[EvidenceSignal] = []
    issues: List[str] = []
    highlights: List[str] = []

    def add(
        condition: bool,
        label: str,
        text: str,
        value: float,
        source: str = "",
        evidence_key: str = "",
        highlight: str = "",
    ) -> float:
        if condition:
            source_name = source or label
            source_key = evidence_key or _source_to_evidence_key(source_name)
            source_text = _pick_source_text(evidence, source_key, highlight or label)
            source_text = _prepend_hit_section_title(evidence, source_key, source_text)
            signal = EvidenceSignal(
                label=label,
                text=text,
                source=source_name,
                source_text=source_text,
                highlight_text=_pick_highlight_text(source_text, highlight or label),
            )
            basis.append(signal)
            highlights.append(text)
            return value
        return 0.0

    score = 6.2
    if dimension == "innovation":
        score += add(evidence["has_new_discovery"], "新种发现", "重要科学发现中列明新发现或新种等原创性内容", 0.9, "重要科学发现", "discovery", "发现了一种新的兔艾美耳球虫")
        score += add(bool(evidence["objective"]), "客观评价", "客观评价材料支撑科技创新判断", 0.35, "客观评价", "objective", "丰富了兔球虫物种资源")
        score += add(bool(evidence["detail"]), "项目详细内容", "项目详细内容提供发现过程和科学依据", 0.30, "项目详细内容", "detail", "生物学特性研究")
        issues.extend(_missing(evidence, [("discovery", "重要科学发现材料不足"), ("objective", "客观评价材料不足")]))
    elif dimension == "outcome":
        score += add(bool(evidence["papers"]), "代表性论文", "提名书列出代表性论文或专著目录", 0.55, "代表性论文", "papers", "七、代表性论文")
        score += add((evidence["sci_count"] or 0) >= 1, "SCI 收录", f"材料体现 SCI 收录 {evidence['sci_count']} 篇", 0.35, "代表性论文", "papers", "Science Citation Index")
        score += add((evidence["citation_count"] or 0) > 0, "引用数据", f"材料体现引用或他引数据 {evidence['citation_count']} 次", 0.45, "引用情况", "citations", "引用")
        score += add(bool(evidence["attachments"]), "附件目录", "附件目录可用于核对成果证明材料", 0.25, "主要附件目录", "attachments", "主要附件目录")
        issues.extend(_missing(evidence, [("papers", "代表性论文材料不足"), ("citations", "引用情况材料不足")]))
    elif dimension == "feasibility":
        score += add(bool(evidence["detail"]), "项目详细内容", "项目详细内容说明研究过程和技术/实验依据", 0.45, "项目详细内容", "detail", "项目详细内容")
        score += add(evidence["has_vaccine_or_validation"], "实验验证", "材料包含实验验证、评价或生物学特性研究表述", 0.45, "项目详细内容", "detail", "免疫保护评价")
        score += add(bool(evidence["objective"]), "客观评价", "客观评价可辅助确认成果证据链", 0.30, "客观评价", "objective", "客观评价")
        issues.extend(_missing(evidence, [("detail", "项目详细内容不足"), ("objective", "客观评价材料不足")]))
    elif dimension == "team":
        score += add(bool(evidence["members"]), "主要完成人", "提名书包含主要完成人信息", 0.35, "主要完成人情况表", "members", "主要完成人")
        score += add(bool(evidence["units"]), "主要完成单位", "提名书包含主要完成单位信息", 0.30, "主要完成单位情况表", "units", "主要完成单位")
        score += add(bool(evidence["nomination"]), "提名意见", "提名意见说明人员排名和材料真实性", 0.35, "提名意见", "nomination", "真实有效")
        issues.extend(_missing(evidence, [("members", "主要完成人材料不足"), ("units", "主要完成单位材料不足")]))
    elif dimension == "social_benefit":
        score += add(bool(evidence["citations"]), "引用情况", "引用情况可体现同行认可和学科影响", 0.45, "引用情况", "citations", "引用")
        score += add(bool(evidence["objective"]), "客观评价", "客观评价材料支撑学科或行业影响判断", 0.35, "客观评价", "objective", "理论依据")
        score += add(bool(evidence["nomination"]), "提名意见", "提名意见说明成果理论基础和支撑价值", 0.30, "提名意见", "nomination", "理论依据")
        issues.extend(_missing(evidence, [("citations", "引用情况材料不足"), ("objective", "客观评价材料不足")]))
    elif dimension == "economic_benefit":
        score = 6.7
        score += add(bool(evidence["summary"]) and _has_any(evidence["summary"], ("应用", "养兔", "疫病", "疫苗")), "潜在应用场景", "项目简介体现潜在应用场景", 0.25, "项目简介", "summary", "养兔业")
        score += add(bool(evidence["objective"]), "客观评价", "客观评价可作为应用价值参考", 0.20, "客观评价", "objective", "客观评价")
        issues.append("自然科学奖经济效益只作参考，不按 ROI、市场规模或商业化时间表强扣分")
    elif dimension == "risk_control":
        score += add(evidence["has_statement"], "声明材料", "声明材料体现真实性、知识产权、保密或无争议承诺", 0.55, "声明", "", "真实有效")
        score += add(evidence["has_publicity"], "公示材料", "公示材料可用于核对异议和形式风险", 0.30, "公示材料", "publicity", "公示")
        score += add(bool(evidence["attachments"]), "附件目录", "附件目录有助于核验材料完整性", 0.25, "主要附件目录", "attachments", "主要附件目录")
        issues.extend(_missing(evidence, [("publicity", "公示材料需核对"), ("attachments", "附件目录需核对")]))
    elif dimension == "schedule":
        score = 6.8
        score += add(bool(evidence["papers"]) or bool(evidence["discovery"]), "已完成成果", "代表性成果或重要发现可证明成果完成度", 0.45, "代表性成果/重要科学发现", "papers", "七、代表性论文")
        score += add(bool(evidence["attachments"]), "附件目录", "附件目录可支撑成果证明闭环", 0.25, "主要附件目录", "attachments", "主要附件目录")
        issues.append("已完成奖励成果不应按计划项目进度表强评，当前按成果完成度判断")
    elif dimension == "compliance":
        score += add(evidence["has_statement"], "提名声明", "提名声明体现材料真实有效、无违规或无争议承诺", 0.50, "提名声明", "nomination", "真实有效")
        score += add(evidence["has_publicity"], "公示材料", "公示材料可支撑形式合规核对", 0.25, "公示材料", "publicity", "公示")
        score += add(bool(evidence["attachments"]), "附件目录", "附件目录可支撑材料完整性核对", 0.30, "主要附件目录", "attachments", "主要附件目录")
        issues.extend(_missing(evidence, [("publicity", "公示材料需核对"), ("attachments", "附件完整性需核对")]))

    if not basis:
        issues.append("当前未命中该维度的核心奖励证据，需人工复核")
    return round(min(score, 8.6), 2), _dedupe_signals(basis), _dedupe(issues), _dedupe(highlights[:4])


def _dimension_opinion(dimension: str, score: float, basis_signals: List[EvidenceSignal], issues: List[str]) -> str:
    target = NATURAL_SCIENCE_DIMENSIONS.get(dimension, {}).get("name") or "该维度"
    judgment = _build_one_sentence_judgment(target, basis_signals, issues)
    basis = [signal.text for signal in basis_signals]
    basis_text = "；".join(basis[:3]) if basis else "暂未命中明确奖励证据"
    issue_text = "；".join(issues[:2]) if issues else "未发现明显材料短板"
    return f"{judgment}主要依据：{basis_text}。需关注：{issue_text}。评分：{score:.2f}。"


def _build_one_sentence_judgment(target: str, basis_signals: List[EvidenceSignal], issues: List[str]) -> str:
    labels = [signal.label for signal in basis_signals if signal.label]
    issue = _first_substantive_issue(issues)
    if len(labels) >= 2:
        evidence_text = "、".join(labels[:3])
        suffix = f"，但{issue}" if issue else ""
        return f"材料已通过{evidence_text}支撑{target}判断，证据较充分{suffix}。"
    if labels:
        suffix = f"，仍需补充或核对{issue}" if issue else "，证据链仍需进一步补充"
        return f"材料已通过{labels[0]}支撑{target}判断{suffix}。"
    supplement = issue or f"{target}相关证明材料"
    return f"当前未命中{target}的核心证据，无法形成充分判断，需补充或核对{supplement}。"


def _first_substantive_issue(issues: List[str]) -> str:
    for issue in issues:
        text = str(issue or "").strip(" 。；;")
        if not text:
            continue
        if "不按 ROI" in text or "不应按计划项目进度表强评" in text:
            continue
        return text
    return ""


def _item_comment(name: str, basis: List[str], issues: List[str]) -> str:
    if basis:
        return f"{name}依据：{basis[0]}"
    if issues:
        return f"{name}需复核：{issues[0]}"
    return f"{name}未发现明显异常"


def _collect_sections(sections: Dict[str, str], patterns: Iterable[str]) -> Tuple[str, List[str]]:
    chunks: List[str] = []
    hits: List[str] = []
    for actual_name, text in sections.items():
        normalized = re.sub(r"\s+", "", str(actual_name or ""))
        if any(re.sub(r"\s+", "", pattern) in normalized for pattern in patterns):
            value = str(text or "").strip()
            if value:
                chunks.append(value)
                hits.append(str(actual_name))
    return "\n\n".join(chunks), hits


def _source_to_evidence_key(source: str) -> str:
    mapping = {
        "提名意见": "nomination",
        "项目简介": "summary",
        "重要科学发现": "discovery",
        "项目详细内容": "detail",
        "代表性论文": "papers",
        "引用情况": "citations",
        "客观评价": "objective",
        "主要附件目录": "attachments",
        "附件目录": "attachments",
        "公示材料": "publicity",
        "主要完成人情况表": "members",
        "主要完成单位情况表": "units",
        "知识产权": "ip",
    }
    for name, key in mapping.items():
        if name in source:
            return key
    return ""


def _pick_source_text(evidence: Dict[str, Any], key: str, highlight: str) -> str:
    keys = [key] if key else []
    keys.extend(["discovery", "objective", "detail", "papers", "citations", "nomination", "summary", "attachments", "publicity"])
    for item_key in keys:
        value = str(evidence.get(item_key) or "").strip()
        if not value:
            continue
        if re.fullmatch(r"Science\s+Citation\s+Index", str(highlight or ""), flags=re.IGNORECASE) and re.search(
            r"Science\s+Citation\s+Index",
            value,
            flags=re.IGNORECASE,
        ):
            return "检索数据库: Science Citation Index"
        if highlight and highlight in value:
            return _trim_source_text(value, highlight)
        if item_key == key:
            return _trim_source_text(value, highlight)
    return ""


def _prepend_hit_section_title(evidence: Dict[str, Any], key: str, source_text: str) -> str:
    text = str(source_text or "").strip()
    if not key:
        return text
    hits = evidence.get(f"{key}_hits")
    if not isinstance(hits, list) or not hits:
        return text
    title = str(hits[0] or "").strip()
    if not title or title in text:
        return text
    return f"{title} {text}".strip()


def _pick_highlight_text(source_text: str, preferred: str) -> str:
    text = str(source_text or "")
    preferred = str(preferred or "").strip()
    if preferred and preferred in text:
        return preferred
    compact_text = re.sub(r"\s+", "", text)
    compact_preferred = re.sub(r"\s+", "", preferred)
    if compact_preferred and len(compact_preferred) >= 6 and compact_preferred in compact_text:
        return preferred
    for pattern in (
        r"发现了?一种新的[^。；;\n]{0,40}",
        r"代表性论文\(?专著\)?目录[^。；;\n]{0,20}",
        r"Science\s+Citation\s+Index",
        r"SCI\s*收录\D{0,8}\d+\s*篇",
        r"引用\D{0,8}\d+\s*次",
        r"他引\D{0,8}\d+\s*次",
        r"代表性论文\D{0,8}\d+\s*篇",
        r"免疫保护评价[^。；;\n]{0,30}",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return _trim_source_text(text, "", max_len=36)


def _trim_source_text(text: str, anchor: str, max_len: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    anchor = str(anchor or "").strip()
    index = value.find(anchor) if anchor else -1
    if index < 0 and anchor:
        compact_value = re.sub(r"\s+", "", value)
        compact_anchor = re.sub(r"\s+", "", anchor)
        compact_index = compact_value.find(compact_anchor)
        if compact_index >= 0:
            index = int(len(value) * compact_index / max(len(compact_value), 1))
    if index < 0:
        return value[:max_len].rstrip()
    row_start = value.rfind("[表格行", 0, index)
    start = row_start if row_start >= 0 else max(0, index - 45)
    return value[start:start + max_len].strip()


def _first_int_around(text: str, markers: Iterable[str]) -> int:
    value = str(text or "")
    for marker in markers:
        for pattern in (
            rf"{re.escape(marker)}\D{{0,8}}(\d+)",
            rf"(\d+)\D{{0,8}}{re.escape(marker)}",
        ):
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
    return 0


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in str(text or "") for keyword in keywords)


def _missing(evidence: Dict[str, Any], checks: Iterable[Tuple[str, str]]) -> List[str]:
    return [message for key, message in checks if not evidence.get(key)]


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _dedupe_signals(values: List[EvidenceSignal]) -> List[EvidenceSignal]:
    result: List[EvidenceSignal] = []
    seen: set[str] = set()
    for value in values:
        key = f"{value.label}|{value.text}"
        if key in seen:
            continue
        result.append(value)
        seen.add(key)
    return result
