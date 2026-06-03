import uuid
from typing import Any, Dict, Optional

from src.common.models.logicon import (
    ConflictItem,
    DocumentGraph,
    ExtractedEntity,
    GraphStats,
    LogicOnDimensionSummary,
    LogicOnResult,
    RuleConfigSnapshot,
    RuleInfo,
)
from src.services.logicon.dimension_report import build_dimension_summaries
from src.services.logicon.parser import LogicOnParser
from src.services.logicon.project_display import extract_logicon_project_display_name
from src.services.logicon.rules import (
    detect_budget_conflicts,
    detect_metric_conflicts,
    detect_metric_conflicts_with_llm,
    detect_time_conflicts,
)
from src.services.logicon.tool_agent import make_tool_env_from_pipeline, run_logicon_tool_agent


class LogicOnAgent:
    def __init__(
        self,
        *,
        amount_tolerance_wan: float = 0.01,
        date_tolerance_days: int = 30,
        metric_tolerance_ratio: float = 0.01,
    ):
        self.parser = LogicOnParser()
        self.amount_tolerance_wan = float(amount_tolerance_wan)
        self.date_tolerance_months = max(0, int(round(float(date_tolerance_days) / 30.0)))
        self.metric_tolerance_ratio = float(metric_tolerance_ratio)

    def _make_dimension_summaries(
        self,
        *,
        conflicts: list[ConflictItem],
        time_entities: list[ExtractedEntity],
        budget_entities: list[ExtractedEntity],
        metric_entities: list[ExtractedEntity],
        time_exec: ExtractedEntity | None,
        time_progress: ExtractedEntity | None,
        budget_total: ExtractedEntity | None,
        budget_items: ExtractedEntity | None,
    ) -> list[LogicOnDimensionSummary]:
        exec_norm = getattr(time_exec, "normalized", {}) if time_exec else {}
        prog_norm = getattr(time_progress, "normalized", {}) if time_progress else {}
        total_norm = getattr(budget_total, "normalized", {}) if budget_total else {}
        items_norm = getattr(budget_items, "normalized", {}) if budget_items else {}
        has_exec = any(exec_norm.get(k) is not None for k in ("start_ym", "end_ym", "duration_months"))
        has_progress = bool(prog_norm.get("milestone_yms") or prog_norm.get("years"))
        has_total = total_norm.get("amount_wan") is not None
        has_items = bool(items_norm.get("items_wan"))
        return build_dimension_summaries(
            conflicts=conflicts,
            time_entities=time_entities,
            budget_entities=budget_entities,
            metric_entities=metric_entities,
            has_exec=has_exec,
            has_progress=has_progress,
            exec_norm=exec_norm,
            prog_norm=prog_norm,
            has_total=has_total,
            has_items=has_items,
            total_norm=total_norm,
            items_norm=items_norm,
            amount_tolerance_wan=self.amount_tolerance_wan,
            date_tolerance_months=self.date_tolerance_months,
        )

    async def _run_metric_branch(
        self,
        *,
        doc_id: str,
        raw_text: str,
        page_texts: Dict[int, str],
        enable_llm: bool,
        warnings: list[str],
        partial: bool,
    ) -> tuple[list[ConflictItem], list[ExtractedEntity], list[str], bool]:
        if enable_llm:
            try:
                from src.common.llm import get_default_llm_client

                llm = get_default_llm_client()
                metric_conflicts, metric_entities = await detect_metric_conflicts_with_llm(
                    doc_id=doc_id,
                    raw_text=raw_text,
                    page_texts=page_texts,
                    llm=llm,
                    metric_tolerance_ratio=self.metric_tolerance_ratio,
                )
            except Exception as e:
                warnings.append(f"指标语义归一化失败，已降级为规则抽取: {str(e)}")
                partial = True
                metric_conflicts, metric_entities = detect_metric_conflicts(
                    doc_id=doc_id,
                    raw_text=raw_text,
                    page_texts=page_texts,
                    metric_tolerance_ratio=self.metric_tolerance_ratio,
                )
        else:
            metric_conflicts, metric_entities = detect_metric_conflicts(
                doc_id=doc_id,
                raw_text=raw_text,
                page_texts=page_texts,
                metric_tolerance_ratio=self.metric_tolerance_ratio,
            )
        return metric_conflicts, metric_entities, warnings, partial

    async def _execute_logicon(
        self,
        *,
        doc_id: str,
        normalized_kind: str,
        raw_text: str,
        page_texts: Dict[int, str],
        enable_llm: bool,
        return_graph: bool,
        enable_agent: bool,
        agent_max_turns: int,
        enable_equivalence_probe: bool = True,
    ) -> LogicOnResult:
        warnings: list[str] = []
        partial = False
        if enable_equivalence_probe and not enable_agent:
            warnings.append("已请求 enable_equivalence_probe，但未启用 Agent，语义等价工具不会注册。")

        time_conflicts, time_entities = detect_time_conflicts(
            doc_id=doc_id,
            parser=self.parser,
            raw_text=raw_text,
            page_texts=page_texts,
            date_tolerance_months=self.date_tolerance_months,
        )
        budget_conflicts, budget_entities = detect_budget_conflicts(
            doc_id=doc_id,
            parser=self.parser,
            raw_text=raw_text,
            page_texts=page_texts,
            amount_tolerance_wan=self.amount_tolerance_wan,
        )
        metric_conflicts, metric_entities, warnings, partial = await self._run_metric_branch(
            doc_id=doc_id,
            raw_text=raw_text,
            page_texts=page_texts,
            enable_llm=enable_llm,
            warnings=warnings,
            partial=partial,
        )

        conflicts = [*time_conflicts, *budget_conflicts, *metric_conflicts]
        entities = [*time_entities, *budget_entities, *metric_entities]

        time_exec = next((e for e in time_entities if getattr(e, "entity_type", "") == "time_exec_period"), None)
        time_progress = next((e for e in time_entities if getattr(e, "entity_type", "") == "time_progress"), None)
        exec_norm = getattr(time_exec, "normalized", {}) if time_exec else {}
        prog_norm = getattr(time_progress, "normalized", {}) if time_progress else {}
        has_exec = any(exec_norm.get(k) is not None for k in ("start_ym", "end_ym", "duration_months"))
        has_progress = bool(prog_norm.get("milestone_yms") or prog_norm.get("years"))
        if not has_exec:
            warnings.append("未抽取到执行期信息（起止年月/执行期年限），时间跨度冲突规则可能无法命中。")
        if not has_progress:
            warnings.append("未抽取到进度安排的时间节点/年份信息，时间跨度冲突规则可能无法命中。")

        budget_total = next((e for e in budget_entities if getattr(e, "entity_type", "") == "budget_total"), None)
        budget_items = next((e for e in budget_entities if getattr(e, "entity_type", "") == "budget_items"), None)
        total_norm = getattr(budget_total, "normalized", {}) if budget_total else {}
        items_norm = getattr(budget_items, "normalized", {}) if budget_items else {}
        has_total = total_norm.get("amount_wan") is not None
        has_items = bool(items_norm.get("items_wan"))
        if not has_total:
            warnings.append("未抽取到预算总额（资金申请/下达总额/预算总额），预算算不平规则可能无法命中。")
        if not has_items:
            warnings.append("未抽取到预算科目明细金额（设备费/材料费/劳务费/业务费等），预算算不平规则可能无法命中。")

        if (not has_exec and not has_progress) or (not has_total and not has_items):
            partial = True

        graph = None
        if return_graph:
            graph = DocumentGraph(
                doc_id=doc_id,
                entities=entities,
                edges=[],
                stats=GraphStats(entity_count=len(entities), edge_count=0),
            )

        enabled = [
            RuleInfo(rule_id="R-TIME-01", name="执行期与进度安排跨度冲突"),
            RuleInfo(rule_id="R-BUDGET-01", name="预算总额与明细求和不一致"),
            RuleInfo(rule_id="R-METRIC-01", name="同一指标多处目标值不一致"),
        ]
        snapshot = RuleConfigSnapshot(
            version="v1",
            enabled_rules=enabled,
            thresholds={
                "amount_tolerance_wan": self.amount_tolerance_wan,
                "date_tolerance_days": self.date_tolerance_months * 30,
                "metric_tolerance_ratio": self.metric_tolerance_ratio,
                "enable_llm": bool(enable_llm),
                "enable_agent": bool(enable_agent),
                "agent_max_turns": int(agent_max_turns),
                "enable_equivalence_probe": bool(enable_equivalence_probe),
            },
        )

        dimension_summaries = self._make_dimension_summaries(
            conflicts=conflicts,
            time_entities=time_entities,
            budget_entities=budget_entities,
            metric_entities=metric_entities,
            time_exec=time_exec,
            time_progress=time_progress,
            budget_total=budget_total,
            budget_items=budget_items,
        )

        agent_analysis: Optional[str] = None
        agent_tool_trace: Optional[list[Dict[str, Any]]] = None
        if enable_agent:
            try:
                from src.common.llm import get_default_llm_client

                llm = get_default_llm_client()
                if hasattr(llm, "bind"):
                    llm = llm.bind(temperature=0.15)
                env = make_tool_env_from_pipeline(
                    doc_id=doc_id,
                    doc_kind=normalized_kind,
                    raw_text=raw_text,
                    page_texts=page_texts,
                    parser=self.parser,
                    amount_tolerance_wan=self.amount_tolerance_wan,
                    date_tolerance_months=self.date_tolerance_months,
                    metric_tolerance_ratio=self.metric_tolerance_ratio,
                    conflicts=conflicts,
                    dimension_summaries=dimension_summaries,
                    time_entities=time_entities,
                    budget_entities=budget_entities,
                    metric_entities=metric_entities,
                    equivalence_llm=(llm if enable_equivalence_probe else None),
                )
                agent_analysis, agent_tool_trace = await run_logicon_tool_agent(
                    llm=llm,
                    env=env,
                    max_turns=agent_max_turns,
                )
            except Exception as e:
                warnings.append(f"Agent 工具调用分析未执行: {str(e)}")
                partial = True

        project_name = extract_logicon_project_display_name(raw_text)
        return LogicOnResult(
            doc_id=doc_id,
            doc_kind=normalized_kind,
            project_name=project_name,
            partial=partial,
            conflicts=conflicts,
            graph=graph,
            rule_snapshot=snapshot,
            warnings=warnings,
            dimension_summaries=dimension_summaries,
            agent_analysis=agent_analysis,
            agent_tool_trace=agent_tool_trace,
        )

    async def check_text(
        self,
        *,
        text: str,
        doc_kind: str = "auto",
        enable_llm: bool = True,
        return_graph: bool = False,
        doc_id: Optional[str] = None,
        enable_agent: bool = True,
        agent_max_turns: int = 8,
        enable_equivalence_probe: bool = True,
        **_: Any,
    ) -> LogicOnResult:
        raw_text = (text or "").strip()
        if not raw_text:
            raise ValueError("text 不能为空")

        normalized_kind = self.parser.normalize_doc_kind(doc_kind, raw_text)
        doc_id = doc_id or f"logicon_{str(uuid.uuid4())[:8]}"
        page_texts: Dict[int, str] = {0: raw_text}
        return await self._execute_logicon(
            doc_id=doc_id,
            normalized_kind=normalized_kind,
            raw_text=raw_text,
            page_texts=page_texts,
            enable_llm=enable_llm,
            return_graph=return_graph,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
        )

    async def check_file(
        self,
        *,
        file_data: bytes,
        file_type: str,
        doc_kind: str = "auto",
        enable_llm: bool = True,
        return_graph: bool = False,
        doc_id: Optional[str] = None,
        enable_agent: bool = True,
        agent_max_turns: int = 8,
        enable_equivalence_probe: bool = True,
        **_: Any,
    ) -> LogicOnResult:
        parsed = await self.parser.parse_file(file_data, file_type)
        raw_text = parsed.raw_text
        if not raw_text:
            raise ValueError("未解析到文本内容")

        normalized_kind = self.parser.normalize_doc_kind(doc_kind, raw_text)
        doc_id = doc_id or f"logicon_{str(uuid.uuid4())[:8]}"
        return await self._execute_logicon(
            doc_id=doc_id,
            normalized_kind=normalized_kind,
            raw_text=raw_text,
            page_texts=parsed.page_texts,
            enable_llm=enable_llm,
            return_graph=return_graph,
            enable_agent=enable_agent,
            agent_max_turns=agent_max_turns,
            enable_equivalence_probe=enable_equivalence_probe,
        )
