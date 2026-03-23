import json
import logging
import re
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from src.common.llm import get_llm_client, llm_config, get_embedding_client
from src.common.models.perfcheck import (
    DocumentSchema, MetricComparison, ContentComparison, BudgetComparison,
    OtherInfoComparison,
    UnitBudgetComparison,
    PerformanceTarget, ResearchContent
)

logger = logging.getLogger(__name__)

METRIC_LEVELS = {
    "SCI": 3,
    "EI": 2,
    "核心": 1,
    "CSCD": 1,
    "统计源": 0.5,
    "普通": 0
}

DECLARATION_CORE_SOURCE_TAGS = [
    "预期技术指标及创新点",
    "预期经济社会效益",
    "预期绩效目标",
]

TASK_CORE_SOURCE_TAGS = [
    "进度安排和阶段目标",
    "验收",
    "考核指标",
    "项目实施的绩效目标",
    "绩效目标",
]

ALIGNMENT_REFINEMENT_PROMPT = """判断以下两个考核项是否在语义上等价或高度相关：
项目 A: {item_a}
项目 B: {item_b}

注意：
- A 是申报书中的内容，B 是任务书中的内容。
- 如果 B 是 A 的子集或 A 的具体化，也视为匹配。
- 如果 B 明显缩减了 A 的范围或要求，需在理由中说明。

输出格式为 JSON: {{"is_match": bool, "similarity": float, "reason": str}}
"""

FINAL_METRIC_SOURCE_HINTS = [
    "验收",
    "考核指标",
    "绩效目标",
    "预期技术指标",
    "预期经济社会效益",
    "预期绩效目标",
]

STAGE_METRIC_HINTS = [
    "阶段目标",
    "进度安排",
    "年度",
    "中期",
    "季度",
    "里程碑",
]

class PerfCheckDetector:
    """绩效核验差异检测器"""

    def __init__(self, model_name: Optional[str] = None):
        timeout = max(float(getattr(llm_config, "timeout", 30.0) or 30.0), 60.0)
        max_retries = int(getattr(llm_config, "max_retries", 2) or 2)
        self.llm = get_llm_client(
            provider=llm_config.provider or "openai",
            model=(model_name or llm_config.model or None),
            api_key=llm_config.api_key or None,
            base_url=llm_config.base_url or None,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.embedding_client = get_embedding_client()

    async def detect_differences(
        self, 
        apply_schema: DocumentSchema, 
        task_schema: DocumentSchema,
        budget_threshold: float = 0.10
    ) -> Tuple[List[MetricComparison], List[ContentComparison], List[BudgetComparison], List[OtherInfoComparison], List[UnitBudgetComparison]]:
        """执行全量差异检测"""
        metrics_risks = await self._check_metrics(apply_schema.performance_targets, task_schema.performance_targets)
        content_risks = await self._check_contents(apply_schema.research_contents, task_schema.research_contents)
        budget_risks = self._check_budget(apply_schema.budget, task_schema.budget, budget_threshold)
        other_risks = self._check_other(apply_schema, task_schema)
        unit_budget_risks = self._check_units_budget(apply_schema.units_budget, task_schema.units_budget)
        
        return metrics_risks, content_risks, budget_risks, other_risks, unit_budget_risks

    async def _check_metrics(self, apply_targets: List[PerformanceTarget], task_targets: List[PerformanceTarget]) -> List[MetricComparison]:
        """绩效指标核验"""
        comparisons = []
        matched_task_ids = set()

        def is_final_metric(x: PerformanceTarget) -> bool:
            source = (getattr(x, "source", "") or "").strip()
            text = (getattr(x, "text", "") or "").strip()
            merged = f"{source} {text}"
            if any(h in merged for h in STAGE_METRIC_HINTS):
                return False
            if any(h in merged for h in FINAL_METRIC_SOURCE_HINTS):
                return True
            # 无明确信号时按最终指标处理，避免误杀正常考核项。
            return True

        def metric_label(x: PerformanceTarget) -> str:
            detail = (getattr(x, "text", "") or "").strip()
            mtype = (x.type or "").strip()
            if detail:
                return detail[:80]
            return mtype or "未命名指标"

        def key_for_match(x: PerformanceTarget) -> str:
            parts = [
                (x.type or "").strip(),
                (x.subtype or "").strip(),
                (getattr(x, "text", "") or "").strip(),
            ]
            return " ".join([p for p in parts if p])

        def key_for_refine(x: PerformanceTarget) -> str:
            src = (getattr(x, "source", "") or "").strip()
            text = (getattr(x, "text", "") or "").strip()
            head = f"[{src}] " if src else ""
            core = text if text else (x.type or "")
            tail = f"{x.constraint}{x.value}{x.unit}"
            sub = f"（{x.subtype}）" if x.subtype else ""
            return f"{head}{core}{sub} {tail}".strip()

        apply_final_targets = [a for a in apply_targets if is_final_metric(a)]
        task_final_targets = [t for t in task_targets if is_final_metric(t)]

        # 按业务要求：仅比较“最终值”，不与年度/阶段中间值对齐。
        effective_apply_targets = apply_final_targets
        effective_task_targets = task_final_targets

        for a in effective_apply_targets:
            best_match = None
            max_sim = -1.0
            
            # 1. 语义初步匹配
            for t in effective_task_targets:
                if t.id in matched_task_ids:
                    continue
                sim = self._calculate_similarity(key_for_match(a), key_for_match(t))
                if sim > max_sim:
                    max_sim = sim
                    best_match = t
            
            if best_match and max_sim > 0.65:
                # 2. LLM 精排确认
                refinement = await self._refine_alignment(
                    key_for_refine(a),
                    key_for_refine(best_match)
                )
                
                if refinement.get("is_match"):
                    matched_task_ids.add(best_match.id)
                    risk_level, reason = self._judge_metric_risk(a, best_match)
                    src_risk, src_reason = self._judge_metric_source_alignment(a, best_match)
                    if src_risk == "RED":
                        risk_level = "RED"
                        reason = f"{reason}；{src_reason}" if reason else src_reason
                    elif src_risk == "YELLOW" and risk_level == "GREEN":
                        risk_level = "YELLOW"
                        reason = f"{reason}；{src_reason}" if reason else src_reason
                    comparisons.append(MetricComparison(
                        apply_id=a.id,
                        task_id=best_match.id,
                        apply_value=a.value,
                        task_value=best_match.value,
                        apply_subtype=a.subtype,
                        task_subtype=best_match.subtype,
                        unit=a.unit,
                        type=metric_label(a),
                        risk_level=risk_level,
                        reason=reason or refinement.get("reason", "")
                    ))
                    continue

            # 未找到匹配：指标消失
            src = (getattr(a, "source", "") or "").strip()
            src_text = f"（来源: {src}）" if src else ""
            comparisons.append(MetricComparison(
                apply_id=a.id,
                task_id="N/A",
                apply_value=a.value,
                task_value=0,
                apply_subtype=a.subtype,
                task_subtype=None,
                unit=a.unit,
                type=metric_label(a),
                risk_level="RED",
                reason=f"指标 '{metric_label(a)}' 在任务书中缺失{src_text}"
            ))

        if not effective_apply_targets and apply_targets:
            comparisons.append(MetricComparison(
                apply_id="N/A",
                task_id="N/A",
                apply_value=0,
                task_value=0,
                apply_subtype=None,
                task_subtype=None,
                unit="",
                type="核心考核指标",
                risk_level="YELLOW",
                reason="申报书未识别到可比对的最终考核指标（已忽略年度/阶段中间指标）。",
            ))

        if not effective_task_targets and task_targets:
            comparisons.append(MetricComparison(
                apply_id="N/A",
                task_id="N/A",
                apply_value=0,
                task_value=0,
                apply_subtype=None,
                task_subtype=None,
                unit="",
                type="核心考核指标",
                risk_level="RED",
                reason="任务书未识别到最终考核指标（仅发现年度/阶段中间指标或抽取不足），无法完成最终值一致性核验。",
            ))

        return comparisons

    def _is_declaration_core_source(self, source: str) -> bool:
        s = (source or "").strip()
        return any(tag in s for tag in DECLARATION_CORE_SOURCE_TAGS)

    def _is_task_core_source(self, source: str) -> bool:
        s = (source or "").strip()
        return any(tag in s for tag in TASK_CORE_SOURCE_TAGS)

    def _judge_metric_source_alignment(self, a: PerformanceTarget, t: PerformanceTarget) -> Tuple[str, str]:
        """核心考核指标来源章节一致性校验。"""
        a_src = (getattr(a, "source", "") or "").strip()
        t_src = (getattr(t, "source", "") or "").strip()
        if not a_src and not t_src:
            return "GREEN", ""

        a_core = self._is_declaration_core_source(a_src)
        t_core = self._is_task_core_source(t_src)
        if a_core and not t_core:
            return "RED", f"来源章节疑似不对齐（申报书: {a_src}，任务书: {t_src or '未标注'}）"
        if (not a_core) and t_core:
            return "YELLOW", f"来源章节存在偏移（申报书: {a_src or '未标注'}，任务书: {t_src}）"
        return "GREEN", ""

    def _judge_metric_risk(self, a: PerformanceTarget, t: PerformanceTarget) -> Tuple[str, str]:
        """判定指标风险"""
        reasons = []
        risk = "GREEN"

        # 1. 数值下降
        if t.value < a.value:
            risk = "RED"
            reasons.append(f"数值从 {a.value} 缩减至 {t.value}")
        
        # 2. 等级降级
        a_level = METRIC_LEVELS.get(a.subtype, 0) if a.subtype else 0
        t_level = METRIC_LEVELS.get(t.subtype, 0) if t.subtype else 0
        if t_level < a_level:
            risk = "RED"
            reasons.append(f"等级从 {a.subtype} 降级为 {t.subtype}")
            
        # 3. 约束变模糊 (如从 ≥ 变为空)
        if a.constraint == "≥" and not t.constraint:
            if risk != "RED": risk = "YELLOW"
            reasons.append("约束条件变得模糊")

        return risk, "；".join(reasons) if reasons else "指标保持一致"

    async def _check_contents(self, apply_contents: List[ResearchContent], task_contents: List[ResearchContent]) -> List[ContentComparison]:
        """研究内容核验（申报书“一、项目实施内容及目标” vs 任务书“二、项目实施的主要内容任务”）"""
        comparisons = []

        if not apply_contents and not task_contents:
            return [
                ContentComparison(
                    apply_id="N/A",
                    apply_text="",
                    is_covered=False,
                    coverage_score=0.0,
                    risk_level="YELLOW",
                    reason="申报书与任务书均未抽取到可核验研究内容，当前结果不支持“无差异”结论。",
                )
            ]

        if not apply_contents:
            return [
                ContentComparison(
                    apply_id="N/A",
                    apply_text="",
                    is_covered=False,
                    coverage_score=0.0,
                    risk_level="YELLOW",
                    reason="申报书未抽取到研究内容，无法执行缩水核验；请检查“项目实施内容及目标”章节解析。",
                )
            ]

        if not task_contents:
            return [
                ContentComparison(
                    apply_id="N/A",
                    apply_text="",
                    is_covered=False,
                    coverage_score=0.0,
                    risk_level="RED",
                    reason="任务书未抽取到研究内容，无法覆盖申报书研究内容，判定为高风险缩水。",
                )
            ]
        
        for a in apply_contents:
            max_sim = 0.0
            best_reason = ""
            
            for t in task_contents:
                sim_score = self._calculate_similarity(a.text, t.text)
                if sim_score > max_sim:
                    max_sim = sim_score
            
            # LLM 辅助覆盖率判断
            refinement = await self._refine_alignment(a.text, "\n".join([t.text for t in task_contents]))
            is_covered = refinement.get("is_match", False)
            coverage_score = refinement.get("similarity", max_sim)
            
            risk_level = "GREEN"
            if not is_covered:
                risk_level = "RED"
            elif coverage_score < 0.5:
                risk_level = "RED"
            elif coverage_score < 0.8:
                risk_level = "YELLOW"

            reason = refinement.get("reason", "语义匹配度分析")
            if not is_covered:
                reason = (
                    "申报书“一、项目实施内容及目标”在任务书“二、项目实施的主要内容任务”中未覆盖，疑似研究内容缩水；"
                    + reason
                )
                
            comparisons.append(ContentComparison(
                apply_id=a.id,
                apply_text=a.text,
                is_covered=is_covered,
                coverage_score=coverage_score,
                risk_level=risk_level,
                reason=reason
            ))
            
        return comparisons

    def _check_budget(self, apply_budget: Any, task_budget: Any, threshold: float) -> List[BudgetComparison]:
        """预算变更核验"""
        risks = []

        total_a = float(getattr(apply_budget, "total", 0.0) or 0.0)
        total_t = float(getattr(task_budget, "total", 0.0) or 0.0)

        # 仅在申报书存在预算总额时进行总额一致性核验。
        if total_a > 0 and abs(total_a - total_t) > 1e-6:
            total_delta = abs(total_t - total_a) / (total_a if total_a > 0 else 1.0)
            risks.append(BudgetComparison(
                type="预算总额",
                apply_amount=total_a,
                task_amount=total_t,
                apply_ratio=1.0 if total_a > 0 else 0.0,
                task_ratio=1.0 if total_t > 0 else 0.0,
                ratio_delta=total_delta,
                risk_level="RED",
                reason="项目预算总额不一致"
            ))
        
        # 标准化分类名，避免微小差异
        apply_items = {item.type: item.amount for item in apply_budget.items}
        task_items = {item.type: item.amount for item in task_budget.items}
        
        # 以申报书为基线：任务书新增类别但申报书为空时不判差异。
        all_types = set(apply_items.keys())
        
        for btype in all_types:
            a_amt = apply_items.get(btype, 0.0)
            t_amt = task_items.get(btype, 0.0)
            
            a_ratio = a_amt / apply_budget.total if apply_budget.total > 0 else 0
            t_ratio = t_amt / task_budget.total if task_budget.total > 0 else 0
            
            delta = abs(a_ratio - t_ratio)
            risk_level = "GREEN"
            reason = "占比变动正常"

            # 金额不一致优先判定，避免仅看占比遗漏绝对值变化。
            if abs(t_amt - a_amt) > 1e-6:
                risk_level = "RED"
                reason = "金额不一致"
            
            if delta > 0.2 and risk_level != "RED":
                risk_level = "RED"
                reason = f"占比变动幅度剧烈 ({delta:.1%})"
            elif delta > threshold and risk_level == "GREEN":
                risk_level = "YELLOW"
                reason = f"占比变动明显 ({delta:.1%})"
                
            risks.append(BudgetComparison(
                type=btype,
                apply_amount=a_amt,
                task_amount=t_amt,
                apply_ratio=a_ratio,
                task_ratio=t_ratio,
                ratio_delta=delta,
                risk_level=risk_level,
                reason=reason
            ))
            
        return risks

    def _check_other(self, apply_schema: DocumentSchema, task_schema: DocumentSchema) -> List[OtherInfoComparison]:
        res: List[OtherInfoComparison] = []

        def _normalize_text(val: Any) -> str:
            s = str(val or "").strip().lower()
            s = re.sub(r"[，,。；;、\s]+", "", s)
            return s

        def _is_placeholder_empty(val: Any) -> bool:
            token = _normalize_text(val)
            if not token:
                return True
            placeholders = {
                "未明确", "不明确", "未知", "暂无", "无", "无相关信息",
                "未填写", "未填", "未提供", "未说明", "待定",
                "n/a", "na", "none", "null", "-", "--"
            }
            return token in placeholders

        def _effective_text(val: Any) -> str:
            raw = str(val or "").strip()
            return "" if _is_placeholder_empty(raw) else raw

        def _build_member_map(members: list[Any]) -> Dict[str, str]:
            mapping: Dict[str, str] = {}
            for m in members or []:
                name = _normalize_text(getattr(m, "name", ""))
                if not name:
                    continue
                duty = _normalize_text(getattr(m, "duty", ""))
                if name in mapping:
                    # 同名多条记录时做拼接，避免信息被覆盖。
                    mapping[name] = (mapping[name] + duty) if duty else mapping[name]
                else:
                    mapping[name] = duty
            return mapping

        try:
            if apply_schema.project_name and task_schema.project_name:
                if apply_schema.project_name != task_schema.project_name:
                    res.append(OtherInfoComparison(
                        field="项目名称",
                        apply_value=apply_schema.project_name,
                        task_value=task_schema.project_name,
                        risk_level="RED",
                        reason="名称不一致"
                    ))
        except Exception:
            pass
        ai = apply_schema.basic_info or None
        ti = task_schema.basic_info or None
        if ai or ti:
            a_unit = _effective_text(ai.undertaking_unit if ai else None)
            t_unit = _effective_text(ti.undertaking_unit if ti else None)
            if a_unit and a_unit != t_unit:
                res.append(OtherInfoComparison(
                    field="承担单位",
                    apply_value=a_unit,
                    task_value=t_unit,
                    risk_level="RED",
                    reason="承担单位不一致"
                ))
            a_partners = set([
                _effective_text(x) for x in (ai.partner_units if ai else [])
                if _effective_text(x)
            ])
            t_partners = set([
                _effective_text(x) for x in (ti.partner_units if ti else [])
                if _effective_text(x)
            ])
            if a_partners and a_partners != t_partners:
                res.append(OtherInfoComparison(
                    field="合作单位",
                    apply_value="、".join(sorted(a_partners)),
                    task_value="、".join(sorted(t_partners)),
                    risk_level="RED",
                    reason="合作单位列表不一致"
                ))
            a_members_raw = (ai.team_members if ai else []) or []
            t_members_raw = (ti.team_members if ti else []) or []
            a_member_map = _build_member_map(a_members_raw)
            t_member_map = _build_member_map(t_members_raw)
            if a_member_map:
                missing_names: list[str] = []
                duty_mismatch: list[str] = []
                for name, a_duty in a_member_map.items():
                    t_duty = t_member_map.get(name)
                    if t_duty is None:
                        missing_names.append(name)
                        continue
                    # 申报书职责应被任务书职责覆盖；任务书更细化不判差异。
                    if a_duty and (a_duty not in t_duty):
                        duty_mismatch.append(name)

                if missing_names or duty_mismatch:
                    reasons: list[str] = []
                    if missing_names:
                        reasons.append("缺少成员: " + "、".join(sorted(missing_names)))
                    if duty_mismatch:
                        reasons.append("分工未覆盖: " + "、".join(sorted(duty_mismatch)))

                    res.append(OtherInfoComparison(
                        field="项目组成员及分工",
                        apply_value="、".join([
                            f"{(m.name or '').strip()}|{(m.duty or '').strip()}"
                            for m in a_members_raw if (m.name or "").strip()
                        ]),
                        task_value="、".join([
                            f"{(m.name or '').strip()}|{(m.duty or '').strip()}"
                            for m in t_members_raw if (m.name or "").strip()
                        ]),
                        risk_level="RED",
                        reason="；".join(reasons)
                    ))
            a_ip = _effective_text(ai.ip_ownership if ai else None)
            t_ip = _effective_text(ti.ip_ownership if ti else None)
            if a_ip and a_ip != t_ip:
                res.append(OtherInfoComparison(
                    field="知识产权归属",
                    apply_value=a_ip,
                    task_value=t_ip,
                    risk_level="RED",
                    reason="知识产权归属变更"
                ))
        return res

    def _check_units_budget(self, apply_units, task_units) -> List[UnitBudgetComparison]:
        risks: List[UnitBudgetComparison] = []
        a_map: Dict[str, float] = {}
        t_map: Dict[str, float] = {}

        def _norm_unit_name(name: Any) -> str:
            return str(name or "").strip()

        try:
            for r in apply_units or []:
                key = _norm_unit_name(getattr(r, "unit_name", ""))
                if not key:
                    continue
                a_map[key] = a_map.get(key, 0.0) + float(r.amount or 0.0)
            for r in task_units or []:
                key = _norm_unit_name(getattr(r, "unit_name", ""))
                if not key:
                    continue
                t_map[key] = t_map.get(key, 0.0) + float(r.amount or 0.0)
        except Exception:
            pass
        # 以申报书为基线：任务书新增单位但申报书为空时不判差异。
        keys = set(a_map.keys())
        for key in sorted(keys):
            a_amt = a_map.get(key, 0.0)
            t_amt = t_map.get(key, 0.0)
            delta = t_amt - a_amt
            risk = "GREEN"
            reason = "金额一致"
            if abs(delta) > 1e-6:
                risk = "RED"
                reason = "金额不一致"
            risks.append(UnitBudgetComparison(
                unit_name=key,
                type="合计",
                apply_amount=a_amt,
                task_amount=t_amt,
                delta=delta,
                risk_level=risk,
                reason=reason
            ))
        return risks

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算余弦相似度（简单版，实际应使用 embedding）"""
        # 如果没有 embedding 客户端，退化为简单字符串包含或编辑距离
        if not self.embedding_client:
            return 1.0 if text1 in text2 or text2 in text1 else 0.0
            
        try:
            vec1 = np.array(self.embedding_client.embed_query(text1))
            vec2 = np.array(self.embedding_client.embed_query(text2))
            return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
        except Exception as e:
            logger.warning(f"Embedding similarity failed: {e}")
            return 0.5

    async def _refine_alignment(self, item_a: str, item_b: str) -> Dict[str, Any]:
        """LLM 精排与语义判断"""
        prompt = ALIGNMENT_REFINEMENT_PROMPT.format(item_a=item_a, item_b=item_b)
        try:
            response = await self.llm.ainvoke(prompt)
            raw_content = response.content

            # 兼容不同 SDK：content 可能是 str 或分段列表。
            if isinstance(raw_content, str):
                content = raw_content
            elif isinstance(raw_content, list):
                chunks: list[str] = []
                for part in raw_content:
                    if isinstance(part, str):
                        chunks.append(part)
                    elif isinstance(part, dict):
                        text_part = part.get("text")
                        if isinstance(text_part, str):
                            chunks.append(text_part)
                        else:
                            chunks.append(str(part))
                    else:
                        chunks.append(str(part))
                content = "\n".join(chunks)
            else:
                content = str(raw_content)

            if "```json" in content:
                content = content.split("```json", 1)[1].split("```", 1)[0].strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Refinement failed: {e}")
            sim = self._calculate_similarity(item_a, item_b)
            return {"is_match": sim >= 0.75, "similarity": sim, "reason": "LLM 精排失败，已降级为向量相似度判定"}
