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
    "项目实施的预期绩效目标",
    "预期绩效目标",
    "绩效指标",
    "总体目标",
    "实施期目标",
    "满意度",
]

TASK_CORE_SOURCE_TAGS = [
    "项目实施的绩效目标",
    "绩效目标",
    "绩效指标",
    "总体目标",
    "实施期目标",
    "满意度",
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
        class _PT:
            def __init__(self, src):
                self.id = getattr(src, "id", "")
                self.type = getattr(src, "type", "")
                self.subtype = getattr(src, "subtype", None)
                self.text = getattr(src, "text", "")
                self.value = getattr(src, "value", "")
                self.unit = getattr(src, "unit", "")
                self.source = getattr(src, "source", "")

        unit_tokens = ["亩", "个", "篇", "项", "件", "人次", "人", "场", "套", "份", "%", "％", "万元", "元"]
        def _split_metric_by_units(src: PerformanceTarget) -> List[PerformanceTarget]:
            s = f"{getattr(src, 'type', '')} {getattr(src, 'text', '')}"
            pairs = []
            for m in re.finditer(r"(\d+(?:\.\d+)?)(?:\s*)([亩个篇项件人次人场套份%％万元元])", s):
                num = m.group(1)
                unit = m.group(2)
                if unit not in unit_tokens:
                    continue
                pairs.append((num, unit))
            if len(pairs) <= 1:
                return [src]
            outs: List[PerformanceTarget] = []
            for i, (num, unit) in enumerate(pairs, start=1):
                v = _PT(src)
                v.id = f"{getattr(src, 'id', '')}-u{i}"
                v.value = num
                v.unit = unit
                # 标记子类型以帮助区分（不影响展示的主类型）
                if unit in {"亩"}:
                    v.subtype = (getattr(src, "subtype", None) or "面积")
                elif unit in {"个"}:
                    v.subtype = (getattr(src, "subtype", None) or "数量")
                outs.append(v)
            return outs

        apply_targets = [y for x in apply_targets for y in _split_metric_by_units(x)]
        task_targets = [y for x in task_targets for y in _split_metric_by_units(x)]

        def _value_for_compare(v: Any) -> float:
            """将值统一为可比较数值：区间取上界，单值直接转 float。"""
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v or "").strip()
            if not s:
                return 0.0
            nums = re.findall(r"\d+(?:\.\d+)?", s)
            if not nums:
                return 0.0
            return float(nums[-1])

        def _display_value(x: PerformanceTarget) -> str:
            unit = str(getattr(x, "unit", "") or "")
            constraint = str(getattr(x, "constraint", "") or "").strip()
            if re.search(r"\d\s*[-~—–~到至]\s*\d", constraint):
                return f"{constraint}{unit}"
            raw = getattr(x, "value", "")
            if isinstance(raw, (int, float)):
                val_text = f"{float(raw):g}"
            else:
                s = str(raw or "").strip()
                val_text = s if s else f"{_value_for_compare(raw):g}"
            return f"{val_text}{unit}"

        def _hard_norm_metric_name(x: PerformanceTarget) -> str:
            """用于规则直匹配的指标名标准化，尽量忽略单位括号与数值尾缀差异。"""
            raw_name = (getattr(x, "type", "") or "").strip() or (getattr(x, "text", "") or "").strip()
            s = str(raw_name).lower().strip()
            s = re.sub(r"^(?:项目)?实施期目标\s*[:：]?", "", s)
            s = re.sub(r"^(?:总体目标\s*[-:：]\s*实施期目标|总体目标\s*[:：]?|总体\s*目标\s*[:：]?)", "", s)
            s = re.sub(r"^[\(\（](?:\d+|[一二三四五六七八九十百千万亿]|[a-z])[）\)]\s*", "", s)
            s = re.sub(r"^\d+[.、．\s]+", "", s)
            # 去掉括号中的单位提示，如“（篇）”“（人次）”。
            s = re.sub(r"[（(][^()（）]{1,8}[)）]", "", s)
            # 去掉末尾范围/数值+单位，如“6-8份”“40人次”。
            s = re.sub(r"\s*(?:>=|<=|>|<|＝|=|≥|≤)?\s*\d+(?:\.\d+)?(?:\s*[-~—–~到至]\s*\d+(?:\.\d+)?)?\s*(?:篇|项|件|名|人次|人|场|%|％|万元|元|套|份|亩)?\s*$", "", s)
            # 统一高频后缀，避免“xx数量”和“xx”无法命中。
            s = re.sub(r"(?:数量|数)$", "", s)
            s = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", s)
            return s

        def is_final_metric(x: PerformanceTarget) -> bool:
            source = (getattr(x, "source", "") or "").strip()
            text = (getattr(x, "text", "") or "").strip()
            merged = f"{source} {text}"
            src_norm = self._normalize_source_text(source)

            # “总体目标-实施期目标”属于同一张绩效目标表中的最终口径，优先放行。
            if ("总体目标" in src_norm) or ("实施期目标" in src_norm):
                return True
            if any(h in merged for h in STAGE_METRIC_HINTS):
                return False
            if any(h in merged for h in FINAL_METRIC_SOURCE_HINTS):
                return True
            # 无明确信号时按最终指标处理，避免误杀正常考核项。
            return True

        def metric_label(x: PerformanceTarget) -> str:
            detail = (getattr(x, "text", "") or "").strip()
            mtype = (x.type or "").strip()

            def _strip_metric_prefix(s: str) -> str:
                text = str(s or "").strip()
                # 去掉章节性前缀，避免“实施期目标：xxx”污染指标名称展示。
                text = re.sub(r"^\s*(?:[（(]?\d+[）)]?[.、)]?\s*)", "", text)
                text = re.sub(r"^(?:项目)?实施期目标\s*[:：]\s*", "", text)
                text = re.sub(r"^(?:项目)?实施期\s*目标\s*[:：]\s*", "", text)
                text = re.sub(r"^(?:项目)?实施期目标\s+", "", text)
                text = re.sub(r"^(?:项目)?预期目标\s*[:：]\s*", "", text)
                text = re.sub(r"^(?:项目)?预期\s*绩效目标\s*[:：]\s*", "", text)
                text = re.sub(r"^(?:项目)?绩效目标\s*[:：]\s*", "", text)
                text = re.sub(r"^(?:项目)?考核指标\s*[:：]\s*", "", text)
                return text.strip()

            def _strip_metric_tail_value(s: str) -> str:
                text = str(s or "").strip()
                # 去掉末尾范围值，如“6-8份”“6~8项”“6至8亩”。
                text = re.sub(r"\s*(?:[:：]?\s*)?(?:>=|≤|<=|>|<|＝|=)?\s*\d+(?:\.\d+)?\s*(?:[-~—–~至到]\s*\d+(?:\.\d+)?)\s*(?:篇|项|件|名|人次|人|场|%|％|万元|元|套|份|亩)?\s*$", "", text)
                # 去掉末尾目标值，如“（人）30”“20件”“>=95%”“95%”等，仅保留指标名称。
                text = re.sub(r"\s*(?:[:：]?\s*)?(?:>=|≤|>=|<=|>|<|＝|=)?\s*\d+(?:\.\d+)?\s*(?:篇|项|件|名|人次|人|场|%|％|万元|元|套|份|亩)?\s*$", "", text)
                text = re.sub(r"\s*(?:以上|以下)$", "", text)
                return text.strip(" ：:，,；;-—~～")

            detail = _strip_metric_prefix(detail)
            mtype = _strip_metric_prefix(mtype)
            mtype = _strip_metric_tail_value(mtype)
            detail = _strip_metric_tail_value(detail)

            # 类型列优先展示 type 字段，避免 text 字段把数值带进来。
            if mtype:
                return mtype[:80]
            if detail:
                return detail[:80]
            return "未命名指标"

        def key_for_match(x: PerformanceTarget) -> str:
            def _normalize_metric_match_text(s: str) -> str:
                text = str(s or "").lower().strip()
                if not text:
                    return ""

                # 去掉常见阶段性前缀，避免“实施期内培养研究生 5 人”这类句式影响对齐。
                text = re.sub(r"^(?:项目)?实施期(?:内)?", "", text)
                text = re.sub(r"^(?:项目)?预期", "", text)
                text = re.sub(r"^(?:项目)?绩效目标", "", text)
                text = re.sub(r"^(?:项目)?考核指标", "", text)

                # 去掉数值、比较符和单位，保留指标语义主干用于匹配。
                text = re.sub(r"[<>＝=≥≤]+", " ", text)
                text = re.sub(r"\d+(?:\.\d+)?", " ", text)
                text = re.sub(r"(篇|项|件|名|人次|人|场|%|％|万元|元)", " ", text)

                # 统一高频同义表达。
                text = text.replace("数量", "")
                text = text.replace("收录的", "")
                text = text.replace("发表", "发表")
                text = text.replace("选育", "培育")
                text = text.replace("示范基地", "种植基地")
                text = text.replace("标准化种植技术体系", "种植技术体系")
                # 指标同义项统一
                text = text.replace("申请发明专利数", "申请发明专利")
                text = text.replace("申请专利", "申请发明专利")
                text = text.replace("制定标准数量", "制定标准")
                text = text.replace("制定地方标准", "制定标准")
                text = text.replace("发表论文数", "发表论文")
                text = text.replace("发表论文数量", "发表论文")

                text = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", text)
                return text
            parts = [
                _normalize_metric_match_text(x.type or ""),
                _normalize_metric_match_text(x.subtype or ""),
                _normalize_metric_match_text(getattr(x, "text", "") or ""),
            ]
            # 将单位作为匹配键的一部分，避免“亩/个”等跨单位误匹配
            unit_part = str(getattr(x, "unit", "") or "").strip()
            if unit_part:
                parts.append(unit_part)
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

        # 先做规则直匹配：同名（标准化后）优先配对，减少语义阶段误判为“缺失”。
        task_name_index: Dict[str, List[PerformanceTarget]] = {}
        for t in task_final_targets:
            key = _hard_norm_metric_name(t)
            if not key:
                continue
            task_name_index.setdefault(key, []).append(t)

        # 按业务要求：metrics_risks 仅比较
        # 申报书“五、项目实施的预期绩效目标” vs 任务书“七、项目实施的绩效目标”。
        effective_apply_targets = [a for a in apply_final_targets if self._is_declaration_core_source(getattr(a, "source", ""))]
        effective_task_targets = [t for t in task_final_targets if self._is_task_core_source(getattr(t, "source", ""))]

        for a in effective_apply_targets:
            a_key = _hard_norm_metric_name(a)
            if a_key:
                direct_candidates = [
                    t for t in task_name_index.get(a_key, [])
                    if t.id not in matched_task_ids
                ]
                if direct_candidates:
                    # 同名多条时优先取数值最接近者。
                    best_direct = min(
                        direct_candidates,
                        key=lambda t: abs(_value_for_compare(getattr(t, "value", 0.0)) - _value_for_compare(getattr(a, "value", 0.0))),
                    )
                    matched_task_ids.add(best_direct.id)
                    risk_level, reason = self._judge_metric_risk(a, best_direct)
                    src_risk, src_reason = self._judge_metric_source_alignment(a, best_direct)
                    if src_risk == "RED":
                        risk_level = "RED"
                        reason = f"{reason}；{src_reason}" if reason else src_reason
                    elif src_risk == "YELLOW" and risk_level == "GREEN":
                        risk_level = "YELLOW"
                        reason = f"{reason}；{src_reason}" if reason else src_reason
                    comparisons.append(MetricComparison(
                        apply_id=a.id,
                        task_id=best_direct.id,
                        apply_value=_value_for_compare(a.value),
                        task_value=_value_for_compare(best_direct.value),
                        apply_display=_display_value(a),
                        task_display=_display_value(best_direct),
                        apply_subtype=a.subtype,
                        task_subtype=best_direct.subtype,
                        unit=a.unit,
                        type=metric_label(a),
                        risk_level=risk_level,
                        reason=reason or "指标保持一致",
                    ))
                    continue

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
                        apply_value=_value_for_compare(a.value),
                        task_value=_value_for_compare(best_match.value),
                        apply_display=_display_value(a),
                        task_display=_display_value(best_match),
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
                apply_value=_value_for_compare(a.value),
                task_value=0,
                apply_display=_display_value(a),
                task_display=f"0{a.unit}",
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
                reason="申报书第五部分“项目实施的预期绩效目标”未识别到可比对指标。",
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
                reason="任务书第七部分“项目实施的绩效目标”未识别到可比对指标，无法完成一致性核验。",
            ))

        return comparisons

    def _is_declaration_core_source(self, source: str) -> bool:
        s = self._normalize_source_text(source)
        return any(self._normalize_source_text(tag) in s for tag in DECLARATION_CORE_SOURCE_TAGS)

    def _is_task_core_source(self, source: str) -> bool:
        s = self._normalize_source_text(source)
        return any(self._normalize_source_text(tag) in s for tag in TASK_CORE_SOURCE_TAGS)

    def _normalize_source_text(self, source: str) -> str:
        s = str(source or "").strip().lower()
        # 兼容 PDF/OCR 的空格、分隔符、换行等噪声。
        s = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", s)
        return s

    def _judge_metric_source_alignment(self, a: PerformanceTarget, t: PerformanceTarget) -> Tuple[str, str]:
        """核心考核指标来源章节一致性校验。"""
        a_src = (getattr(a, "source", "") or "").strip()
        t_src = (getattr(t, "source", "") or "").strip()
        if not a_src and not t_src:
            return "GREEN", ""

        # 业务特例：申报书“实施期目标”与任务书“绩效目标/验收考核指标”属于正常章节映射。
        a_src_norm = self._normalize_source_text(a_src)
        t_src_norm = self._normalize_source_text(t_src)
        if ("实施期目标" in a_src_norm) and (
            ("绩效目标" in t_src_norm) or ("验收的考核指标" in t_src_norm) or ("考核指标" in t_src_norm)
        ):
            return "GREEN", ""

        a_core = self._is_declaration_core_source(a_src)
        t_core = self._is_task_core_source(t_src)
        if a_core and not t_core:
            return "RED", f"来源章节疑似不对齐（申报书: {a_src}，任务书: {t_src or '未标注'}）"
        if (not a_core) and t_core:
            return "YELLOW", ""
        return "GREEN", ""

    def _judge_metric_risk(self, a: PerformanceTarget, t: PerformanceTarget) -> Tuple[str, str]:
        """判定指标风险"""
        reasons = []
        risk = "GREEN"

        def _value_for_compare(v: Any) -> float:
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v or "").strip()
            nums = re.findall(r"\d+(?:\.\d+)?", s)
            return float(nums[-1]) if nums else 0.0

        a_val = _value_for_compare(getattr(a, "value", 0.0))
        t_val = _value_for_compare(getattr(t, "value", 0.0))

        def _norm_constraint(c: Any) -> str:
            s = str(c or "").strip()
            if not s:
                return ""
            if s in {">=", "≥", "以上", "不少于", "不低于", "达到", "达"}:
                return "ge"
            if s in {"<=", "≤", "以下", "不超过", "控制在"}:
                return "le"
            # 区间约束（如 6-8）单独标记
            if re.search(r"\d\s*[-~—–~到至]\s*\d", s):
                return "range"
            return s

        # 1. 数值下降
        if t_val < a_val:
            risk = "RED"
            reasons.append(f"数值从 {a_val} 缩减至 {t_val}")
        
        # 2. 等级降级
        a_level = METRIC_LEVELS.get(a.subtype, 0) if a.subtype else 0
        t_level = METRIC_LEVELS.get(t.subtype, 0) if t.subtype else 0
        if t_level < a_level:
            risk = "RED"
            reasons.append(f"等级从 {a.subtype} 降级为 {t.subtype}")
            
        # 3. 约束变模糊：仅在约束缺失且数值无法证明“至少同等严格”时提示。
        a_c = _norm_constraint(getattr(a, "constraint", ""))
        t_c = _norm_constraint(getattr(t, "constraint", ""))
        if a_c and (not t_c):
            should_warn = False
            if a_c == "ge":
                # 下限约束缺失：任务值若未达到申报值则已被 RED；等于或更高不再提示。
                should_warn = t_val < a_val
            elif a_c == "le":
                # 上限约束缺失：任务值若超出申报上限才提示。
                should_warn = t_val > a_val
            elif a_c == "range":
                # 区间约束缺失时，任务值需落在申报区间内才视为不降级。
                raw = str(getattr(a, "constraint", "") or "")
                nums = re.findall(r"\d+(?:\.\d+)?", raw)
                if len(nums) >= 2:
                    lo = float(nums[0])
                    hi = float(nums[-1])
                    should_warn = not (lo <= t_val <= hi)
            else:
                should_warn = False

            if should_warn and risk != "RED":
                risk = "YELLOW"
                reasons.append("约束条件变得模糊")

        return risk, "；".join(reasons) if reasons else "指标保持一致"

    async def _check_contents(self, apply_contents: List[ResearchContent], task_contents: List[ResearchContent]) -> List[ContentComparison]:
        """研究内容核验（申报书“一、项目实施内容及目标” vs 任务书“二、项目实施的主要内容任务”）"""
        comparisons = []

        def _normalize_content_text(val: str) -> str:
            s = str(val or "").strip().lower()
            # 去掉常见条目序号前缀，避免“（1）/1.”等编号影响一致性判断。
            s = re.sub(r"^\s*(?:（?\d+）?|\d+[.、)]|[一二三四五六七八九十]+[、.．)])\s*", "", s)
            return re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", s)

        def _extract_key_phrases(val: str, *, max_items: int = 6) -> List[str]:
            text = str(val or "").strip()
            if not text:
                return []
            text = re.sub(r"^\s*(?:（?\d+）?|\d+[.、)]|[一二三四五六七八九十]+[、.．)])\s*", "", text)
            parts = re.split(r"[；;。\n]", text)
            out: List[str] = []
            seen: set[str] = set()
            for p in parts:
                seg = str(p or "").strip(" ，,。；;:")
                if len(seg) < 6:
                    continue
                key = _normalize_content_text(seg)
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(seg)
                if len(out) >= max_items:
                    break
            return out

        def _missing_key_phrases(apply_text: str, task_text: str) -> List[str]:
            task_norm = _normalize_content_text(task_text)
            misses: List[str] = []
            for ph in _extract_key_phrases(apply_text):
                if _normalize_content_text(ph) not in task_norm:
                    misses.append(ph)
            return misses[:4]

        if not apply_contents and not task_contents:
            return [
                ContentComparison(
                    apply_id="N/A",
                    apply_text="",
                    task_text="",
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
                    task_text="",
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
                    task_text="",
                    is_covered=False,
                    coverage_score=0.0,
                    risk_level="RED",
                    reason="任务书未抽取到研究内容，无法覆盖申报书研究内容，判定为高风险缩水。",
                )
            ]

        item_results: List[Dict[str, Any]] = []
        # 结合关键短语覆盖与文本相似度进行对齐；若数量接近，优先按序对齐
        def _phrase_overlap_score(a_text: str, b_text: str) -> float:
            a_ph = set(_extract_key_phrases(a_text))
            if not a_ph:
                return 0.0
            b_norm = _normalize_content_text(b_text)
            hit = sum(1 for ph in a_ph if _normalize_content_text(ph) in b_norm)
            return hit / max(1, len(a_ph))

        by_index_initial = (len(apply_contents) >= 2 and len(task_contents) >= 2 and abs(len(apply_contents) - len(task_contents)) <= 2)

        for idx, a in enumerate(apply_contents):
            a_norm = _normalize_content_text(a.text)
            max_score = -1.0
            best_task_text = ""

            # 初始候选：按序对齐，避免完全依赖相似度误配
            if by_index_initial and idx < len(task_contents):
                cand_text = task_contents[idx].text
                max_score = max(self._calculate_similarity(a.text, cand_text), _phrase_overlap_score(a.text, cand_text))
                best_task_text = cand_text

            # 遍历寻找更优候选：综合“相似度 + 关键短语覆盖”
            for t in task_contents:
                sim_score = self._calculate_similarity(a.text, t.text)
                cov_score = _phrase_overlap_score(a.text, t.text)
                score = max(sim_score, cov_score)
                if cov_score >= 0.6:
                    score = max(score, (cov_score * 0.75) + (sim_score * 0.25))
                if score > max_score:
                    max_score = score
                    best_task_text = t.text

            # 完全一致优先：避免 LLM 给出 0.9 这类“保守分”。
            exact_hit = False
            if a_norm:
                for t in task_contents:
                    t_norm = _normalize_content_text(t.text)
                    if t_norm and t_norm == a_norm:
                        exact_hit = True
                        best_task_text = t.text
                        break

            if exact_hit:
                item_results.append({
                    "apply_id": a.id,
                    "apply_text": a.text,
                    "task_text": best_task_text,
                    "is_covered": True,
                    "coverage_score": 1.0,
                    "reason": "文本一致",
                })
                continue

            # LLM 辅助覆盖率判断
            refinement = await self._refine_alignment(a.text, best_task_text)
            is_covered = refinement.get("is_match", False)
            # 使用综合得分作为下限，避免覆盖率因文本很长被低估
            combined_baseline = max_score if max_score >= 0 else 0.0
            coverage_score = float(refinement.get("similarity", combined_baseline) or 0.0)
            coverage_score = max(0.0, min(1.0, coverage_score))
            if is_covered:
                # 已覆盖时不低于规则相似度，避免 LLM 低估造成“已覆盖但仅 90%”的观感偏差。
                coverage_score = max(coverage_score, float(combined_baseline))

            b_norm = _normalize_content_text(best_task_text)
            if a_norm and b_norm and a_norm == b_norm:
                is_covered = True
                coverage_score = 1.0

            # 若关键短语覆盖很高，则直接认定覆盖并抬升得分
            phrase_cov = _phrase_overlap_score(a.text, best_task_text)
            if phrase_cov >= 0.8 and not is_covered:
                is_covered = True
                coverage_score = max(coverage_score, phrase_cov)

            if is_covered:
                reason = "任务书为申报书具体化"
            else:
                missing = _missing_key_phrases(a.text, best_task_text)
                if missing:
                    reason = "任务书未覆盖关键短语：" + "、".join(missing)
                else:
                    reason = "任务书未覆盖关键短语：未识别到对应关键短语"

            item_results.append({
                "apply_id": a.id,
                "apply_text": a.text,
                "task_text": best_task_text,
                "is_covered": bool(is_covered),
                "coverage_score": float(coverage_score),
                "reason": reason,
            })

        total_items = len(item_results)
        covered_items = sum(1 for x in item_results if x["is_covered"])

        if covered_items == total_items:
            global_risk = "GREEN"
            global_reason = "任务书覆盖申报书全部研究内容，判定为“内容一致或扩展”。"
        elif covered_items == 0:
            global_risk = "RED"
            global_reason = "任务书未覆盖申报书核心内容，判定为“严重缩水”。"
        else:
            global_risk = "YELLOW"
            global_reason = f"任务书仅覆盖部分申报书内容（{covered_items}/{total_items}），判定为“部分缩水”。"

        for item in item_results:
            item_risk = "RED"
            if item["is_covered"]:
                item_risk = "GREEN" if float(item.get("coverage_score", 0.0) or 0.0) >= 0.85 else "YELLOW"
            comparisons.append(ContentComparison(
                apply_id=item["apply_id"],
                apply_text=item["apply_text"],
                task_text=item.get("task_text", ""),
                is_covered=item["is_covered"],
                coverage_score=item["coverage_score"],
                risk_level=item_risk,
                reason=item["reason"]
            ))

        return comparisons

    def _check_budget(self, apply_budget: Any, task_budget: Any, threshold: float) -> List[BudgetComparison]:
        """预算变更核验"""
        risks = []

        # 叶子科目优先，避免“直接费用/财政资金”等层级项与明细项同时比较造成误报。
        leaf_priority = [
            "设备费",
            "业务费",
            "劳务费",
            "材料费",
            "测试化验加工费",
            "燃料动力费",
            "差旅费",
            "会议费",
            "国际合作与交流费",
            "出版/文献/信息传播/知识产权事务费",
            "专家咨询费",
            "管理费",
            "其他支出",
        ]
        leaf_set = set(leaf_priority)
        parent_buckets = {
            "省级财政资金",
            "自筹资金",
            "财政资金",
            "直接费用",
            "间接费用",
            "总计",
            "合计",
            "总额",
            "预算总额",
            "经费总额",
            "总预算",
        }

        alias_map = {
            "检验检测费": "测试化验加工费",
            "测试费": "测试化验加工费",
            "测试化验费": "测试化验加工费",
            "测试化验加工费用": "测试化验加工费",
            "出版文献信息传播知识产权事务费": "出版/文献/信息传播/知识产权事务费",
            "出版文献信息传播费": "出版/文献/信息传播/知识产权事务费",
            "知识产权事务费": "出版/文献/信息传播/知识产权事务费",
            "国际合作交流费": "国际合作与交流费",
        }

        def _canonical_budget_type(name: Any) -> str:
            s = str(name or "").strip()
            if not s:
                return ""

            s = re.sub(r"\s+", "", s)
            s = re.sub(r"^[（(]?[一二三四五六七八九十]+[)）、.．]", "", s)
            s = re.sub(r"^\d+[、.．)]", "", s)
            s = re.sub(r"^其中[:：]", "", s)
            s = re.sub(r"^预算科目[:：]", "", s)
            s = s.strip(":：;；|，,")

            if s in alias_map:
                return alias_map[s]
            return s

        def _aggregate_items(items: Any) -> tuple[dict[str, float], list[str]]:
            merged: dict[str, float] = {}
            order: list[str] = []
            if not isinstance(items, list):
                return merged, order

            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_type = item.get("type")
                ctype = _canonical_budget_type(raw_type)
                if not ctype:
                    continue
                amount = float(item.get("amount", 0.0) or 0.0)

                # 同类多次出现时取绝对值更大的金额，避免 0/空行覆盖有效值。
                prev = float(merged.get(ctype, 0.0) or 0.0)
                merged[ctype] = amount if abs(amount) >= abs(prev) else prev

                if ctype not in order:
                    order.append(ctype)

            return merged, order

        def _is_total_item_name(name: Any) -> bool:
            s = str(name or "").strip()
            s = re.sub(r"\s+", "", s)
            return s in {"合计", "总计"}

        total_a = float(getattr(apply_budget, "total", 0.0) or 0.0)
        total_t = float(getattr(task_budget, "total", 0.0) or 0.0)

        if total_a > 0 or total_t > 0:
            total_diff = abs(total_t - total_a)
            total_delta = total_diff / (total_a if total_a > 0 else 1.0)
            total_risk = "GREEN"
            total_reason = "项目预算总额一致"
            if total_diff > 1e-6:
                total_risk = "RED"
                total_reason = f"项目预算总额不一致（申报 {total_a:g} 万元，任务 {total_t:g} 万元，差额 {total_diff:g} 万元，差异率 {total_delta:.1%}）"
            risks.append(BudgetComparison(
                type="预算总额",
                apply_amount=total_a,
                task_amount=total_t,
                apply_ratio=1.0 if total_a > 0 else 0.0,
                task_ratio=1.0 if total_t > 0 else 0.0,
                ratio_delta=0.0,
                risk_level=total_risk,
                reason=total_reason
            ))
        
        apply_raw_items = [
            {"type": getattr(item, "type", ""), "amount": float(getattr(item, "amount", 0.0) or 0.0)}
            for item in (getattr(apply_budget, "items", []) or [])
        ]
        task_raw_items = [
            {"type": getattr(item, "type", ""), "amount": float(getattr(item, "amount", 0.0) or 0.0)}
            for item in (getattr(task_budget, "items", []) or [])
        ]

        apply_items, apply_order = _aggregate_items(apply_raw_items)
        task_items, task_order = _aggregate_items(task_raw_items)

        if total_a > 0 or total_t > 0:
            apply_items = {k: v for k, v in apply_items.items() if not _is_total_item_name(k) and k not in parent_buckets}
            task_items = {k: v for k, v in task_items.items() if not _is_total_item_name(k) and k not in parent_buckets}
            apply_order = [k for k in apply_order if k in apply_items]
            task_order = [k for k in task_order if k in task_items]

        # 双方存在叶子科目时，仅比较叶子科目，避免层级项重复触发“金额不一致”。
        apply_leaf = {k: v for k, v in apply_items.items() if k in leaf_set}
        task_leaf = {k: v for k, v in task_items.items() if k in leaf_set}
        if apply_leaf or task_leaf:
            apply_items = apply_leaf
            task_items = task_leaf
            ordered_types = [k for k in leaf_priority if (k in apply_items or k in task_items)]
        else:
            ordered_types = []
            seen_types: set[str] = set()
            for t in apply_order:
                if t and t not in seen_types:
                    ordered_types.append(t)
                    seen_types.add(t)
            for t in task_order:
                if t and t not in seen_types:
                    ordered_types.append(t)
                    seen_types.add(t)

        for btype in ordered_types:
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

        def _append_other(field: str, apply_value: str, task_value: str, mismatch_reason: str) -> None:
            a = str(apply_value or "").strip()
            t = str(task_value or "").strip()
            mismatch = bool(a != t)
            if not a and not t:
                res.append(OtherInfoComparison(
                    field=field,
                    apply_value="",
                    task_value="",
                    risk_level="GREEN",
                    reason="双方均未抽取到有效值",
                ))
                return

            res.append(OtherInfoComparison(
                field=field,
                apply_value=a,
                task_value=t,
                risk_level=("RED" if mismatch else "GREEN"),
                reason=(mismatch_reason if mismatch else "一致"),
            ))

        def _normalize_partner_unit(name: Any) -> str:
            s = str(name or "").strip()
            if not s:
                return ""
            s = re.sub(r"\s+", "", s)
            # 兼容任务书中混入的签章、日期、经办人等噪声。
            s = re.split(
                r"(?:（?公章）?|日期[:：]?|负责人[:：]?|经办人[:：]?|归口管理单位[:：]?|科研计划专用章|甲方[:：]?|乙方[:：]?|丙方[:：]?"
                r"|承担临床|临床疗效观察|生物样本采集|协助项目承担单位|知识产权归属|项目合作单位|论文撰写|七、项目实施的绩效目标|\[表格表头)",
                s,
                maxsplit=1,
            )[0]
            # 去掉括号中的别名/说明，统一按主名比较
            s = re.split(r"[（(]", s, maxsplit=1)[0]
            # 去掉明显的句式噪声
            s = re.sub(r"可以将.*$", "", s)
            s = s.strip("，,;；。()（）")
            if len(s) < 3:
                return ""
            return s

        def _normalize_project_name(val: Any) -> str:
            s = str(val or "").strip()
            s = re.sub(r"[\s\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", s)
            if not s:
                return ""
            s = s.replace("从", "")
            s = s.replace("探讨", "")
            s = s.replace("临床研究", "临床疗效")
            s = s.replace("作用机制", "干预机制")
            return s

        def _normalize_partner_units(items: list[Any]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for x in items or []:
                name = _normalize_partner_unit(x)
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(name)
            return out

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

        def _normalize_duty_text(val: Any) -> str:
            text = _normalize_text(val)
            if not text:
                return ""
            # 统一常见负责人表述，减少同义措辞造成的误报。
            leader_aliases = [
                "主持项目全面实施",
                "主持项目实施",
                "主持全面实施",
                "负责项目全面实施",
                "项目全面实施负责人",
                "项目总负责人",
                "项目负责人",
                "负责人",
            ]
            if any(alias in text for alias in leader_aliases):
                return "项目负责人"
            return text

        def _duty_is_covered(apply_duty: str, task_duty: str) -> bool:
            if not apply_duty:
                return True
            if not task_duty:
                return False
            if apply_duty in task_duty:
                return True

            a_norm = _normalize_duty_text(apply_duty)
            t_norm = _normalize_duty_text(task_duty)
            if not a_norm:
                return True
            if not t_norm:
                return False
            return (a_norm in t_norm) or (t_norm in a_norm)

        a_project = _effective_text(getattr(apply_schema, "project_name", ""))
        t_project = _effective_text(getattr(task_schema, "project_name", ""))
        _append_other("项目名称", a_project, t_project, "名称不一致")
        if res and res[-1].field == "项目名称":
            a_norm = _normalize_project_name(a_project)
            t_norm = _normalize_project_name(t_project)
            if a_norm and t_norm:
                sim = self._calculate_similarity(a_norm, t_norm)
                if (a_norm in t_norm) or (t_norm in a_norm) or sim >= 0.62:
                    res[-1].risk_level = "GREEN"
                    res[-1].reason = "一致"

        ai = apply_schema.basic_info or None
        ti = task_schema.basic_info or None

        a_unit = _effective_text(ai.undertaking_unit if ai else None)
        t_unit = _effective_text(ti.undertaking_unit if ti else None)
        _append_other("承担单位", a_unit, t_unit, "承担单位不一致")

        a_partners = _normalize_partner_units([
            _effective_text(x) for x in (ai.partner_units if ai else [])
            if _effective_text(x)
        ])
        t_partners = _normalize_partner_units([
            _effective_text(x) for x in (ti.partner_units if ti else [])
            if _effective_text(x)
        ])
        a_partner_set = set(a_partners)
        t_partner_set = set(t_partners)
        _append_other(
            "合作单位",
            json.dumps(a_partners, ensure_ascii=False),
            json.dumps(t_partners, ensure_ascii=False),
            "合作单位列表不一致",
        )
        if res and res[-1].field == "合作单位" and a_partner_set == t_partner_set:
            res[-1].risk_level = "GREEN"
            res[-1].reason = "一致"

        a_members_raw = (ai.team_members if ai else []) or []
        t_members_raw = (ti.team_members if ti else []) or []
        a_member_map = _build_member_map(a_members_raw)
        t_member_map = _build_member_map(t_members_raw)
        missing_names: list[str] = []
        duty_mismatch: list[str] = []
        for name, a_duty in a_member_map.items():
            t_duty = t_member_map.get(name)
            if t_duty is None:
                missing_names.append(name)
                continue
            # 申报书职责应被任务书职责覆盖；任务书更细化不判差异。
            if not _duty_is_covered(a_duty, t_duty):
                duty_mismatch.append(name)

        member_reason = "一致"
        if missing_names or duty_mismatch:
            reasons: list[str] = []
            if missing_names:
                reasons.append("缺少成员: " + "、".join(sorted(missing_names)))
            if duty_mismatch:
                reasons.append("分工未覆盖: " + "、".join(sorted(duty_mismatch)))
            member_reason = "；".join(reasons)

        _append_other(
            "项目组成员及分工",
            json.dumps([
                {
                    "name": (m.name or "").strip(),
                    "duty": (m.duty or "").strip(),
                }
                for m in a_members_raw if (m.name or "").strip()
            ], ensure_ascii=False),
            json.dumps([
                {
                    "name": (m.name or "").strip(),
                    "duty": (m.duty or "").strip(),
                }
                for m in t_members_raw if (m.name or "").strip()
            ], ensure_ascii=False),
            member_reason,
        )
        if res and res[-1].field == "项目组成员及分工" and not (missing_names or duty_mismatch):
            res[-1].risk_level = "GREEN"
            res[-1].reason = "一致"

        return res

    def _check_units_budget(self, apply_units, task_units) -> List[UnitBudgetComparison]:
        """比较单位预算明细中的合计经费。只关注单位的总合计金额，不关注子项。"""
        risks: List[UnitBudgetComparison] = []
        a_map: Dict[str, float] = {}  # unit_name -> amount
        t_map: Dict[str, float] = {}  # unit_name -> amount
        order: list[str] = []  # 保持出现顺序

        def _norm_unit_name(name: Any) -> str:
            return str(name or "").strip()

        try:
            for r in apply_units or []:
                unit_name = _norm_unit_name(getattr(r, "unit_name", ""))
                if not unit_name:
                    continue
                if unit_name not in order:
                    order.append(unit_name)
                # 累加该单位的所有金额
                a_map[unit_name] = a_map.get(unit_name, 0.0) + float(r.amount or 0.0)
            
            for r in task_units or []:
                unit_name = _norm_unit_name(getattr(r, "unit_name", ""))
                if not unit_name:
                    continue
                if unit_name not in order:
                    order.append(unit_name)
                # 累加该单位的所有金额
                t_map[unit_name] = t_map.get(unit_name, 0.0) + float(r.amount or 0.0)
        except Exception:
            pass

        # 补齐任务书新增的单位
        for unit_name in t_map.keys():
            if unit_name not in order:
                order.append(unit_name)

        # 比较每个单位的总金额
        for unit_name in order:
            a_amt = a_map.get(unit_name, 0.0)
            t_amt = t_map.get(unit_name, 0.0)
            delta = t_amt - a_amt
            
            risk = "GREEN"
            reason = "金额一致"
            if abs(delta) > 1e-6:
                risk = "RED"
                reason = "金额不一致"
            
            risks.append(UnitBudgetComparison(
                unit_name=unit_name,
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
            s1 = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", str(text1 or "").lower())
            s2 = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", str(text2 or "").lower())
            if not s1 or not s2:
                return 0.0
            if s1 in s2 or s2 in s1:
                return 0.98

            # 字符集合重叠（中文无分词场景下更稳）。
            c1 = set(s1)
            c2 = set(s2)
            char_jaccard = (len(c1 & c2) / len(c1 | c2)) if (c1 or c2) else 0.0

            # 双字片段重叠，提升对“研究生数量/培养研究生”等近义改写的识别能力。
            b1 = {s1[i:i + 2] for i in range(len(s1) - 1)} if len(s1) >= 2 else {s1}
            b2 = {s2[i:i + 2] for i in range(len(s2) - 1)} if len(s2) >= 2 else {s2}
            bigram_jaccard = (len(b1 & b2) / len(b1 | b2)) if (b1 or b2) else 0.0

            # 轻量融合：双字片段优先，字符重叠兜底。
            return float(0.7 * bigram_jaccard + 0.3 * char_jaccard)
            
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
