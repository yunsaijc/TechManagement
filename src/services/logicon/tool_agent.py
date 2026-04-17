"""逻辑自洽：LangChain 工具调用 Agent。

在确定性规则（R-TIME/R-BUDGET/R-METRIC）产出之后，由模型按需调用工具：
检索原文、定位页码、抽取金额候选、做确定性求和/容差比较、重跑单维规则，
并输出面向审核员的简短中文结论。

设计原则（弥补规则难覆盖之处）：
- **语义与路由**：由模型决定查哪一段、是否多步检索；**数值真假与冲突条目**仍以规则重跑与结构化抽取为准。
- **理解 vs 计算分离**：预算加总、两数比较等通过专用工具完成，避免模型心算。
- **与「关掉 LLM 聚类」一致**：指标是否冲突仍以 `detect_metric_conflicts` 为准；Agent 不替代聚类，只做解释与取证。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.common.models.logicon import ConflictItem, ExtractedEntity, LogicOnDimensionSummary
from src.services.logicon.parser import LogicOnParser
from src.services.logicon.rules import (
    _extract_amount_candidates,
    detect_budget_conflicts,
    detect_metric_conflicts,
    detect_time_conflicts,
)

logger = logging.getLogger(__name__)


class EquivalenceProbeResult(BaseModel):
    """受控语义等价探测：严格 JSON（由 with_structured_output 约束）。"""

    aligned: bool = Field(
        description="两条表述是否指向同一类指标目标且语义相容（如「3篇」与「不少于3篇」通常为 true；不同指标类型为 false）"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="0~1，不确定时偏低")
    reason_zh: str = Field(max_length=450, description="一句或两句中文理由，勿引入文档外事实")


@dataclass
class _ToolEnv:
    doc_id: str
    doc_kind: str
    raw_text: str
    page_texts: Dict[int, str]
    parser: LogicOnParser
    amount_tolerance_wan: float
    date_tolerance_months: int
    metric_tolerance_ratio: float
    conflicts: List[ConflictItem]
    dimension_summaries: List[LogicOnDimensionSummary]
    time_entities: List[ExtractedEntity]
    budget_entities: List[ExtractedEntity]
    metric_entities: List[ExtractedEntity]
    # 仅当开启 enable_equivalence_probe 且启用 Agent 时注入；用于 semantic_metric_equivalence_probe
    equivalence_llm: Optional[Any] = None


def _truncate(s: str, max_len: int = 14000) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + f"\n…（已截断，原文共 {len(t)} 字符）"


def _page_for_substring(sub: str, page_texts: Dict[int, str]) -> Optional[int]:
    if not sub:
        return None
    for p in sorted(page_texts.keys()):
        if sub in (page_texts.get(p) or ""):
            return int(p)
    return None


def _search_snippets(raw_text: str, page_texts: Dict[int, str], keywords: str, max_snippets: int) -> str:
    parts = [k.strip() for k in re.split(r"[\s,，;；]+", keywords) if k.strip()]
    if not parts:
        return "请提供至少一个关键词。"
    hits: List[str] = []
    for kw in parts[:6]:
        pos = 0
        while len(hits) < max_snippets:
            i = raw_text.find(kw, pos)
            if i < 0:
                break
            a = max(0, i - 200)
            b = min(len(raw_text), i + len(kw) + 200)
            snip = raw_text[a:b].replace("\n", " ")
            pg = _page_for_substring(raw_text[i:b], page_texts)
            pg_s = f"约第 {pg} 页" if pg is not None else "页码未定位"
            hits.append(f"[{pg_s}] …{snip}…")
            pos = i + max(1, len(kw))
    if not hits:
        return f"未在全文命中关键词（已尝试: {', '.join(parts[:6])}）。"
    return "\n---\n".join(hits[:max_snippets])


def _entities_digest(entities: List[ExtractedEntity], label: str, limit: int = 12) -> str:
    lines: List[str] = [f"## {label}（最多 {limit} 条）"]
    for e in entities[:limit]:
        d = e.model_dump(mode="json")
        nm = d.get("name") or d.get("entity_type")
        val = (d.get("value") or "")[:400]
        norm = d.get("normalized") or {}
        norm_s = json.dumps(norm, ensure_ascii=False)[:800]
        lines.append(f"- **{nm}** | value: {val}\n  - normalized: {norm_s}")
    if not entities:
        lines.append("_（无）_")
    return "\n".join(lines)


def _conflicts_digest(conflicts: List[ConflictItem], limit: int = 20) -> str:
    rows = []
    for c in conflicts[:limit]:
        rows.append(
            {
                "rule_id": c.rule_id,
                "severity": c.severity.value if hasattr(c.severity, "value") else str(c.severity),
                "title": c.title,
                "description": (c.description or "")[:500],
            }
        )
    payload = {
        "total": len(conflicts),
        "shown": min(limit, len(conflicts)),
        "items": rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


_HEADING_HINT_RE = re.compile(
    r"(^第[0-9一二三四五六七八九十百千]+[章节编条]\s*[\u4e00-\u9fa5]{0,40})"
    r"|(^[（(]?[一二三四五六七八九十]+[）)]\s*[\u4e00-\u9fa5]{2,60})"
    r"|([\u4e00-\u9fa5]{2,40}(?:表|图|附件|预算|进度|考核指标|绩效指标|研究内容|预期成果))"
)


def _dimension_digest(summaries: List[LogicOnDimensionSummary]) -> str:
    out = []
    for s in summaries:
        out.append(
            {
                "rule_id": s.rule_id,
                "name": s.name,
                "outcome": s.outcome,
                "detail_lines": (s.detail_lines or [])[:24],
            }
        )
    return json.dumps(out, ensure_ascii=False, indent=2)


def _invoke_semantic_equivalence_probe(
    llm: Any,
    claim_a: str,
    claim_b: str,
    constraint_kind: str,
) -> str:
    """单次结构化 LLM 调用；失败时返回带 error 字段的 JSON，不改变规则层。"""
    ca = (claim_a or "").strip()[:600]
    cb = (claim_b or "").strip()[:600]
    ck = (constraint_kind or "").strip()[:240]
    if not ca or not cb:
        return json.dumps(
            {"error": "claim_a 与 claim_b 均不能为空", "aligned": None, "confidence": 0.0, "reason_zh": ""},
            ensure_ascii=False,
        )
    try:
        chain = llm.bind(temperature=0.0).with_structured_output(EquivalenceProbeResult)
    except Exception as e:
        return json.dumps({"error": f"绑定结构化输出失败: {e}"}, ensure_ascii=False)
    messages = [
        SystemMessage(
            content=(
                "判断两句中文是否描述**同一类**项目绩效/约束目标且可同时成立。"
                "「发表3篇论文」与「发表论文不少于3篇」→ aligned=true。"
                "「3篇论文」与「2项专利」→ aligned=false。"
                "「不少于N」与「N」在同类指标下通常相容。"
                "不要虚构；不要将预算科目与论文篇数混为一谈。"
            )
        ),
        HumanMessage(
            content="claim_a:\n"
            + ca
            + "\n\nclaim_b:\n"
            + cb
            + (("\n\nconstraint_kind_hint:\n" + ck) if ck else "")
        ),
    ]
    try:
        out = chain.invoke(messages)
        return json.dumps(out.model_dump(), ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("semantic_metric_equivalence_probe")
        return json.dumps(
            {
                "error": f"{type(e).__name__}: {e}",
                "aligned": None,
                "confidence": 0.0,
                "reason_zh": "",
            },
            ensure_ascii=False,
        )


def _guess_page_for_char_index(pos: int, raw_text: str, page_texts: Dict[int, str]) -> Optional[int]:
    if pos < 0 or not page_texts:
        return None
    keys = sorted(page_texts.keys())
    acc = 0
    for i, p in enumerate(keys):
        chunk = page_texts[p] or ""
        n = len(chunk)
        if acc <= pos < acc + n:
            return int(p)
        acc += n
        if i < len(keys) - 1:
            acc += 2  # 与 parse_file 中 "\n\n".join 一致
    if pos >= len(raw_text or ""):
        return None
    return _page_for_substring(raw_text[max(0, pos - 80) : pos + 80], page_texts)


def build_logicon_tools(env: _ToolEnv):
    """为当前文档构造绑定闭包的工具列表（供 bind_tools）。"""

    @tool
    def search_document_keywords(keywords: str, max_snippets: int = 8) -> str:
        """在全文检索关键词，返回带上下文的短片段（用于核对矛盾出处）。多个词用空格或逗号分隔。"""
        n = max(1, min(24, int(max_snippets)))
        return _search_snippets(env.raw_text, env.page_texts, keywords, n)

    @tool
    def get_page_text(page_number: int, max_chars: int = 8000) -> str:
        """读取指定页纯文本。page_number 与解析器输出的页键一致：多为 1 起编；纯文本模式常为 0。"""
        pgs = env.page_texts
        if not pgs:
            return "本文档无分页信息（单页文本）。"
        mc = max(500, min(16000, int(max_chars)))
        if page_number in pgs:
            return _truncate(pgs[page_number], mc)
        alt = page_number - 1
        if alt in pgs:
            return _truncate(pgs[alt], mc)
        keys = sorted(pgs.keys())
        return f"无此页码。可用页键: {keys[:40]}{'…' if len(keys) > 40 else ''}"

    @tool
    def get_conflict_and_dimension_digest() -> str:
        """返回已检出的冲突摘要（规则 ID、标题、严重度）以及三维度核对摘要（勿编造条目）。"""
        return (
            "### conflicts\n"
            + _conflicts_digest(env.conflicts)
            + "\n\n### dimension_summaries\n"
            + _dimension_digest(env.dimension_summaries)
        )

    @tool
    def list_extracted_entities(entity_group: str) -> str:
        """列出规则层抽取的实体摘要。entity_group: time | budget | metric | all"""
        g = (entity_group or "all").strip().lower()
        if g == "time":
            return _entities_digest(env.time_entities, "时间相关实体")
        if g == "budget":
            return _entities_digest(env.budget_entities, "预算相关实体")
        if g == "metric":
            return _entities_digest(env.metric_entities, "指标相关实体")
        if g == "all":
            return "\n\n".join(
                [
                    _entities_digest(env.time_entities, "时间相关实体", 8),
                    _entities_digest(env.budget_entities, "预算相关实体", 8),
                    _entities_digest(env.metric_entities, "指标相关实体", 8),
                ]
            )
        return "entity_group 必须是 time、budget、metric 或 all。"

    @tool
    def rerun_dimension_rules(dimension: str) -> str:
        """重新运行某一维度的确定性规则检测，返回冲突条数与每条标题（与首次运行应一致，除非文本变化）。"""
        dim = (dimension or "").strip().lower()
        if dim in ("time", "r-time", "time_span"):
            c, _ = detect_time_conflicts(
                doc_id=env.doc_id,
                parser=env.parser,
                raw_text=env.raw_text,
                page_texts=env.page_texts,
                date_tolerance_months=env.date_tolerance_months,
            )
        elif dim in ("budget", "r-budget", "sum"):
            c, _ = detect_budget_conflicts(
                doc_id=env.doc_id,
                parser=env.parser,
                raw_text=env.raw_text,
                page_texts=env.page_texts,
                amount_tolerance_wan=env.amount_tolerance_wan,
            )
        elif dim in ("metric", "r-metric", "kpi"):
            c, _ = detect_metric_conflicts(
                doc_id=env.doc_id,
                raw_text=env.raw_text,
                page_texts=env.page_texts,
                metric_tolerance_ratio=env.metric_tolerance_ratio,
            )
        else:
            return "dimension 必须是 time、budget 或 metric。"
        items = [{"rule_id": x.rule_id, "title": x.title, "severity": x.severity.value} for x in c]
        return json.dumps({"dimension": dim, "conflict_count": len(c), "items": items[:30]}, ensure_ascii=False)

    @tool
    def get_raw_text_window(start_char: int, end_char: int) -> str:
        """按「全文字符下标」截取子串（与解析得到的 raw_text 一致），并给出约略页码；用于精确定位后再人工核对。"""
        raw = env.raw_text or ""
        n = len(raw)
        a = max(0, int(start_char))
        b = min(n, int(end_char))
        if b <= a:
            return json.dumps({"error": "需要 end_char > start_char", "text_len": n}, ensure_ascii=False)
        snip = raw[a:b]
        pg = _guess_page_for_char_index((a + b) // 2, raw, env.page_texts)
        return json.dumps(
            {
                "start_char": a,
                "end_char": b,
                "approx_page": pg,
                "snippet": _truncate(snip.replace("\n", " "), 6000),
            },
            ensure_ascii=False,
            indent=2,
        )

    @tool
    def extract_amount_candidates_from_text(text_snippet: str) -> str:
        """从任意原文片段中抽取「数字+万/元」等金额候选（内部统一为万元浮点），用于与规则层对照或心算前校验；不替代 rerun_dimension_rules(budget)。"""
        t = text_snippet or ""
        items = _extract_amount_candidates(t)
        rows = [{"amount_wan": round(x[0], 6), "unit": x[1], "raw": (x[2] or "")[:120]} for x in items[:48]]
        return json.dumps({"count": len(items), "candidates": rows}, ensure_ascii=False, indent=2)

    @tool
    def sum_numbers_wan(numbers_json: str) -> str:
        """对 JSON 数组中的若干数字求和（单位须已统一为「万元」）；禁止传入任意代码，仅支持纯数字数组，例如 [1.2, 3.4]。"""
        try:
            data = json.loads(numbers_json or "[]")
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"JSON 解析失败: {e}"}, ensure_ascii=False)
        if not isinstance(data, list):
            return json.dumps({"error": "需要 JSON 数组"}, ensure_ascii=False)
        s = 0.0
        for x in data:
            s += float(x)
        return json.dumps({"sum_wan": round(s, 6), "count": len(data)}, ensure_ascii=False)

    @tool
    def compare_two_numbers_relative_tolerance(value_a: float, value_b: float, note: str = "") -> str:
        """比较两个数相对差异是否不超过当前文档的 metric_tolerance_ratio（与 R-METRIC-01 同量级参考）；返回 JSON，不写入冲突列表。"""
        a, b = float(value_a), float(value_b)
        denom = max(abs(a), abs(b), 1e-12)
        ratio = abs(a - b) / denom
        tol = float(env.metric_tolerance_ratio)
        return json.dumps(
            {
                "value_a": a,
                "value_b": b,
                "relative_diff": round(ratio, 8),
                "metric_tolerance_ratio": tol,
                "within_tolerance": bool(ratio <= tol + 1e-12),
                "note": (note or "")[:300],
            },
            ensure_ascii=False,
        )

    @tool
    def find_pages_with_all_keywords(keywords: str) -> str:
        """返回「同一页文本中同时出现」所有关键词的页码（空格/逗号分隔）。用于跨段/跨表前先缩小页范围。"""
        parts = [k.strip() for k in re.split(r"[\s,，;；]+", keywords) if k.strip()]
        if not parts:
            return json.dumps({"pages": [], "error": "关键词为空"}, ensure_ascii=False)
        hit_pages: List[int] = []
        for p in sorted(env.page_texts.keys()):
            txt = env.page_texts.get(p) or ""
            if all(k in txt for k in parts):
                hit_pages.append(int(p))
        return json.dumps({"keywords": parts, "pages": hit_pages, "count": len(hit_pages)}, ensure_ascii=False)

    @tool
    def list_likely_section_or_table_titles(max_hits: int = 50) -> str:
        """启发式列出疑似章节标题/表题行（含 char_start），便于分块后再 get_raw_text_window 细读。"""
        raw = env.raw_text or ""
        mh = max(5, min(120, int(max_hits)))
        hits: List[Dict[str, Any]] = []
        pos = 0
        for line in raw.split("\n"):
            stripped = line.strip()
            ln = len(stripped)
            if 6 <= ln <= 120 and (
                _HEADING_HINT_RE.search(stripped)
                or re.search(r"(表|预算|附件|指标|绩效|进度|考核|研究内容|预期成果)", stripped)
            ):
                hits.append({"char_start": pos, "line": stripped[:160]})
                if len(hits) >= mh:
                    break
            pos += len(line) + 1
        return json.dumps({"hits": hits, "total": len(hits)}, ensure_ascii=False, indent=2)

    tool_list: List[Any] = [
        search_document_keywords,
        get_page_text,
        get_raw_text_window,
        extract_amount_candidates_from_text,
        sum_numbers_wan,
        compare_two_numbers_relative_tolerance,
        find_pages_with_all_keywords,
        list_likely_section_or_table_titles,
        get_conflict_and_dimension_digest,
        list_extracted_entities,
        rerun_dimension_rules,
    ]

    if env.equivalence_llm is not None:
        _probe_llm = env.equivalence_llm

        @tool
        def semantic_metric_equivalence_probe(
            claim_a: str,
            claim_b: str,
            constraint_kind: str = "",
        ) -> str:
            """判断两条极短表述是否「同一指标类型下语义相容」（如「论文3篇」与「不少于3篇」）。返回严格 JSON（aligned/confidence/reason_zh）；不修改规则冲突列表，不可替代 rerun_dimension_rules(metric)。"""
            return _invoke_semantic_equivalence_probe(_probe_llm, claim_a, claim_b, constraint_kind)

        tool_list.append(semantic_metric_equivalence_probe)

    return tool_list


def _tool_name_args_id(tc: Any) -> tuple[str, Dict[str, Any], str]:
    if isinstance(tc, dict):
        return (
            str(tc.get("name") or ""),
            dict(tc.get("args") or {}),
            str(tc.get("id") or ""),
        )
    name = getattr(tc, "name", None)
    args = getattr(tc, "args", None)
    tid = getattr(tc, "id", None)
    return str(name or ""), dict(args or {}), str(tid or "")


def _dispatch_tool_call(tools_by_name: Dict[str, Any], name: str, args: Dict[str, Any]) -> str:
    fn = tools_by_name.get(name)
    if not fn:
        return f"未知工具: {name}"
    try:
        out = fn.invoke(args)
        return out if isinstance(out, str) else str(out)
    except Exception as e:
        logger.exception("logicon tool error: %s %s", name, args)
        return f"工具执行失败: {type(e).__name__}: {e}"


async def run_logicon_tool_agent(
    *,
    llm: Any,
    env: _ToolEnv,
    max_turns: int = 8,
) -> tuple[Optional[str], List[Dict[str, Any]]]:
    """执行多轮工具调用，返回 (最终分析文本, 轨迹)。"""

    tools = build_logicon_tools(env)
    tools_by_name = {t.name: t for t in tools}
    llm_bind = llm.bind_tools(tools)

    sys_body = (
        "你是科技项目申报书/任务书的「逻辑自洽」辅助审核员。"
        "确定性规则已跑完：你只能基于工具返回的事实描述风险，不得编造数字或冲突条目。"
        "分步取证时可选用："
        "search_document_keywords / get_page_text / find_pages_with_all_keywords / list_likely_section_or_table_titles；"
        "精确定位用 get_raw_text_window；"
        "金额片段用 extract_amount_candidates_from_text，同一口径多个数相加用 sum_numbers_wan；"
        "两数是否「足够接近」可参考 compare_two_numbers_relative_tolerance；"
        "仍以 rerun_dimension_rules 与 get_conflict_and_dimension_digest 为真源。"
        "禁止根据行业经验做主观判断（如“经费占比偏低/偏高”）；仅可引用工具证据。"
        "若冲突总数为 0，不得输出“存在风险/问题”，只可说明“未检出确定冲突”，并给出抽取盲区提示。"
    )
    if "semantic_metric_equivalence_probe" in tools_by_name:
        sys_body += (
            "已提供 semantic_metric_equivalence_probe：仅当需判断两条极短表述是否「同一指标、语义相容」时调用；"
            "不得用它否定或替代规则检出的冲突；每次调用会多一次结构化 LLM。"
        )
    sys_body += (
        "最终用简体中文给出：整体结论（1–3 句）、需重点人工复核的点、与抽取/规则不足有关的提示。"
    )
    system = SystemMessage(content=sys_body)
    human = HumanMessage(
        content=(
            f"doc_id={env.doc_id}，doc_kind={env.doc_kind}。\n"
            "请先调用 get_conflict_and_dimension_digest 或 list_extracted_entities 了解规则层结果；"
            "若需对照表述多样或跨段内容，再用检索/页交集/标题启发式工具缩小范围，必要时 extract_amount_candidates + sum_numbers_wan。"
            "最后直接输出审核员可读的分析，不要只列工具名。"
        )
    )
    messages = [system, human]
    trace: List[Dict[str, Any]] = []
    turns = max(1, min(16, int(max_turns)))

    for turn in range(turns):
        ai = await llm_bind.ainvoke(messages)
        messages.append(ai)
        if not isinstance(ai, AIMessage):
            break
        tcalls = getattr(ai, "tool_calls", None) or []
        if not tcalls:
            text = (getattr(ai, "content", None) or "").strip()
            return (text or None, trace)
        for tc in tcalls:
            name, args, tid = _tool_name_args_id(tc)
            result_text = _dispatch_tool_call(tools_by_name, name, args)
            preview = result_text if len(result_text) <= 1200 else result_text[:1200] + "…"
            trace.append({"tool": name, "args": args, "result_preview": preview})
            messages.append(ToolMessage(content=result_text, tool_call_id=tid or name))

    last = messages[-1]
    if isinstance(last, AIMessage):
        return ((getattr(last, "content", None) or "").strip() or None, trace)
    return (None, trace)


def make_tool_env_from_pipeline(
    *,
    doc_id: str,
    doc_kind: str,
    raw_text: str,
    page_texts: Dict[int, str],
    parser: LogicOnParser,
    amount_tolerance_wan: float,
    date_tolerance_months: int,
    metric_tolerance_ratio: float,
    conflicts: List[ConflictItem],
    dimension_summaries: List[LogicOnDimensionSummary],
    time_entities: List[ExtractedEntity],
    budget_entities: List[ExtractedEntity],
    metric_entities: List[ExtractedEntity],
    equivalence_llm: Optional[Any] = None,
) -> _ToolEnv:
    return _ToolEnv(
        doc_id=doc_id,
        doc_kind=doc_kind,
        raw_text=raw_text,
        page_texts=page_texts,
        parser=parser,
        amount_tolerance_wan=amount_tolerance_wan,
        date_tolerance_months=date_tolerance_months,
        metric_tolerance_ratio=metric_tolerance_ratio,
        conflicts=conflicts,
        dimension_summaries=dimension_summaries,
        time_entities=time_entities,
        budget_entities=budget_entities,
        metric_entities=metric_entities,
        equivalence_llm=equivalence_llm,
    )
