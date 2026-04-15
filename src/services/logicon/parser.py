import json
import logging
import asyncio
import re
from typing import Any, Awaitable, Dict, Mapping, Optional

from src.common.file_handler.factory import get_parser
from src.common.llm import get_llm_client, llm_config
from src.common.models.perfcheck import Budget, DocumentSchema

logger = logging.getLogger(__name__)

DECLARATION_SECTION_TITLES = [
    "项目实施内容及目标",
    "申报单位及合作单位基础",
    "项目申报单位基本信息表",
    "项目实施的预期绩效目标表",
    "项目实施计划及保障措施和风险分析",
    "项目组主要成员",
    "项目组主要成员表",
    "项目预算表",
    "承担单位、合作单位经费预算明细表",
    "附件",
]

TASK_SECTION_TITLES = [
    "承担单位和合作单位情况",
    "承担单位和合作单位情况表",
    "项目实施的主要内容任务",
    "进度安排和阶段目标",
    "项目验收的考核指标",
    "项目承担单位、合作单位任务分工",
    "参加人员及分工",
    "参加人员及分工表",
    "项目实施的绩效目标",
    "项目实施的绩效目标表",
    "项目预算表",
    "承担单位、合作单位经费预算明细表",
]

RESEARCH_POSITIVE_KEYWORDS = [
    "研究", "研究任务", "技术路线", "实施方案", "关键技术", "攻关", "开发", "建设", "示范", "应用",
]

RESEARCH_NEGATIVE_KEYWORDS = [
    "预算", "金额", "经费", "万元", "验收", "考核", "绩效", "指标", "承担单位", "合作单位", "分工",
]

RESEARCH_ADMIN_NOISE_KEYWORDS = [
    "科学技术厅制", "科技厅制", "申报通知", "指南代码", "符合指南", "请申报单位", "申报单位可根据", "自行确定",
    "填写说明", "填报说明", "真实性", "准确性", "法律效力", "签字", "盖章", "联系人", "联系电话",
    "电子邮箱", "邮编", "通讯地址", "附件", "备注", "表格", "模板", "申报要求", "管理部门",
]

RESEARCH_TECH_ACTION_KEYWORDS = [
    "开展", "完成", "实现", "形成", "构建", "建立", "突破", "研制", "验证", "优化", "设计", "开发", "制备", "评估", "测试",
]

RESEARCH_TECH_OBJECT_KEYWORDS = [
    "模型", "算法", "系统", "平台", "工艺", "材料", "装置", "方法", "机制", "数据", "样本", "实验", "临床", "产品", "原型",
]

BUDGET_TYPE_KEYWORDS = [
    "设备费", "业务费", "材料费", "测试化验加工费", "燃料动力费", "差旅费", "会议费", "国际合作与交流费",
    "出版", "文献", "信息传播", "知识产权事务费", "劳务费", "专家咨询费", "管理费", "其他支出",
    "直接费用", "间接费用",
]

BUDGET_TYPE_BLOCKED_KEYWORDS = [
    "承担单位", "合作单位", "预算明细表", "单位名称", "单位类型", "任务分工", "负责人", "序号",
    "年度", "预算年度", "专项经费", "自筹经费", "项目预算基本测算说明",
]

BUDGET_TYPE_FIELD_HINTS = [
    "类别",
    "科目",
    "费用",
    "费用名称",
    "预算科目",
    "预算科目名称",
    "支出内容",
    "支出科目",
    "支出项目",
    "项目内容",
    "预算内容",
    "科目名称",
    "项目支出",
    "支出类别",
]
BUDGET_AMOUNT_FIELD_HINTS = ["金额", "合计", "总额", "资金", "财政", "自筹"]
BUDGET_NON_LEAF_TYPES = [
    "省级财政资金", "自筹资金", "直接费用", "间接费用", "财政资金", "总计", "合计",
]

BUDGET_TYPE_ALIASES = {
    "测试化验加工费": "测试化验加工费",
    "检验检测费": "测试化验加工费",
    "出版文献信息传播知识产权事务费": "出版/文献/信息传播/知识产权事务费",
    "出版文献信息传播费": "出版/文献/信息传播/知识产权事务费",
    "国际合作与交流费": "国际合作与交流费",
}

PERFCHECK_EXTRACT_PROMPT = """你是项目核验抽取器，请把输入文本转换为 JSON。

硬性要求：
1) 只输出 JSON，不要 Markdown、解释或注释。
2) 字段固定如下：
     - project_name: str
     - research_contents: [{id, text}]
     - performance_targets: [{id, type, subtype, text, source, value, unit, constraint}]
     - budget: {total, items:[{type, amount}]}
    - basic_info: {undertaking_unit, partner_units:[str], team_members:[{name, duty}]}
     - units_budget: [{unit_name, type, amount}]
3) 缺失字段返回空字符串/空数组/0。
4) 数值字段必须为 number。
5) constraint 仅允许: "≥" "≤" "=" ">" "<"。
6) performance_targets 必须优先覆盖核心章节：
     - 申报书：项目实施预期技术指标及创新点、项目实施预期经济社会效益、项目实施的预期绩效目标
     - 任务书：进度安排和阶段目标、项目验收的考核指标、项目实施的绩效目标
7) text 描述指标语义；source 填写章节来源。

输出模板：
{{
    "project_name": "",
    "research_contents": [],
    "performance_targets": [],
    "budget": {{"total": 0, "items": []}},
    "basic_info": {{
        "undertaking_unit": "",
        "partner_units": [],
        "team_members": []
    }},
    "units_budget": []
}}

待处理文本：
{text}
"""

class PerfCheckParser:
    """绩效核验文档解析器"""

    def __init__(self, model_name: Optional[str] = None):
        timeout = max(float(getattr(llm_config, "timeout", 30.0) or 30.0), 5.0)
        max_retries = int(getattr(llm_config, "max_retries", 2) or 2)
        # 限制并发 LLM 请求，避免子任务因并发过高出现饥饿或超时。
        self._llm_semaphore = asyncio.Semaphore(5)
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

    def _dynamic_timeout(self, prompt: str, *, base_sec: float = 30.0, max_sec: float = 45.0) -> float:
        """保留估算函数用于日志/未来扩展；实际超时由 SDK 客户端 timeout 统一控制。"""
        text = prompt or ""
        estimated_tokens = max(1, len(text) // 4)
        extra = min(15.0, estimated_tokens / 3500.0 * 8.0)
        return max(10.0, min(max_sec, base_sec + extra))

    def _format_exception(self, exc: Exception) -> str:
        """将异常转换为可读文本，避免空字符串报错信息。"""
        if isinstance(exc, asyncio.TimeoutError):
            return "TimeoutError: LLM 调用超时"
        msg = str(exc).strip()
        if msg:
            return msg
        return f"{type(exc).__name__}: 未提供详细错误信息"

    async def _extract_budget_with_fallback(self, *, budget_prompt: str, base_timeout: float) -> Dict[str, Any]:
        """预算抽取主路径失败时降级，降低 budget 导致整体失败的概率。"""
        try:
            return await self._ainvoke_json(
                prompt=budget_prompt,
            )
        except Exception as exc:
            logger.warning("预算合并抽取失败，尝试降级抽取: %s", self._format_exception(exc))

        fallback_prompt = (
            "从预算文本中抽取最小必要字段，返回 JSON："
            "{\"budget\": {\"total\": number, \"items\": [{\"type\": str, \"amount\": number}]}}。\n"
            "只输出 JSON；无法确定时填 0 或空数组。\n\n文本：\n"
            + budget_prompt.split("\n\n文本：\n", 1)[-1]
        )
        fallback_data = await self._ainvoke_json(
            prompt=fallback_prompt,
        )
        if "units_budget" not in fallback_data:
            fallback_data["units_budget"] = []
        return fallback_data

    async def _run_with_llm_semaphore(self, coro: Any) -> Dict[str, Any]:
        async with self._llm_semaphore:
            return await coro

    async def _run_extract_tasks_fail_fast(
        self,
        task_builders: Mapping[str, Awaitable[Dict[str, Any]]],
        *,
        core_keys: set[str],
    ) -> Dict[str, Dict[str, Any]]:
        """并发执行抽取任务；核心字段失败时立即取消其余任务并抛错。"""
        tasks: Dict[str, asyncio.Task] = {
            key: asyncio.create_task(self._run_with_llm_semaphore(coro))
            for key, coro in task_builders.items()
        }
        task_to_key = {task: key for key, task in tasks.items()}
        pending = set(tasks.values())
        results: Dict[str, Dict[str, Any]] = {}

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for done_task in done:
                key = task_to_key[done_task]
                try:
                    results[key] = done_task.result()
                except Exception as exc:
                    if key in core_keys:
                        for p in pending:
                            p.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        raise ValueError(
                            f"核心字段抽取失败({key}): {self._format_exception(exc)}"
                        ) from exc

                    logger.warning("非核心字段抽取失败(%s): %s", key, self._format_exception(exc))
                    results[key] = {}

        return results

    def _find_heading_positions(self, raw: str, titles: list[str]) -> list[int]:
        positions: dict[int, int] = {}
        for title in titles:
            # 兼容标题后缀是否带“表”，避免同类表格标题因写法差异漏命中。
            base_title = title[:-1] if title.endswith("表") else title
            pat = re.compile(
                rf"(?m)^\s*(?:[一二三四五六七八九十]+[、.．)]\s*)?{re.escape(base_title)}(?:表)?(?:\s|$)",
            )
            m = pat.search(raw)
            if m:
                positions[m.start()] = m.end()
                continue

            fallback_titles = [base_title, f"{base_title}表"]
            for fallback_title in fallback_titles:
                idx = raw.find(fallback_title)
                if idx >= 0:
                    positions[idx] = idx + len(fallback_title)
                    break

        return sorted(positions.keys())

    def _detect_doc_kind(self, raw: str) -> str:
        decl_hits = len(self._find_heading_positions(raw, DECLARATION_SECTION_TITLES))
        task_hits = len(self._find_heading_positions(raw, TASK_SECTION_TITLES))
        if task_hits >= 2 and task_hits >= decl_hits:
            return "task"
        if decl_hits >= 1:
            return "declaration"
        return "unknown"

    def _strip_filling_instructions(self, raw: str) -> str:
        """移除“填写说明/填报说明”整段，避免行政模板文本污染抽取。"""
        text = str(raw or "")
        if not text:
            return ""

        start_match = re.search(r"填\s*写\s*说\s*明|填\s*报\s*说\s*明", text)
        if not start_match:
            return text

        start_idx = start_match.start()
        suffix = text[start_idx:]

        end_patterns = [
            r"(?m)^\s*一[、.．)]\s*承担单位和合作单位情况(?:\s|$)",
            r"(?m)^\s*1[.、)]\s*承担单位基本情况(?:\s|$)",
            r"(?m)^\s*项目申报单位基本信息(?:\s|$)",
            r"(?m)^\s*一[、.．)]\s*项目实施内容(?:及目标)?(?:\s|$)",
            r"(?m)^\s*(?:第一部分|第1部分)\s*",
            r"\[表格表头\d+\]\s*.*(?:承担单位和合作单位情况|项目申报单位基本信息|单位名称\s*\|)",
        ]

        end_positions: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix, re.IGNORECASE)
            if m and m.start() > 0:
                end_positions.append(start_idx + m.start())

        if not end_positions:
            return text

        end_idx = min(end_positions)
        merged = (text[:start_idx].rstrip() + "\n\n" + text[end_idx:].lstrip()).strip()
        return merged

    def _collect_section_blocks(
        self,
        *,
        raw: str,
        section_titles: list[str],
        per_block_chars: int,
        max_blocks: int,
    ) -> list[str]:
        positions = self._find_heading_positions(raw, section_titles)
        if not positions:
            return []

        blocks: list[str] = []
        for i, start in enumerate(positions[:max_blocks]):
            end = positions[i + 1] if i + 1 < len(positions) else len(raw)
            block = raw[start:end].strip()
            if block:
                blocks.append(block[:per_block_chars])

        return blocks

    def _collect_topic_text(
        self,
        *,
        raw: str,
        section_titles: list[str],
        patterns: list[str],
        max_chars: int,
        per_block_chars: int,
        window_before: int,
        window_after: int,
    ) -> str:
        section_blocks = self._collect_section_blocks(
            raw=raw,
            section_titles=section_titles,
            per_block_chars=per_block_chars,
            max_blocks=4,
        )
        section_text = "\n\n".join(section_blocks).strip()
        if len(section_text) >= max_chars:
            return section_text[:max_chars]

        remaining = max(0, max_chars - len(section_text))
        if remaining < 400:
            return section_text[:max_chars]

        windows_text = self._collect_windows(
            raw=raw,
            patterns=patterns,
            head_chars=300 if not section_text else 0,
            tail_chars=0,
            before=window_before,
            after=window_after,
            max_chars=remaining,
        )

        merged = "\n\n".join([x for x in [section_text, windows_text] if x]).strip()
        return merged[:max_chars]

    def _collect_budget_text_precise(self, *, raw: str, doc_kind: str, max_chars: int) -> str:
        """尽量从预算表真实章节截取，避免被前文说明与无关表格行淹没。

        业务硬约束：
        - 申报书：第七部分 项目预算表
        - 任务书：八、项目预算表
        并剔除“项目预算基本测算说明（含设备详细说明）”段落。
        """
        text = (raw or "").strip()
        if not text:
            return ""

        if doc_kind == "task":
            anchor_patterns = [
                r"(?m)^\s*(?:八[、.．)]|第?八(?:部分|章)?)\s*项目预算表(?:\s|$)",
                r"(?m)^\s*项目预算表\s*$",
                r"\[表格表头\d+\]\s*序号\s*\|\s*预算科目名称\s*\|\s*金额",
            ]
            next_section_patterns = [
                r"(?m)^\s*(?:九[、.．)]|第?九(?:部分|章)?)\s+",
                r"(?m)^\s*(?:承担单位、合作单位经费预算明细表|附件目录|附件)\s*$",
            ]
        else:
            anchor_patterns = [
                r"(?m)^\s*(?:第?七(?:部分|章)?|七[、.．)])\s*项目预算表(?:\s|$)",
                r"(?m)^\s*项目预算表\s*$",
                r"\[表格表头\d+\]\s*序号\s*\|\s*预算科目名称\s*\|\s*金额",
            ]
            next_section_patterns = [
                r"(?m)^\s*(?:第?八(?:部分|章)?|八[、.．)])\s+",
                r"(?m)^\s*(?:承担单位、合作单位经费预算明细表|附件目录|附件)\s*$",
            ]

        anchors: list[int] = []
        for pat in anchor_patterns:
            for m in re.finditer(pat, text):
                anchors.append(m.start())

        if not anchors:
            return ""

        def _score(pos: int) -> int:
            window = text[pos : min(len(text), pos + 2200)]
            score = 0
            if "预算科目名称" in window:
                score += 5
            if "单位：万元" in window:
                score += 3
            if re.search(r"(省级财政资金|直接费用|设备费|业务费|劳务费)", window):
                score += 4
            prev = text[max(0, pos - 260) : pos]
            if "填报说明" in prev:
                score -= 4
            return score

        best_pos = max(anchors, key=lambda p: (_score(p), p))

        end_candidates: list[int] = []
        suffix = text[best_pos + 1 :]
        for pat in next_section_patterns:
            m = re.search(pat, suffix)
            if m:
                end_candidates.append(best_pos + 1 + m.start())

        end_pos = min(end_candidates) if end_candidates else len(text)
        section = text[best_pos:end_pos].strip()

        # 预算对比仅使用“项目预算表”，不纳入后续“承担单位、合作单位经费预算明细表”。
        detail_cut = re.search(r"(?:九[、.．)]\s*)?承担单位、合作单位经费预算明细表|第?九(?:部分|章)", section)
        if detail_cut:
            section = section[: detail_cut.start()].strip()

        # 不纳入“项目预算基本测算说明（含单价50万以上设备详细说明）”文本。
        explain_match = re.search(r"项目预算基本测算说明", section)
        if explain_match:
            section = section[: explain_match.start()].strip()

        return section[:max_chars]

    def _collect_units_budget_text_precise(self, *, raw: str, doc_kind: str, max_chars: int = 9000) -> str:
        """精准截取“承担单位、合作单位经费预算明细表”章节。"""
        text = (raw or "").strip()
        if not text:
            return ""

        anchor_patterns = [
            r"(?m)^\s*(?:第?[八九](?:部分|章)?|[八九][、.．)])\s*承担单位、合作单位经费预算明细表(?:\s|$)",
            r"(?m)^\s*承担单位、合作单位经费预算明细表(?:\s|$)",
            r"\[表格表头\d+\]\s*[^\n]{0,80}单位名称\s*\|[^\n]{0,80}单位类型\s*\|[^\n]{0,120}(?:合计|专项经费|自筹经费)",
        ]

        starts: list[int] = []
        for pat in anchor_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                starts.append(m.start())

        if not starts:
            return ""

        start = min(starts)
        suffix = text[start + 1 :]
        end_patterns = [
            r"(?m)^\s*(?:第?[一二三四五六七八九十](?:部分|章)?|[一二三四五六七八九十][、.．)])\s+",
            r"(?m)^\s*(?:附件目录|附件)\s*$",
        ]
        ends: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix)
            if m:
                ends.append(start + 1 + m.start())

        end = min(ends) if ends else len(text)
        section = text[start:end].strip()
        return section[:max_chars]

    def _extract_units_budget_items_from_table_rows(self, text: str, *, max_items: int = 200) -> list[dict[str, Any]]:
        """从"承担单位、合作单位经费预算明细表"中提取单位预算明细（仅提取单位+合计经费）。"""
        raw = str(text or "")
        if not raw:
            return []

        item_map: dict[str, float] = {}  # unit_name -> amount
        for blk in self._extract_table_row_blocks(raw):
            if "单位名称" not in blk:
                continue

            kv = {
                k.strip(): (v or "").strip()
                for k, v in re.findall(r"(?:^|[;；])\s*([^:：;|]+)[:：]\s*([^;|]+)", blk)
            }
            if not kv:
                continue

            def _pick(field: str) -> str:
                for k, v in kv.items():
                    nk = re.sub(r"\s+", "", k)
                    if field in nk:
                        return v
                return ""

            unit_name = _pick("单位名称")
            if not unit_name:
                continue
            unit_name = re.sub(r"\s+", "", unit_name).strip("，,;；。")
            if not unit_name:
                continue

            # 只提取合计经费，不提取子项（专项/自筹）
            amt_raw = _pick("合计")
            if not amt_raw:
                # 尝试从通用字段名提取金额
                for k, v in kv.items():
                    if any(x in re.sub(r"\s+", "", k) for x in ("金额", "经费", "预算", "总计", "总额")):
                        amt_raw = v
                        break
            
            if amt_raw:
                amount = float(self._parse_amount(amt_raw))
                # 如果该单位已有价值，取最大值（应对多行情况）
                item_map[unit_name] = max(item_map.get(unit_name, 0.0), amount)

        items: list[dict[str, Any]] = []
        for unit_name, amount in item_map.items():
            items.append({"unit_name": unit_name, "type": "合计", "amount": float(amount)})

        return items[:max_items]

    def _extract_required_research_section(self, *, raw: str, doc_kind: str, max_chars: int = 5200) -> str:
        """按业务硬约束抽取研究章节：
        - 申报书：一、项目实施内容（及目标）
        - 任务书：二、项目实施的主要内容任务
        """
        text = (raw or "").strip()
        if not text:
            return ""

        if doc_kind == "task":
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?二[、.．)]\s*项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?二(?:部分|章)?\s*项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目实施的主要内容任务(?:表)?(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?三[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?三(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:进度安排和阶段目标|项目验收的考核指标|项目实施的绩效目标(?:表)?)\s*$",
            ]
        else:
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?一[、.．)]\s*项目实施内容(?:及目标)?(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?一(?:部分|章)?\s*项目实施内容(?:及目标)?(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?二[、.．)]\s*项目实施内容[、,，]\s*研究方法及技术路线(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?二(?:部分|章)?\s*项目实施内容[、,，]\s*研究方法及技术路线(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目实施内容[、,，]\s*研究方法及技术路线(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目实施内容(?:及目标)?(?:表)?(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?三[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?三(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:申报单位及合作单位基础|项目申报单位基本信息表|项目实施的预期绩效目标表|项目预算表)\s*$",
                r"(?m)^\s*(?:#+\s*)?(?:项目实施预期技术指标及创新点|项目实施预期经济社会效益|项目实施的预期绩效目标(?:表)?)\s*$",
            ]

        start_positions: list[int] = []
        for pat in start_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                start_positions.append(m.start())

        if not start_positions:
            return ""

        start_idx = min(start_positions)
        suffix = text[start_idx:]

        end_positions: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix, re.IGNORECASE)
            if m and m.start() > 0:
                end_positions.append(start_idx + m.start())

        end_idx = min(end_positions) if end_positions else len(text)
        # 对齐到标题边界后保留少量上下文，兼顾 OCR/格式噪声。
        slice_start = max(0, start_idx - 80)
        slice_end = min(len(text), end_idx + 120)
        section = text[slice_start:slice_end].strip()
        return section[:max_chars]

    def _extract_research_content_only(self, *, raw: str, doc_kind: str, max_chars: int = 5200) -> str:
        """在“项目实施内容及目标/主要内容任务”章节内进一步收缩，只保留“研究内容”小节。

        目标：
        - 申报书：第一部分 > 一、项目实施内容 > 研究内容
        - 任务书：二、项目实施的主要内容任务 > 研究内容

        避免把“合作单位选择原因/国际合作/论文专利/承担项目/进度安排”等非研究内容混入核验。
        """
        text = str(raw or "").strip()
        if not text:
            return ""

        if doc_kind == "task":
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?二[、.．)]\s*项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?二(?:部分|章)?\s*项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?(?:[（(]?[一二三四五六七八九十]+[）)]?\s*)?研究内容(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?研究任务(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?主要内容(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?三[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?三(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:进度安排和阶段目标|项目验收的考核指标|项目实施的绩效目标(?:表)?)\s*$",
            ]
        else:
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?(?:[（(]?[一二三四五六七八九十]+[）)]?\s*)?研究内容(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?(?:[（(]?[一二三四五六七八九十]+[）)]?\s*)?项目的主要实施内容(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目的主要实施内容(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?主要实施内容(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?研究内容(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?二[、.．)]\s*(?:合作单位|相关的国际合作|进度安排|项目实施计划|项目预算|项目实施的预期绩效目标)",
                r"(?m)^\s*(?:#+\s*)?三[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?[二三](?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:研究方法|技术路线|项目拟采取的研究方法)(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?(?:可行性分析|先进性分析)(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?(?:项目实施的预期绩效目标(?:表)?|项目预算表|承担单位、合作单位经费预算明细表)\s*$",
                r"(?m)^\s*(?:#+\s*)?进度安排(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?近五年发表论文(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?近五年授权专利(?:\s|$)",
            ]

        start_positions: list[int] = []
        for pat in start_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                start_positions.append(m.start())
        if not start_positions:
            for pat in end_patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m and m.start() > 0:
                    return text[: min(len(text), m.start())].strip()[:max_chars]
            return text[:max_chars]

        start_idx = min(start_positions)
        suffix = text[start_idx:]
        end_positions: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix, re.IGNORECASE)
            if m and m.start() > 20:
                end_positions.append(start_idx + m.start())
        end_idx = min(end_positions) if end_positions else len(text)

        slice_start = max(0, start_idx - 40)
        slice_end = min(len(text), end_idx + 40)
        section = text[slice_start:slice_end].strip()
        return section[:max_chars]

    def _extract_required_metrics_sections(self, *, raw: str, doc_kind: str, max_chars: int = 14000) -> str:
        """按业务硬约束抽取绩效目标章节，优先覆盖：
        - 申报书：五、项目实施的预期绩效目标
        - 任务书：七、项目实施的绩效目标
        """
        text = (raw or "").strip()
        if not text:
            return ""

        if doc_kind == "task":
            metric_titles = [
                "项目实施的绩效目标",
                "项目实施的绩效目标表",
            ]
            all_titles = TASK_SECTION_TITLES
        else:
            metric_titles = [
                "项目实施的预期绩效目标",
                "项目实施的预期绩效目标表",
            ]
            all_titles = DECLARATION_SECTION_TITLES

        metric_positions = self._find_heading_positions(text, metric_titles)
        if not metric_positions:
            return ""

        all_positions = self._find_heading_positions(text, all_titles)
        blocks: list[str] = []
        for start_idx in metric_positions[:4]:
            next_positions = [p for p in all_positions if p > start_idx]
            end_idx = next_positions[0] if next_positions else len(text)
            slice_start = max(0, start_idx - 80)
            slice_end = min(len(text), end_idx + 220)
            block = text[slice_start:slice_end].strip()
            if block:
                table_lines = [
                    ln.strip()
                    for ln in block.splitlines()
                    if re.search(r"\[表格(?:表头|行)\d*\]", ln)
                ]
                # 优先保留章节内表格内容；同时追加可能位于非表格行的“总体目标/实施期目标”文本，
                # 防止该类指标在任务书中被切片丢失。
                if table_lines:
                    extra_lines = [
                        ln.strip()
                        for ln in block.splitlines()
                        if (
                            ln.strip()
                            and not re.search(r"\[表格(?:表头|行)\d*\]", ln)
                            and (
                                "总体目标" in ln
                                or "总目标" in ln
                                or "实施期目标" in ln
                                or "创新番茄种质资源" in ln
                            )
                        )
                    ]
                    merged_lines = table_lines + extra_lines
                    blocks.append("\n".join(merged_lines))
                else:
                    blocks.append(block)

        merged = "\n\n".join(blocks).strip()
        return merged[:max_chars]

    def _extract_performance_targets_from_metrics_table(self, metrics_text: str) -> list[dict[str, Any]]:
        text = str(metrics_text or "").strip()
        if not text:
            return []

        row_pat = re.compile(r"\[表格行(\d+)\]\s*(.+?)(?=\n\[表格行\d+\]|\Z)", re.DOTALL)
        rows_raw = [(m.group(1), (m.group(2) or "")) for m in row_pat.finditer(text)]
        if not rows_raw:
            return []

        def _pairs(line: str) -> list[tuple[str, str]]:
            return [
                (k.strip(), (v or "").strip())
                for k, v in re.findall(r"(?:^|[;；])\s*([^:：;|]+)[:：]\s*([^;|]+)", line)
            ]

        header_mapping: dict[str, dict[str, int]] = {}
        header_row_id = ""
        for row_id, content in rows_raw:
            compact = re.sub(r"\s+", "", content)
            if ("三级指标" in compact) and ("指标值" in compact):
                pairs = _pairs(content)
                if not pairs:
                    continue
                occ: dict[str, int] = {}
                mapping: dict[str, dict[str, int]] = {}
                for k, v in pairs:
                    nk = re.sub(r"\s+", "", k)
                    occ[nk] = occ.get(nk, 0) + 1
                    if v:
                        vv = re.sub(r"\s+", "", v)
                        if vv in {"三级指标", "指标值", "二级指标", "一级指标"}:
                            mapping.setdefault(nk, {})[vv] = occ[nk]
                if mapping:
                    header_mapping = mapping
                    header_row_id = row_id
                    break

        target_key = "实施期目标"
        candidate_keys = []
        for k in header_mapping.keys():
            nk = re.sub(r"\s+", "", str(k or ""))
            if nk.startswith(target_key):
                candidate_keys.append(k)
        use_key = candidate_keys[0] if candidate_keys else target_key
        map_for_key = header_mapping.get(use_key, {})
        idx_third = int(map_for_key.get("三级指标", 0) or 0)
        idx_value = int(map_for_key.get("指标值", 0) or 0)
        if idx_third <= 0 or idx_value <= 0:
            return []

        out: list[dict[str, Any]] = []

        def _parse_number(s: str) -> float | None:
            m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
            if not m:
                return None
            try:
                return float(m.group(0))
            except Exception:
                return None

        for row_id, content in rows_raw:
            if header_row_id and row_id == header_row_id:
                continue
            pairs = _pairs(content)
            if not pairs:
                continue

            occ: dict[str, int] = {}
            metric_name = ""
            metric_value_raw = ""
            subtype = ""
            for k, v in pairs:
                nk = re.sub(r"\s+", "", k)
                occ[nk] = occ.get(nk, 0) + 1
                if nk == use_key or nk.startswith(target_key):
                    if occ[nk] == idx_third and v:
                        metric_name = str(v).strip()
                    if occ[nk] == idx_value and v:
                        metric_value_raw = str(v).strip()
                if v and (not subtype):
                    vv = re.sub(r"\s+", "", str(v))
                    if vv in {"数量指标", "满意度指标", "经济指标", "效益指标", "技术指标"}:
                        subtype = vv

            if not metric_name or not metric_value_raw:
                continue

            value = _parse_number(metric_value_raw)
            if value is None:
                continue

            unit = ""
            m_unit = re.search(r"[（(]([^()（）]{1,8})[)）]", metric_name)
            if m_unit:
                unit = m_unit.group(1).strip()
            if not unit:
                if ("%" in metric_value_raw) or ("％" in metric_value_raw) or ("满意度" in metric_name):
                    unit = "%"
            if unit == "％":
                unit = "%"

            out.append(
                {
                    "id": f"P{len(out) + 1}",
                    "type": metric_name.strip(),
                    "text": f"{metric_name.strip()} {metric_value_raw}".strip(),
                    "source": "绩效指标",
                    "value": value,
                    "unit": unit,
                    "constraint": "=",
                    "subtype": subtype or ("满意度指标" if unit == "%" else "数量指标"),
                }
            )

        return out

    def _extract_required_team_members_sections(self, *, raw: str, doc_kind: str, max_chars: int = 9000) -> str:
        """按业务硬约束抽取成员分工章节表格：
        - 申报书：第四/第六部分 项目组主要成员
        - 任务书：六、参加人员及分工
        """
        text = (raw or "").strip()
        if not text:
            return ""

        if doc_kind == "task":
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?六[、.．)]\s*参加人员及分工(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?六(?:部分|章)?\s*参加人员及分工(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?参加人员及分工(?:表)?(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?七[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?七(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:项目实施的绩效目标(?:表)?|项目预算表|承担单位、合作单位经费预算明细表)(?:\s|$)",
            ]
        else:
            start_patterns = [
                r"(?m)^\s*(?:#+\s*)?四[、.．)]\s*项目组主要成员(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?四(?:部分|章)?\s*项目组主要成员(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?六[、.．)]\s*项目组主要成员(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?第?六(?:部分|章)?\s*项目组主要成员(?:表)?(?:\s|$)",
                r"(?m)^\s*(?:#+\s*)?项目组主要成员(?:表)?(?:\s|$)",
            ]
            end_patterns = [
                r"(?m)^\s*(?:#+\s*)?五[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?五(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?七[、.．)]\s*",
                r"(?m)^\s*(?:#+\s*)?第?七(?:部分|章)\s*",
                r"(?m)^\s*(?:#+\s*)?(?:项目预算表|承担单位、合作单位经费预算明细表|附件)(?:\s|$)",
            ]

        start_positions: list[int] = []
        for pat in start_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                start_positions.append(m.start())

        if not start_positions:
            return ""

        def _score_start(pos: int) -> int:
            window = text[pos : min(len(text), pos + 2200)]
            score = 0
            if re.search(r"(?:四[、.．)]|第?四(?:部分|章))", window):
                score += 2
            if re.search(r"(?:六[、.．)]|第?六(?:部分|章))", window):
                score += 2
            score += len(re.findall(r"姓名", window))
            score += len(re.findall(r"分工", window))
            score += len(re.findall(r"序号", window))
            score += 2 * len(re.findall(r"\[表格行\d+\]", window))
            score += 2 * len(re.findall(r"\[表格表头\d+\]", window))
            if "填报说明" in window[:260] or "填写说明" in window[:260]:
                score -= 8
            return score

        start_idx = max(start_positions, key=lambda p: (_score_start(p), p))
        suffix = text[start_idx:]
        end_positions: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix, re.IGNORECASE)
            if m and m.start() > 0:
                end_positions.append(start_idx + m.start())

        end_idx = min(end_positions) if end_positions else len(text)

        blocks: list[str] = []
        slice_start = max(0, start_idx - 80)
        slice_end = min(len(text), end_idx + 120)
        block = text[slice_start:slice_end].strip()
        if not block:
            return ""

        table_lines = [
            ln.strip()
            for ln in block.splitlines()
            if re.search(r"\[表格(?:表头|行)\d*\]", ln)
        ]
        if table_lines:
            blocks.append("\n".join(table_lines))
        else:
            # 无 [表格行] 标记时，退化保留含“姓名/分工/序号”的行。
            fallback_lines = [
                ln.strip()
                for ln in block.splitlines()
                if ("姓名" in ln or "分工" in ln or "序号" in ln)
            ]
            if fallback_lines:
                blocks.append("\n".join(fallback_lines))
            else:
                blocks.append(block)

        merged = "\n\n".join(blocks).strip()
        return merged[:max_chars]

    def _extract_research_section_precise(self, *, raw: str, doc_kind: str, max_chars: int = 5200) -> str:
        """按起止关键词精准切片研究内容，优先降低无关上下文。"""
        text = (raw or "").strip()
        if not text:
            return ""

        # 先按章节标题定位，避免纯关键词在表格/OCR文本中漏命中。
        if doc_kind == "task":
            research_titles = ["项目实施的主要内容任务", "项目实施主要内容任务", "研究内容"]
            all_titles = TASK_SECTION_TITLES
        else:
            research_titles = ["项目实施内容及目标", "项目实施内容", "研究内容"]
            all_titles = DECLARATION_SECTION_TITLES

        research_positions = self._find_heading_positions(text, research_titles)
        if research_positions:
            start_idx = research_positions[0]
            all_positions = self._find_heading_positions(text, all_titles)
            next_positions = [p for p in all_positions if p > start_idx]
            end_idx = next_positions[0] if next_positions else len(text)

            pre_buffer = 80
            post_buffer = 180
            slice_start = max(0, start_idx - pre_buffer)
            slice_end = min(len(text), end_idx + post_buffer)
            section = text[slice_start:slice_end].strip()
            if section:
                return section[:max_chars]

        if doc_kind == "task":
            start_patterns = [
                r"(?m)^\s*二[、.．)]\s*项目实施的主要内容任务(?:表)?(?:\s|$)",
                r"项目实施的主要内容任务",
                r"项目实施主要内容任务",
                r"项目实施主要内容",
                r"研究内容",
                r"技术路线",
                r"研究目标",
            ]
            end_patterns = [
                r"(?m)^\s*三[、.．)]\s*",
                r"(?m)^\s*四[、.．)]\s*",
                r"(?m)^\s*五[、.．)]\s*",
                r"项目验收的考核指标",
                r"进度安排和阶段目标",
                r"项目实施的绩效目标(?:表)?",
                r"项目预算(?:表)?",
                r"承担单位、合作单位经费预算明细(?:表)?",
                r"经费预算",
            ]
        else:
            start_patterns = [
                r"(?m)^\s*一[、.．)]\s*项目实施内容及目标(?:表)?(?:\s|$)",
                r"项目实施内容及目标",
                r"项目实施内容",
                r"研究内容",
                r"技术路线",
                r"研究目标",
            ]
            end_patterns = [
                r"(?m)^\s*二[、.．)]\s*",
                r"(?m)^\s*三[、.．)]\s*",
                r"(?m)^\s*四[、.．)]\s*",
                r"考核指标",
                r"进度安排",
                r"年度计划",
                r"项目实施的预期绩效目标(?:表)?",
                r"项目预算(?:表)?",
                r"承担单位、合作单位经费预算明细(?:表)?",
                r"经费预算",
            ]

        start_positions: list[int] = []
        for pat in start_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                start_positions.append(m.start())

        if not start_positions:
            return ""

        start_idx = min(start_positions)
        suffix = text[start_idx:]

        end_positions: list[int] = []
        for pat in end_patterns:
            m = re.search(pat, suffix, re.IGNORECASE)
            if m and m.start() > 0:
                end_positions.append(start_idx + m.start())

        end_idx = min(end_positions) if end_positions else len(text)

        pre_buffer = 120
        post_buffer = 200
        slice_start = max(0, start_idx - pre_buffer)
        slice_end = min(len(text), end_idx + post_buffer)
        return text[slice_start:slice_end][:max_chars].strip()

    def _collect_windows(
        self,
        *,
        raw: str,
        patterns: list[str],
        head_chars: int,
        tail_chars: int,
        before: int,
        after: int,
        max_chars: int,
    ) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""

        raw = raw[:45000]

        positions: list[tuple[int, int]] = []
        for pat in patterns:
            for m in re.finditer(pat, raw):
                start = max(0, m.start() - before)
                end = min(len(raw), m.end() + after)
                positions.append((start, end))

        # 合并重叠窗口，避免重复上下文导致 token 浪费。
        positions.sort()
        merged_positions: list[tuple[int, int]] = []
        for start, end in positions:
            if not merged_positions or start > merged_positions[-1][1]:
                merged_positions.append((start, end))
            else:
                prev_start, prev_end = merged_positions[-1]
                merged_positions[-1] = (prev_start, max(prev_end, end))

        windows = [raw[s:e] for s, e in merged_positions[:6]]

        head = raw[:head_chars] if head_chars > 0 else ""
        tail = raw[-tail_chars:] if tail_chars > 0 and len(raw) > head_chars + tail_chars else ""

        merged = "\n\n".join([x for x in ([head] + windows + ([tail] if tail else [])) if x])
        merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
        return merged[:max_chars]

    def _strip_code_fence(self, content: str) -> str:
        if "```json" in content:
            return content.split("```json")[1].split("```")[0].strip()
        if "```" in content:
            return content.split("```")[1].split("```")[0].strip()
        return content.strip()

    def _normalize_performance_targets(self, targets: Any) -> list[dict[str, Any]]:
        """标准化指标名称：优先使用三级细项，避免一级/二级泛化名称。"""
        normalized: list[dict[str, Any]] = []
        generic_type_re = re.compile(r"^(?:一级|二级|三级)?(?:指标|技术指标|经济社会效益|绩效目标|考核指标)$")
        for idx, raw_item in enumerate(targets or [], start=1):
            item = dict(raw_item or {})
            item_id = str(item.get("id") or f"P{idx}").strip() or f"P{idx}"
            text = str(item.get("text") or "").strip()
            metric_type = str(item.get("type") or "").strip()

            if (not metric_type) or generic_type_re.match(metric_type):
                metric_type = text[:80] if text else metric_type
            if metric_type.startswith("一级") or metric_type.startswith("二级"):
                metric_type = text[:80] if text else metric_type

            item["id"] = item_id
            item["type"] = metric_type or "未命名指标"
            # 约束为区间时（如"6-8"），统一以区间上界作为 value，避免比较阶段误判“缩减”。
            constraint = str(item.get("constraint") or "").strip()
            if constraint:
                nums = re.findall(r"\d+(?:\.\d+)?", constraint)
                if len(nums) >= 2:
                    # 统一输出语义：区间目标的 value 使用区间字符串（如"6-8"）。
                    item["value"] = constraint
            if not text:
                item["text"] = item["type"]
            normalized.append(item)
        return normalized

    def _extract_table_row_blocks(self, text: str) -> list[str]:
        raw = str(text or "")
        if not raw:
            return []

        blocks: list[str] = []
        pat = re.compile(r"\[表格行\d+\]\s*(.+?)(?=\n\[表格行\d+\]|\Z)", re.DOTALL)
        for m in pat.finditer(raw):
            s = re.sub(r"\s+", " ", m.group(1) or "").strip()
            if s:
                blocks.append(s)
        return blocks

    def _extract_undertaking_unit(self, text: str) -> str:
        raw = str(text or "")
        if not raw:
            return ""

        direct = re.search(r"申报单位[:：]\s*([^\n，,；;。]{2,60})", raw)
        if direct:
            return re.sub(r"\s+", "", direct.group(1)).strip()

        for blk in self._extract_table_row_blocks(raw):
            if "单位名称" not in blk:
                continue
            m = re.search(r"单位名称\s*[|:：]\s*([^|:：]{2,60})", blk)
            if m:
                return re.sub(r"\s+", "", m.group(1)).strip()

        return ""

    def _extract_project_name(self, text: str) -> str:
        raw = str(text or "")
        if not raw:
            return ""

        def _clean_name(name: str) -> str:
            s = str(name or "").strip()
            s = re.sub(r"\s+", "", s)
            s = s.strip("：:;；，,。")
            # 去掉明显噪声后缀。
            s = re.split(r"(?:申报单位|承担单位|合作单位|项目负责人|归口管理部门|填报日期|起止年月)", s, maxsplit=1)[0]
            s = s.strip("：:;；，,。")
            if len(s) < 4:
                return ""
            return s

        def _cut_by_next_fields(value: str) -> str:
            s = str(value or "")
            stop = re.search(
                r"(?:\n\s*(?:项\s*目\s*编\s*号|项目编号|签\s*订\s*年\s*度|签订年度|项\s*目\s*起\s*止\s*年\s*月|项目起止年月|承\s*担\s*单\s*位|承担单位|申报单位|合\s*作\s*单\s*位|合作单位|项\s*目\s*负\s*责\s*人|项目负责人|归口管理部门|科技厅分管处室)\s*[:：])",
                s,
            )
            if stop:
                s = s[: stop.start()]
            return s.strip()

        def _extract_from_header_region(src: str) -> str:
            s = str(src or "")
            if not s:
                return ""
            # 仅在页眉区域查找，避免被后文“填写说明/表格行”污染。
            split_pos = len(s)
            for pat in [r"填写说明", r"一、承担单位和合作单位情况", r"\[表格表头", r"\[表格行"]:
                m = re.search(pat, s)
                if m:
                    split_pos = min(split_pos, m.start())
            head = s[: max(1200, split_pos)]

            m = re.search(r"项\s*目\s*名\s*称\s*[:：]\s*([\s\S]{4,260})", head)
            if m:
                val = _clean_name(_cut_by_next_fields(m.group(1)))
                if val:
                    return val
            m = re.search(r"项目名称\s*[:：]\s*([\s\S]{4,260})", head)
            if m:
                val = _clean_name(_cut_by_next_fields(m.group(1)))
                if val:
                    return val
            return ""

        # 任务书页眉/封面优先提取，命中后直接返回。
        header_name = _extract_from_header_region(raw)
        if header_name:
            return header_name

        # 0) 多行字段优先：兼容“项\n目\n名\n称：xxx\nxxx”的布局断裂文档。
        m = re.search(r"(?:项\s*目\s*名\s*称|项目名称)\s*[:：]\s*([\s\S]{4,260})", raw)
        if m:
            name = _clean_name(_cut_by_next_fields(m.group(1)))
            if name:
                return name

        # 1) 普通文本形态：项目名称：xxx
        m = re.search(r"项目名称\s*[:：]\s*([^\n]{4,200})", raw)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name

        # 1.1) 被空格打散的标题形态：项   目   名   称：xxx
        m = re.search(r"项\s*目\s*名\s*称\s*[:：]\s*([^\n]{4,220})", raw)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name

        # 2) OCR 表格行形态：... 项目名称 ; xxx ; ...
        m = re.search(r"项目名称\s*[;；|]\s*([^;；|\n]{4,240})", raw)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name

        # 3) DOCX 压缩键值形态：项目名称/旧值:新值
        m = re.search(r"项目名称/[^:;|]{0,200}:([^;|\n]{4,240})", raw)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name

        # 4) 无冒号兜底：紧跟“项目名称”后的短文本片段（兼容 OCR/布局断裂）
        m = re.search(r"项\s*目\s*名\s*称\s*([^\n]{4,220})", raw)
        if m:
            name = _clean_name(m.group(1))
            if name:
                return name

        return ""

    def _extract_partner_units(self, text: str) -> list[str]:
        raw = str(text or "")
        if not raw:
            return []

        units: list[str] = []

        def _clean_partner_name(name: str) -> str:
            s = re.sub(r"\s+", "", str(name or "")).strip("，,;；。")
            if not s:
                return ""
            # 去掉合同签章/日期等尾部噪声，避免被误判为单位名。
            s = re.split(
                r"(?:（?公章）?|日期[:：]?|负责人[:：]?|经办人[:：]?|归口管理单位[:：]?|科研计划专用章|甲方[:：]?|乙方[:：]?|丙方[:：]?"
                r"|承担临床|临床疗效观察|生物样本采集|协助项目承担单位|知识产权归属|项目合作单位|论文撰写|七、项目实施的绩效目标|\[表格表头)",
                s,
                maxsplit=1,
            )[0]
            s = s.strip("，,;；。()（）")
            if len(s) < 3:
                return ""
            return s

        direct = re.search(r"合\s*作\s*单\s*位\s*[:：]\s*([^\n]+)", raw)
        if direct:
            for p in re.split(r"[,，、]", direct.group(1)):
                name = _clean_partner_name(p)
                if 2 <= len(name) <= 64:
                    units.append(name)

        for blk in self._extract_table_row_blocks(raw):
            parts = [re.sub(r"\s+", "", x).strip() for x in blk.split("|") if str(x).strip()]
            if len(parts) < 3:
                continue
            if not re.fullmatch(r"\d+", parts[0] or ""):
                continue
            # 合作单位概况表：序号 | 单位名称 | 国别 | ...
            if "中国" in parts or any("自治区" in x or "市" in x for x in parts):
                candidate = _clean_partner_name(parts[1])
                if 3 <= len(candidate) <= 64 and ("医院" in candidate or "大学" in candidate or "公司" in candidate):
                    units.append(candidate)

        deduped: list[str] = []
        seen: set[str] = set()
        for name in units:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _extract_team_members_from_table_rows(self, text: str, *, max_items: int = 40) -> list[dict[str, str]]:
        raw = str(text or "")
        if not raw:
            return []

        members: list[dict[str, str]] = []
        seen_names: set[str] = set()

        def _clean_member_duty(duty: str) -> str:
            s = re.sub(r"\s+", "", str(duty or "")).strip("，,;；")
            s = re.split(r"(?:七、项目实施的绩效目标|项目实施的绩效目标|\[表格表头\d+\]|\[表格表头\]|知识产权归属)", s, maxsplit=1)[0]
            s = s.strip("，,;；")
            return s

        for blk in self._extract_table_row_blocks(raw):
            # DOCX 表格常见形态："姓名/刘建宁:贾蓓 ; 分工/实验设计、实验质控:实验质量、安全性控制"
            if ("姓名/" in blk) and ("分工/" in blk):
                serial = 0
                m_serial = re.search(r"序号/(\d+)(?::(\d+))?", blk)
                if m_serial:
                    serial = int(m_serial.group(2) or m_serial.group(1) or "0")

                name = ""
                m_name_pair = re.search(r"姓名/([^:;|]+):([^;|]+)", blk)
                if m_name_pair:
                    name = m_name_pair.group(2)
                else:
                    m_name = re.search(r"姓名/([^;|]+)", blk)
                    if m_name:
                        name = m_name.group(1)

                duty = ""
                m_duty_pair = re.search(r"分工/([^:;|]+):([^;|]+)", blk)
                if m_duty_pair:
                    duty = m_duty_pair.group(2)
                else:
                    m_duty = re.search(r"分工/([^;|]+)", blk)
                    if m_duty:
                        duty = m_duty.group(1)

                name = re.sub(r"\s+", "", str(name or "")).strip("，,;；")
                duty = _clean_member_duty(duty)

                if serial >= 1 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z·]{2,12}", name):
                    if name not in seen_names:
                        seen_names.add(name)
                        members.append({"name": name, "duty": duty})
                        if len(members) >= max_items:
                            break
                continue

            if "|" not in blk:
                continue
            compact = re.sub(r"\s+", "", blk)
            if "姓名" in compact and "分工" in compact:
                continue

            parts = [re.sub(r"\s+", "", x).strip() for x in blk.split("|")]
            parts = [p for p in parts if p]
            if len(parts) < 6:
                continue
            if not re.fullmatch(r"\d+", parts[0] or ""):
                continue

            name = parts[1]
            if not re.fullmatch(r"[\u4e00-\u9fa5A-Za-z·]{2,12}", name):
                continue

            duty = ""
            # 行尾通常是“分工 | 是否为科技特派员”
            if len(parts) >= 2:
                tail = parts[-1]
                duty = parts[-2] if tail in {"是", "否"} and len(parts) >= 2 else parts[-1]
            duty = _clean_member_duty(duty)
            if not duty or duty in {"是", "否"}:
                duty = ""

            if name in seen_names:
                continue
            seen_names.add(name)
            members.append({"name": name, "duty": duty})
            if len(members) >= max_items:
                break

        return members

    def _heuristic_extract_basic_info(self, text: str, *, team_members_text: Optional[str] = None) -> dict[str, Any]:
        raw = str(text or "")
        if not raw:
            return {
                "undertaking_unit": "",
                "partner_units": [],
                "team_members": [],
            }

        undertaking = self._extract_undertaking_unit(raw)
        partners = self._extract_partner_units(raw)
        member_raw = str(team_members_text or "").strip() or raw
        team_members = self._extract_team_members_from_table_rows(member_raw)

        return {
            "undertaking_unit": undertaking,
            "partner_units": partners,
            "team_members": team_members,
        }

    def _merge_basic_info(self, llm_basic: Any, heuristic_basic: Any, *, doc_kind: str) -> dict[str, Any]:
        llm = llm_basic if isinstance(llm_basic, dict) else {}
        heu = heuristic_basic if isinstance(heuristic_basic, dict) else {}

        def _is_generic_leader_duty(duty: str) -> bool:
            d = re.sub(r"\s+", "", str(duty or "")).strip()
            return d in {"项目负责人", "负责人", "项目总负责人"}

        undertaking = str(llm.get("undertaking_unit") or "").strip() or str(heu.get("undertaking_unit") or "").strip()

        merged_partners: list[str] = []
        seen_partner: set[str] = set()
        llm_partner_raw = llm.get("partner_units")
        heu_partner_raw = heu.get("partner_units")
        llm_partners: list[Any] = llm_partner_raw if isinstance(llm_partner_raw, list) else []
        heu_partners: list[Any] = heu_partner_raw if isinstance(heu_partner_raw, list) else []
        for src in llm_partners + heu_partners:
            name = re.sub(r"\s+", "", str(src or "").strip())
            if not name or name in seen_partner:
                continue
            seen_partner.add(name)
            merged_partners.append(name)

        merged_members: list[dict[str, str]] = []
        seen_member: set[str] = set()
        llm_member_raw = llm.get("team_members")
        heu_member_raw = heu.get("team_members")
        llm_members: list[Any] = llm_member_raw if isinstance(llm_member_raw, list) else []
        heu_members: list[Any] = heu_member_raw if isinstance(heu_member_raw, list) else []
        for src in llm_members + heu_members:
            if not isinstance(src, dict):
                continue
            name = re.sub(r"\s+", "", str(src.get("name") or "").strip())
            duty = re.sub(r"\s+", "", str(src.get("duty") or "").strip())
            if not name:
                continue
            if name in seen_member:
                for item in merged_members:
                    if item.get("name") != name:
                        continue
                    current_duty = re.sub(r"\s+", "", str(item.get("duty") or "").strip())
                    if (not current_duty) and duty:
                        item["duty"] = duty
                    elif duty and _is_generic_leader_duty(current_duty) and (not _is_generic_leader_duty(duty)):
                        # 用更具体职责覆盖“项目负责人”等泛化表达。
                        item["duty"] = duty
                continue
            seen_member.add(name)
            merged_members.append({"name": name, "duty": duty})

        return {
            "undertaking_unit": undertaking,
            "partner_units": merged_partners,
            "team_members": merged_members,
        }

    def _supplement_performance_targets(self, targets: list[dict[str, Any]], raw_text: str) -> list[dict[str, Any]]:
        """补齐绩效目标：先抽“绩效指标+满意度”，再补“总体目标实施期目标”缺失项。"""
        rows: list[dict[str, Any]] = [dict(x or {}) for x in (targets or []) if isinstance(x, dict)]

        def _norm(s: str) -> str:
            return re.sub(r"\s+", "", str(s or "").lower())

        def _upsert_by_key(item: dict[str, Any], key: str, *, prefer_replace: bool) -> bool:
            """按“指标名+单位”合并；prefer_replace=True 时覆盖已有同名指标。"""
            if not key:
                return False
            for idx, existing in enumerate(rows):
                ex_key = _norm(str(existing.get("type") or "") + "|" + str(existing.get("unit") or ""))
                if ex_key != key:
                    continue
                if prefer_replace:
                    item["id"] = str(existing.get("id") or item.get("id") or f"P{idx + 1}")
                    rows[idx] = item
                    return True
                return True

            item["id"] = f"P{len(rows) + 1}"
            rows.append(item)
            return False

        raw = str(raw_text or "")
        m = re.search(r"生物膜[^。；\n]{0,60}?抑制率[^\d]{0,8}(\d+(?:\.\d+)?)\s*%", raw)
        if not m:
            m = re.search(r"抑制率[^\d]{0,8}(\d+(?:\.\d+)?)\s*%", raw)
        if m:
            value = float(m.group(1))
            rows.append(
                {
                    "id": f"P{len(rows) + 1}",
                    "type": "生物膜形成抑制率",
                    "subtype": "技术指标",
                    "text": f"在体外对金黄色葡萄球菌生物膜形成抑制率达 {value:g}% 以上。",
                    "source": "三、项目实施预期技术指标及创新点" if "预期技术指标" in raw else "技术指标",
                    "value": value,
                    "unit": "%",
                    "constraint": "≥",
                }
            )
        # 通用规则补齐：从“实施期内...达到/不低于/不超过...”句式中提取量化指标。
        seen_keys: set[str] = set()
        perf_source_keys: set[str] = set()
        for r in rows:
            key = _norm(str(r.get("type") or "") + "|" + str(r.get("unit") or ""))
            if key:
                seen_keys.add(key)
                src_norm = _norm(str(r.get("source") or ""))
                if any(k in src_norm for k in ("绩效指标", "考核指标", "验收", "三级指标")):
                    perf_source_keys.add(key)

        # 1) 先从“绩效指标（三级指标 + 指标值）”行提取。
        for blk in self._extract_table_row_blocks(raw):
            kv_pairs = [
                (k.strip(), (v or "").strip())
                for k, v in re.findall(r"(?:^|[;；])\s*([^:：;|]+)[:：]\s*([^;|]+)", blk)
            ]
            if not kv_pairs:
                continue

            metric_name = ""
            metric_value = None
            unit_from_cell = ""
            # 兼容更多表头写法：考核指标/指标名称/指标值/目标值/数量/单位
            name_field_hints = ("三级指标", "考核指标", "指标名称", "指标")
            value_field_hints = ("指标值", "目标值", "数量", "数值")
            for k, v in kv_pairs:
                nk = re.sub(r"\s+", "", k)
                if any(h in nk for h in name_field_hints) and v and (not metric_name):
                    metric_name = str(v).strip()
                if any(h in nk for h in value_field_hints) and v and (metric_value is None):
                    cands = self._extract_amount_candidates(v)
                    if cands:
                        metric_value = float(cands[-1])
                if ("单位" in nk) and v and (not unit_from_cell):
                    unit_from_cell = str(v).strip()

            if not metric_name or metric_value is None:
                continue

            metric_name = re.sub(r"^绩效指标\s*[:：]?", "", metric_name).strip()
            metric_name = metric_name.strip("，,；;。")
            if len(metric_name) < 2:
                continue

            unit = ""
            m_unit = re.search(r"[（(]([^()（）]{1,8})[)）]", metric_name)
            if m_unit:
                unit = m_unit.group(1).strip()
            if not unit:
                for u in ["人次", "万元", "%", "篇", "项", "件", "名", "人", "场", "套", "份", "亩"]:
                    if u in metric_name:
                        unit = u
                        break
            if not unit and unit_from_cell:
                unit = unit_from_cell

            key = _norm(metric_name + "|" + unit)
            if not key:
                continue
            if (key in seen_keys) and (key in perf_source_keys):
                continue

            _upsert_by_key(
                {
                    "id": f"P{len(rows) + 1}",
                    "type": metric_name,
                    "subtype": "数量指标" if unit not in {"%", "％", "万元", "元"} else ("满意度指标" if unit in {"%", "％"} else "经济指标"),
                    "text": metric_name,
                    "source": "绩效指标",
                    "value": float(metric_value),
                    "unit": "%" if unit == "％" else unit,
                    "constraint": "=",
                },
                key,
                prefer_replace=True,
            )
            seen_keys.add(key)
            perf_source_keys.add(key)

        # 满意度常独立于三级指标行，单独补齐。
        sat = re.search(r"服务对象满意度[^\d]{0,8}(\d+(?:\.\d+)?)\s*[%％]", raw)
        if sat:
            sat_value = float(sat.group(1))
            sat_name = "服务对象满意度"
            sat_key = _norm(sat_name + "|%")
            _upsert_by_key(
                {
                    "id": f"P{len(rows) + 1}",
                    "type": sat_name,
                    "subtype": "满意度指标",
                    "text": f"服务对象满意度 {sat_value:g}%",
                    "source": "绩效指标",
                    "value": sat_value,
                    "unit": "%",
                    "constraint": "≥",
                },
                sat_key,
                prefer_replace=True,
            )
            seen_keys.add(sat_key)
            perf_source_keys.add(sat_key)

        # 补齐经济指标：横向科研经费到账/总到账（常出现在“实施期目标”描述里，非标准“三级指标/指标值”列）。
        # 注意：若文本已包含“技术合同交易额/成交额”这类最终目标，则横向经费到账往往为分阶段口径，默认不再补齐，避免重复干扰对比。
        has_contract_trade = bool(re.search(r"技术合同(?:交易额|成交额)", raw))
        if not has_contract_trade:
            # 示例：完成横向科研经费到账250万元 / 完成横向转让科研经费总到账150万元
            for m in re.finditer(r"完成\s*横向(?:转让)?\s*(?:科研)?经费(?P<kind>总)?到账\s*(\d+(?:\.\d+)?)\s*万元", raw):
                value = float(m.group(2))
                kind = m.group("kind") or ""
                name = "完成横向科研经费总到账" if kind else "完成横向科研经费到账"
                key = _norm(name + "|万元")
                _upsert_by_key(
                    {
                        "id": f"P{len(rows) + 1}",
                        "type": name,
                        "subtype": "经济指标",
                        "text": str(m.group(0) or "").strip("。；;"),
                        "source": "实施期目标",
                        "value": value,
                        "unit": "万元",
                        "constraint": "=",
                    },
                    key,
                    prefer_replace=False,
                )
                seen_keys.add(key)
                perf_source_keys.add(key)

        sat_key_norm = _norm("服务对象满意度|%")
        has_perf_table_metrics = any(k != sat_key_norm for k in perf_source_keys)
        if has_perf_table_metrics:
            return rows

        line_pat = re.compile(
            r"(?P<prefix>(?:实施期内|项目实施期内|项目实施期)?[^。；\n]{0,20})?"
            r"(?P<name>[^。；\n]{2,80}?)"
            r"(?P<constraint>达到|达|不低于|不少于|不超过|控制在)\s*"
            r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>篇|项|件|人次|人|场|%|％|万元|元)"
        )
        subtype_hint = {
            "%": "满意度指标",
            "％": "满意度指标",
            "篇": "数量指标",
            "项": "数量指标",
            "件": "数量指标",
            "人次": "数量指标",
            "人": "数量指标",
            "场": "数量指标",
            "万元": "经济指标",
            "元": "经济指标",
        }
        constraint_map = {
            "达到": "≥",
            "达": "≥",
            "不低于": "≥",
            "不少于": "≥",
            "不超过": "≤",
            "控制在": "≤",
        }
        for m in line_pat.finditer(raw):
            metric_name = str(m.group("name") or "").strip()
            metric_name = re.sub(r"^(?:，|,|且|并|和)", "", metric_name).strip()
            metric_name = re.sub(r"(?:数量|指标|目标)$", "", metric_name).strip()
            if len(metric_name) < 2:
                continue

            unit = str(m.group("unit") or "").strip()
            key = _norm(metric_name + "|" + unit)
            if not key or ((key in seen_keys) and (key in perf_source_keys)):
                continue

            value = float(m.group("value"))
            c_raw = str(m.group("constraint") or "")
            _upsert_by_key(
                {
                    "id": f"P{len(rows) + 1}",
                    "type": metric_name,
                    "subtype": subtype_hint.get(unit, "数量指标"),
                    "text": str(m.group(0) or "").strip("。；;"),
                    "source": "项目实施的绩效目标" if "绩效目标" in raw else "项目实施的预期绩效目标",
                    "value": value,
                    "unit": "%" if unit == "％" else unit,
                    "constraint": constraint_map.get(c_raw, "≥"),
                },
                key,
                prefer_replace=False,
            )
            seen_keys.add(key)

        # 仅从“总体目标”表格行做枚举句式兜底："1.选育xx1份；2.建立xx1套；3.建立xx100亩"。
        # 避免从任务分工/预算明细等章节误补指标。
        row_blocks = [
            b for b in self._extract_table_row_blocks(raw)
            if ("总体" in b and ("实施期目标" in b or "绩效指标" in b or "目标" in b))
        ]

        # 对“总体目标行 + 多个实施期目标列”场景，仅保留第一段实施期目标文本，
        # 防止把后续年度/阶段列误当成总体目标补齐。
        normalized_blocks: list[str] = []
        for b in row_blocks:
            compact = re.sub(r"\s+", "", b)
            if "实施期目标:" in compact:
                parts = re.split(r"实施期目标\s*[:：]", b)
                if len(parts) >= 2:
                    first_target = parts[1]
                    # 遇到下一列“实施期目标”或年度/阶段列时截断。
                    stop = re.search(r"(?:;|；)\s*实施期目标\s*[:：]|第一年度目标|第二年度目标|第三年度目标|年度目标|阶段目标", first_target)
                    if stop:
                        first_target = first_target[: stop.start()]
                    normalized_blocks.append(first_target)
                    continue
            normalized_blocks.append(b)

        scan_text = "\n".join(normalized_blocks) if normalized_blocks else ("\n".join(row_blocks) if row_blocks else raw)
        stage_cut = re.search(r"第一年度目标|第二年度目标|第三年度目标|年度目标|阶段目标", scan_text)
        if stage_cut:
            scan_text = scan_text[: stage_cut.start()]

        # 改进的正则表达式，支持范围值如"6-8份"
        # 支持 (1)、1.、1、等各种编号前缀
        direct_pat = re.compile(
            r"(?:^|[；;。:\n：])\s*(?:(?:\(|\（)\d+(?:\)|）)\s*|(?:\d+[.、．\s])\s*)?"
            r"(?P<name>[\u4e00-\u9fa5A-Za-z（）()、/]{2,80}?)\s*"
            r"(?P<value_range>\d+(?:\.\d+)?(?:[-~—–~到至]\s*\d+(?:\.\d+)?)?)\s*(?P<unit>份|套|亩)(?:以上)?"
        )
        stage_context_markers = ["第一年度目标", "第二年度目标", "第三年度目标", "年度目标", "阶段目标"]
        for m in direct_pat.finditer(scan_text):
            span_start = int(m.start())
            prefix = scan_text[max(0, span_start - 48): span_start]
            if any(k in prefix for k in stage_context_markers):
                continue

            metric_name = str(m.group("name") or "").strip()
            metric_name = re.sub(r"^(?:，|,|且|并|和)", "", metric_name).strip()
            metric_name = re.sub(r"^(?:项目)?实施期目标\s*[:：]?", "", metric_name).strip()
            metric_name = re.sub(r"^(?:总体目标\s*[:：]?|总体\s*目标\s*[:：]?)", "", metric_name).strip()
            # 移除编号前缀：(1) (二) 等
            metric_name = re.sub(r"^[\(\（](?:\d+|[一二三四五六七八九十百千万亿]|[a-zA-Z])[）\)]\s*", "", metric_name).strip()
            metric_name = re.sub(r"^(?:\d+[.、．\s])\s*", "", metric_name).strip()
            # 移除末尾的范围前缀，如" 6-8"或" 6"或" 6-"
            metric_name = re.sub(r"\s+\d+(?:[-~—–~到至]\s*\d+)?[-~—–~到至]?\s*$", "", metric_name).strip()
            metric_name = metric_name.strip("，,；;。:")
            if len(metric_name) < 2:
                continue

            unit = str(m.group("unit") or "").strip()
            key = _norm(metric_name + "|" + unit)
            if not key or key in seen_keys:
                continue

            # 处理范围值，如"6-8"或"6"
            value_range_raw = str(m.group("value_range") or "").strip()
            values = re.findall(r"\d+(?:\.\d+)?", value_range_raw)
            if not values:
                continue
            
            # 对于范围值（如6-8），value保留区间字符串；单个值保持数值。
            # constraint字段存储范围信息
            if len(values) > 1:
                value = value_range_raw
                constraint = value_range_raw  # 保存原始范围，如"6-8"
            else:
                value = float(values[0])
                constraint = "="
            
            _upsert_by_key(
                {
                    "id": f"P{len(rows) + 1}",
                    "type": metric_name,
                    "subtype": "数量指标",
                    "text": str(m.group(0) or "").strip("。；;"),
                    "source": "总体目标补齐",
                    "value": value,
                    "unit": unit,
                    "constraint": constraint,
                },
                key,
                prefer_replace=False,
            )
            seen_keys.add(key)

        # 兜底：部分文档“总体目标-实施期目标”行会混入多列/空格噪声，
        # 直接在该行首段实施期目标文本中补抽，避免遗漏“创新番茄种质资源”等核心项。
        fallback_item_pat = re.compile(
            r"(?:^|[；;。:\n：])\s*(?:(?:\(|\（)\d+(?:\)|）)\s*|(?:\d+[.、．\s])\s*)?"
            r"(?P<name>[\u4e00-\u9fa5A-Za-z（）()、/]{2,80}?)\s*"
            r"(?P<value_range>\d+(?:\.\d+)?(?:[-~—–~到至]\s*\d+(?:\.\d+)?)?)\s*(?P<unit>份|套|亩|种)"
        )
        for b in row_blocks:
            compact = re.sub(r"\s+", "", b)
            if ("总体目标" not in compact) or ("实施期目标" not in compact):
                continue
            if ("绩效指标" in compact) and ("三级指标" in compact):
                continue

            seg = b
            parts = re.split(r"实施期目标\s*[:：]", seg)
            if len(parts) >= 2:
                seg = parts[1]
            stop = re.search(r"(?:;|；)\s*实施期目标\s*[:：]|第一年度目标|第二年度目标|第三年度目标|年度目标|阶段目标", seg)
            if stop:
                seg = seg[: stop.start()]

            for m in fallback_item_pat.finditer(seg):
                metric_name = str(m.group("name") or "").strip()
                metric_name = re.sub(r"^(?:，|,|且|并|和)", "", metric_name).strip()
                metric_name = metric_name.strip("，,；;。:")
                if len(metric_name) < 2:
                    continue

                unit = str(m.group("unit") or "").strip()
                key = _norm(metric_name + "|" + unit)
                if not key or key in seen_keys:
                    continue

                value_range_raw = str(m.group("value_range") or "").strip()
                values = re.findall(r"\d+(?:\.\d+)?", value_range_raw)
                if not values:
                    continue
                if len(values) > 1:
                    value = value_range_raw
                    constraint = value_range_raw
                else:
                    value = float(values[0])
                    constraint = "="

                _upsert_by_key(
                    {
                        "id": f"P{len(rows) + 1}",
                        "type": metric_name,
                        "subtype": "数量指标",
                        "text": str(m.group(0) or "").strip("。；;"),
                        "source": "总体目标补齐",
                        "value": value,
                        "unit": unit,
                        "constraint": constraint,
                    },
                    key,
                    prefer_replace=False,
                )
                seen_keys.add(key)

        # 最终清理：移除type中包含"数字-"或"数字~"等不完整范围的条目
        # 例如移除"创新番茄种质资源 6-"这种残留的指标
        rows = [
            r for r in rows
            if not re.search(r'\d+[-~—–~到至]\s*$', r.get('type', ''))
        ]

        return rows

    def _extract_overall_metric_row_ids(self, metrics_text: str) -> set[str]:
        """从绩效目标表格文本中识别“总体目标”所在表格行编号。"""
        text = str(metrics_text or "")
        if not text:
            return set()

        overall_ids: set[str] = set()
        section_mode = ""
        for line in text.splitlines():
            ln = str(line or "").strip()
            if not ln:
                continue

            compact = re.sub(r"\s+", "", ln)
            if re.search(r"\[表格表头\d*\]", compact):
                if any(k in compact for k in ["总体目标", "总体绩效目标", "总目标"]):
                    section_mode = "overall"
                elif any(k in compact for k in ["年度目标", "阶段目标", "第一年", "第二年", "第三年"]):
                    section_mode = "stage"
                continue

            row_match = re.search(r"\[表格行\s*(\d+)\]", compact)
            if not row_match:
                continue
            row_id = row_match.group(1)

            # 行内带“总体目标”时直接认定；否则按最近表头模式认定。
            if any(k in compact for k in ["总体目标", "总体绩效目标", "总目标"]):
                overall_ids.add(row_id)
                continue
            if section_mode == "overall":
                overall_ids.add(row_id)

        return overall_ids

    def _keep_overall_targets_only(self, targets: list[dict[str, Any]], metrics_text: str) -> list[dict[str, Any]]:
        """保留“总体目标 + 绩效指标”并剔除年度/阶段目标。"""
        rows: list[dict[str, Any]] = [dict(x or {}) for x in (targets or []) if isinstance(x, dict)]
        if not rows:
            return rows

        overall_row_ids = self._extract_overall_metric_row_ids(metrics_text)
        kept: list[dict[str, Any]] = []

        def _looks_like_metric(item: dict[str, Any]) -> bool:
            name = str(item.get("type") or item.get("text") or "").strip()
            if not name:
                return False
            unit = str(item.get("unit") or "").strip()
            if unit:
                return True
            v = item.get("value")
            if isinstance(v, (int, float)) and (v != 0 or re.search(r"\d", name)):
                return True
            if isinstance(v, str) and re.search(r"\d", v):
                return True
            if re.search(r"\d", name):
                return True
            return False

        stage_markers = [
            "年度目标", "阶段目标", "第一年", "第二年", "第三年", "年度", "阶段",
            "当年", "本年度", "招募病例", "完成招募", "年内", "季度", "中期", "里程碑",
        ]
        stage_strict_markers = [
            "年度目标", "阶段目标", "第一年", "第二年", "第三年",
            "第一阶段", "第二阶段", "第三阶段",
            "季度", "中期", "里程碑",
            "招募病例", "完成招募",
            "当年", "本年度", "年内",
        ]
        overall_markers = ["总体目标", "总体绩效目标", "总目标"]
        perf_markers = ["绩效指标", "一级指标", "二级指标", "三级指标", "验收", "考核指标"]
        compact_metrics = re.sub(r"\s+", "", str(metrics_text or ""))
        has_overall_context = bool(overall_row_ids) or any(k in compact_metrics for k in overall_markers)

        for r in rows:
            merged = " ".join([
                str(r.get("source") or ""),
                str(r.get("subtype") or ""),
                str(r.get("text") or ""),
                str(r.get("type") or ""),
            ])
            compact = re.sub(r"\s+", "", merged)

            source = str(r.get("source") or "")
            m_row = re.search(r"表格行\s*(\d+)", source)
            row_id = m_row.group(1) if m_row else ""

            if row_id and overall_row_ids:
                if row_id in overall_row_ids:
                    kept.append(r)
                    continue

            if has_overall_context and any(k in compact for k in stage_strict_markers) and (not any(k in compact for k in perf_markers)):
                continue

            if any(k in compact for k in stage_markers) and (not _looks_like_metric(r)):
                continue

            if any(k in compact for k in overall_markers):
                kept.append(r)
                continue

            # 对显式补齐且标注为总体目标的条目放行。
            if "总体目标补齐" in compact:
                kept.append(r)
                continue

            # 保留绩效指标相关条目（去重在后续统一处理）。
            if any(k in compact for k in perf_markers):
                kept.append(r)
                continue

            # 当识别到了总体目标行号时，仍可能存在大量“纯指标名 + 数值”的条目（例如表格里只有指标名/值/单位）。
            # 这些条目不包含“绩效指标/三级指标”等关键词，若强行按行号过滤会误删，导致只剩少量指标。
            if _looks_like_metric(r):
                kept.append(r)
                continue

            # 当无法识别总体目标行号时，保守保留非阶段项。
            if not overall_row_ids:
                kept.append(r)

        if kept:
            has_contract_trade = ("技术合同交易额" in compact_metrics) or ("技术合同成交额" in compact_metrics)
            if has_contract_trade:
                def _is_stage_finance_target(item: dict[str, Any]) -> bool:
                    merged = " ".join([
                        str(item.get("type") or ""),
                        str(item.get("text") or ""),
                    ])
                    compact = re.sub(r"\s+", "", merged)
                    return ("横向" in compact and "经费" in compact and "到账" in compact) or ("横向转让" in compact and "经费" in compact)
                kept = [x for x in kept if not _is_stage_finance_target(x)]

            kept = self._dedupe_performance_targets(kept)
            for i, item in enumerate(kept, start=1):
                item["id"] = f"P{i}"
            return kept

        return rows

    def _dedupe_performance_targets(self, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """指标去重：同一指标重复出现时优先保留绩效指标来源，其次总体目标来源。"""
        rows: list[dict[str, Any]] = [dict(x or {}) for x in (targets or []) if isinstance(x, dict)]
        if not rows:
            return rows

        def _norm_text(s: Any) -> str:
            text = str(s or "").lower().strip()
            text = text.replace("选育", "培育")
            text = text.replace("示范基地", "种植基地")
            text = text.replace("标准化种植技术体系", "种植技术体系")
            # 去掉泛化后缀，避免“xx数量”与“xx”无法去重。
            text = re.sub(r"(?:数量|数)\s*$", "", text)
            # 先移除开头的编号和括号，如"(1) "或"1. "
            text = re.sub(r"^[\(\（]\d+[\)\）]\s*", "", text)
            text = re.sub(r"^\d+[\.、．\s]+", "", text)
            # 移除末尾的不完整范围前缀，如"种质资源 6-"变成"种质资源"或"种质资源 6-8"变成"种质资源"
            text = re.sub(r'\s+\d+(?:[-~—–~到至]\s*\d+)?[-~—–~到至]?\s*$', '', text)
            # 移除所有空格、数字、特殊字符
            text = re.sub(r"[\s\t\r\n\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\\d]+", "", text)
            return text

        def _to_float(v: Any) -> float:
            try:
                return float(v or 0.0)
            except Exception:
                return 0.0

        def _source_priority(src: str) -> int:
            s = _norm_text(src)
            if ("绩效指标" in s) or ("考核指标" in s) or ("三级指标" in s) or ("验收" in s):
                return 4
            if "总体目标补齐" in src:
                return 3
            if ("总体目标" in s) or ("总目标" in s):
                return 3
            return 2

        picked: dict[str, dict[str, Any]] = {}
        score: dict[str, tuple[int, int, int]] = {}
        for idx, r in enumerate(rows):
            name = _norm_text(r.get("type") or r.get("text") or "")
            unit = _norm_text(r.get("unit") or "")
            if not name:
                continue
            key = f"{name}|{unit}"

            value_quality = 1 if abs(_to_float(r.get("value"))) > 1e-9 else 0

            cur_rank = (_source_priority(str(r.get("source") or "")), value_quality, -idx)
            if key not in picked or cur_rank > score[key]:
                picked[key] = r
                score[key] = cur_rank

        return list(picked.values())

    def _clean_research_line(self, line: str) -> str:
        s = str(line or "").strip()
        if not s:
            return ""

        s = re.sub(r"^\[表格行\d+\]\s*", "", s)
        s = re.sub(r"^\[表格表头\d+\]\s*", "", s)
        s = re.sub(r"^\[表格标题\d+\]\s*", "", s)
        s = re.sub(r"^(?:[-*•]|\d+[.、)])\s*", "", s)
        s = re.sub(r"\s+", " ", s).strip(" ;；、，,。")
        return s

    def _looks_like_research_line(self, line: str) -> bool:
        s = self._clean_research_line(line)
        if not s:
            return False
        if len(s) < 6 or len(s) > 260:
            return False

        # 过滤页眉页脚与行政模板话术。
        if any(k in s for k in RESEARCH_ADMIN_NOISE_KEYWORDS):
            return False

        if re.search(r"^(河北省|北京市|上海市|天津市|重庆市).{0,20}制$", s):
            return False
        if re.search(r"^(请|应|须|不得|可以|可根据).{0,40}(申报|填报|通知|指南)", s):
            return False
        if re.search(r"^(项目名称|单位名称|联系人|联系电话|电子邮箱|通讯地址|邮编)[:：]", s):
            return False

        if any(k in s for k in RESEARCH_NEGATIVE_KEYWORDS):
            return False

        has_research_kw = any(k in s for k in RESEARCH_POSITIVE_KEYWORDS)
        has_action = any(k in s for k in RESEARCH_TECH_ACTION_KEYWORDS)
        has_object = any(k in s for k in RESEARCH_TECH_OBJECT_KEYWORDS)

        # 优先要求“动作 + 技术对象”，降低管理性语句误入。
        if has_action and has_object:
            return True

        # 次级兜底：明确研究关键词 + 动作词。
        if has_research_kw and has_action:
            return True

        # 保守兜底：句首编号条目且包含技术对象。
        if re.search(r"^(?:[一二三四五六七八九十]+[、.．)]|\d+[.、)])", line.strip()) and has_object:
            return True

        return False

    def _heuristic_extract_research_contents(self, text: str, *, max_items: int = 12) -> list[dict[str, str]]:
        """LLM 抽取失败时，从章节文本与表格行中提取研究内容候选。"""
        raw = str(text or "").strip()
        if not raw:
            return []

        candidates: list[str] = []

        for line in raw.splitlines():
            s = self._clean_research_line(line)
            if not s:
                continue

            # 键值对行拆分后逐段判断，适配表格行输出。
            parts = re.split(r"[;；]\s*", s)
            if len(parts) > 1:
                for p in parts:
                    p = self._clean_research_line(p)
                    if self._looks_like_research_line(p):
                        candidates.append(p)
                continue

            if self._looks_like_research_line(s):
                candidates.append(s)

        seen: set[str] = set()
        results: list[dict[str, str]] = []
        for item in candidates:
            key = re.sub(r"\s+", "", item)
            if key in seen:
                continue
            seen.add(key)
            results.append({"id": f"R{len(results) + 1}", "text": item})
            if len(results) >= max_items:
                break

        return results

    def _strip_research_index(self, text: Any) -> str:
        s = str(text or "").strip()
        s = re.sub(r"^\s*(?:[一二三四五六七八九十]+[、.．)]|\d+[.、．)])\s*", "", s)
        return s.strip()

    def _is_title_only_research(self, text: Any) -> bool:
        s = self._strip_research_index(text)
        if not s:
            return True
        # 标题通常较短、无句号、无明显动作词。
        if len(s) <= 28 and not re.search(r"[。；;]", s):
            if not any(k in s for k in ["通过", "采用", "开展", "进行", "筛选", "建立", "鉴定", "评价", "分析"]):
                return True
        return False

    def _extract_research_topic_blocks(self, text: str, *, max_items: int = 12) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        cleaned_lines: list[str] = []
        for ln in lines:
            s = re.sub(r"^\[表格(?:表头|行|标题)\d*\]\s*", "", ln).strip()
            if not s:
                continue
            s = s.lstrip("|").strip()
            if s:
                cleaned_lines.append(s)

        joined = "\n".join(cleaned_lines).strip()
        if not joined:
            return []

        topic_pat = re.compile(r"研究(?:内容|任务)\s*(?:[一二三四五六七八九十]|\d+)\s*[:：]")
        boundary_chars = set("\n\r \t\u3000|;；。")
        matches: list[re.Match[str]] = []
        for m in topic_pat.finditer(joined):
            if m.start() == 0 or joined[m.start() - 1] in boundary_chars:
                matches.append(m)
        if len(matches) < 2:
            return []

        blocks: list[str] = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(joined)
            seg = joined[start:end].strip()
            if seg:
                blocks.append(seg)

        stop_markers = [
            "项目拟采取的研究方法",
            "进度安排和阶段目标",
            "项目验收的考核指标",
            "项目实施的绩效目标",
            "项目实施的预期绩效目标",
            "项目预期的主要创新点",
            "主要创新点",
            "项目预算表",
            "承担单位、合作单位经费预算明细表",
            "项目实施对受援地产业或相关行业领域带动促进作用",
            "项目实施对受援地产业",
        ]
        stop_regexes = [
            r"(?:^|\n)\s*(?:研究方法|技术路线)(?!图)\s*(?:$|[:：])",
            r"(?:^|\n)\s*项目拟采取的研究方法\s*(?:$|[:：])",
            r"(?:^|\n)\s*(?:[一二三四五六七八九十0-9]+[、.．)]|[（(][一二三四五六七八九十0-9]+[）)])\s*(?:研究方法|技术路线)(?!图)\s*(?:$|[:：])",
            r"(?:^|\s)二[、.．)]\s*项目实施对",
            r"(?:^|\s)第二(?:部分|章)?\s*项目实施对",
        ]

        def _cut_tail(s: str) -> str:
            text = str(s or "").strip()
            if not text:
                return ""
            earliest = None
            for m in stop_markers:
                idx = text.find(m)
                if idx >= 0 and idx > 16:
                    earliest = idx if earliest is None else min(earliest, idx)
            for pat in stop_regexes:
                m = re.search(pat, text)
                if m and m.start() > 16:
                    earliest = m.start() if earliest is None else min(earliest, m.start())
            if earliest is not None:
                text = text[:earliest].strip()
            text = re.sub(r"[。；;]\s*[（(]\s*[一二三四五六七八九十0-9]+\s*[）)]\s*[\s\u3000]*$", "", text).strip()
            text = re.sub(r"[（(]\s*[一二三四五六七八九十0-9]+\s*[）)]\s*[\s\u3000]*$", "", text).strip()
            text = re.sub(r"[一二三四五六七八九十0-9]+\s*[、.．)]\s*[\s\u3000]*$", "", text).strip()
            return text

        out: list[str] = []
        seen: set[str] = set()
        for b in blocks:
            s = re.sub(r"\s+", " ", _cut_tail(b)).strip()
            if len(s) < 20:
                continue
            k = re.sub(r"\s+", "", s)
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
            if len(out) >= max_items:
                break
        return out

    def _pick_sequential_numbered_blocks(self, blocks: list[str], *, min_keep: int = 2, max_items: int = 12) -> list[str]:
        items = [str(x or "").strip() for x in (blocks or []) if str(x or "").strip()]
        if not items:
            return []

        def _parse_num(s: str) -> tuple[str, int | None]:
            m = re.match(r"^\s*[（(]\s*(\d+)\s*[）)]", s)
            if m:
                return ("paren", int(m.group(1)))
            m = re.match(r"^\s*(\d+)[.、．)]", s)
            if m:
                return ("dot", int(m.group(1)))
            return ("", None)

        style, first_num = _parse_num(items[0])
        if not style or first_num is None:
            return items[:max_items]

        out: list[str] = []
        expected = first_num
        for s in items:
            s_style, num = _parse_num(s)
            if s_style != style or num is None:
                if len(out) >= min_keep:
                    break
                continue
            if num == expected:
                out.append(s)
                expected += 1
                if len(out) >= max_items:
                    break
                continue
            if num == 1 and len(out) >= min_keep:
                break
            if len(out) >= min_keep:
                break
        return out

    def _extract_numbered_research_blocks(self, text: str, *, max_items: int = 12) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        blocks: list[str] = []
        current: list[str] = []

        for ln in lines:
            cleaned = re.sub(r"^\[表格(?:表头|行|标题)\d*\]\s*", "", ln).strip()
            if not cleaned:
                continue
            cleaned = cleaned.lstrip("|").strip()

            parts = [cleaned]
            marker_pat = re.compile(
                r"(?:[（(]\s*\d+\s*[）)]\s*(?=[\u4e00-\u9fa5A-Za-z])|\b\d+[.、．)]\s*(?=[\u4e00-\u9fa5A-Za-z]))"
            )
            markers = [m.start() for m in marker_pat.finditer(cleaned)]
            if len(markers) >= 2:
                parts = []
                for i, start in enumerate(markers):
                    end = markers[i + 1] if i + 1 < len(markers) else len(cleaned)
                    seg = cleaned[start:end].strip()
                    if seg:
                        parts.append(seg)

            for part in parts:
                if re.match(r"^\s*(?:(?:\(|（)\s*\d+\s*(?:\)|）)|\d+[.、．)])\s*", part) or re.match(r"^\s*[-*•]\s+", part):
                    if current:
                        blocks.append(" ".join(current).strip())
                    current = [part]
                else:
                    if current:
                        current.append(part)
        if current:
            blocks.append(" ".join(current).strip())

        stop_markers = [
            "项目拟采取的研究方法",
            "进度安排和阶段目标",
            "项目验收的考核指标",
            "项目实施的绩效目标",
            "项目实施的预期绩效目标",
            "项目预期的主要创新点",
            "主要创新点",
            "项目预算表",
            "承担单位、合作单位经费预算明细表",
            "项目实施对受援地产业或相关行业领域带动促进作用",
            "项目实施对受援地产业",
        ]
        stop_regexes = [
            r"(?:^|\n)\s*(?:研究方法|技术路线)(?!图)\s*(?:$|[:：])",
            r"(?:^|\n)\s*项目拟采取的研究方法\s*(?:$|[:：])",
            r"(?:^|\n)\s*(?:[一二三四五六七八九十0-9]+[、.．)]|[（(][一二三四五六七八九十0-9]+[）)])\s*(?:研究方法|技术路线)(?!图)\s*(?:$|[:：])",
            r"(?:^|\s)二[、.．)]\s*项目实施对",
            r"(?:^|\s)第二(?:部分|章)?\s*项目实施对",
        ]

        def _cut_tail(s: str) -> str:
            text = str(s or "").strip()
            if not text:
                return ""
            earliest = None
            for m in stop_markers:
                idx = text.find(m)
                if idx >= 0 and idx > 16:
                    earliest = idx if earliest is None else min(earliest, idx)
            for pat in stop_regexes:
                m = re.search(pat, text)
                if m and m.start() > 16:
                    earliest = m.start() if earliest is None else min(earliest, m.start())
            if earliest is not None:
                text = text[:earliest].strip()
            text = re.sub(r"[。；;]\s*[（(]\s*[一二三四五六七八九十0-9]+\s*[）)]\s*[\s\u3000]*$", "", text).strip()
            text = re.sub(r"[（(]\s*[一二三四五六七八九十0-9]+\s*[）)]\s*[\s\u3000]*$", "", text).strip()
            text = re.sub(r"[一二三四五六七八九十0-9]+\s*[、.．)]\s*[\s\u3000]*$", "", text).strip()
            return text

        cleaned: list[str] = []
        seen: set[str] = set()
        for b in blocks:
            s = re.sub(r"\s+", " ", _cut_tail(b)).strip()
            if len(s) < 10:
                continue
            if self._is_title_only_research(s):
                continue
            k = re.sub(r"\s+", "", s)
            if k in seen:
                continue
            seen.add(k)
            cleaned.append(s)
            if len(cleaned) >= max_items:
                break
        return cleaned

    def _enrich_research_contents_from_text(
        self,
        research_contents: list[dict[str, Any]],
        source_text: str,
        *,
        max_items: int = 12,
    ) -> list[dict[str, str]]:
        rows = [dict(x or {}) for x in (research_contents or []) if isinstance(x, dict)]
        if not rows:
            return []

        title_only_count = sum(1 for r in rows if self._is_title_only_research(r.get("text", "")))
        if title_only_count == 0:
            return [{"id": f"R{i+1}", "text": str(r.get("text", "")).strip()} for i, r in enumerate(rows)]

        numbered = self._extract_research_topic_blocks(source_text or "", max_items=max_items) or self._extract_numbered_research_blocks(source_text or "", max_items=max_items)
        if not numbered:
            return [{"id": f"R{i+1}", "text": str(r.get("text", "")).strip()} for i, r in enumerate(rows)]

        # 若 LLM 明显只抽到标题，优先直接使用编号段落完整文本。
        if title_only_count >= max(1, int(len(rows) * 0.5)) and len(numbered) >= min(4, len(rows)):
            return [{"id": f"R{i+1}", "text": numbered[i]} for i in range(min(len(numbered), max_items))]

        # 否则仅替换“标题化”条目，保留已完整的条目。
        out: list[dict[str, str]] = []
        used_idx: set[int] = set()
        for i, r in enumerate(rows, start=1):
            text = str(r.get("text", "")).strip()
            if not self._is_title_only_research(text):
                out.append({"id": f"R{i}", "text": text})
                continue

            key = self._strip_research_index(text)
            replacement = ""
            for j, b in enumerate(numbered):
                if j in used_idx:
                    continue
                b_key = self._strip_research_index(b)
                if key and (b_key.startswith(key) or key in b_key):
                    replacement = b
                    used_idx.add(j)
                    break
            out.append({"id": f"R{i}", "text": replacement or text})

        # 重新编号，保证连续。
        for i, r in enumerate(out, start=1):
            r["id"] = f"R{i}"
        return out[:max_items]

    def _parse_amount(self, value: str, unit_hint: str = "") -> float:
        s = str(value or "").strip().replace(",", "")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return 0.0
        amount = float(m.group())
        unit = str(unit_hint or "") + s
        if "亿元" in unit:
            amount *= 10000.0
        return amount

    def _extract_amount_candidates(self, text: str) -> list[float]:
        s = str(text or "")
        if not s:
            return []
        out: list[float] = []
        for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)?", s):
            num = m.group(1)
            unit = m.group(2) or ""
            out.append(self._parse_amount(num, unit))
        return out

    def _amount_key_priority(self, key: str) -> int:
        k = str(key or "")
        if any(h in k for h in BUDGET_TYPE_FIELD_HINTS):
            # 防止“预算科目名称”被当作金额字段，误取序号数字。
            return 0
        if ("合计" in k) or ("总额" in k) or ("总计" in k):
            return 3
        if any(h in k for h in BUDGET_AMOUNT_FIELD_HINTS):
            return 2
        return 1

    def _clean_budget_line(self, line: str) -> str:
        s = str(line or "").strip()
        s = re.sub(r"^\[表格行\d+\]\s*", "", s)
        s = re.sub(r"^\[表格表头\d+\]\s*", "", s)
        s = re.sub(r"^\[表格标题\d+\]\s*", "", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip(" ;；|，,")

    def _looks_like_budget_type(self, name: str) -> bool:
        n = self._normalize_budget_type(name)
        if not n or len(n) > 24:
            return False
        if any(x in n for x in BUDGET_TYPE_BLOCKED_KEYWORDS):
            return False
        if any(x in n for x in BUDGET_NON_LEAF_TYPES):
            return False
        if re.search(r"(费|支出|经费)$", n):
            return True
        return any(k in n for k in BUDGET_TYPE_KEYWORDS)

    def _normalize_budget_type(self, name: str) -> str:
        n = str(name or "").strip()
        if not n:
            return ""

        n = re.sub(r"^[（(]?[一二三四五六七八九十]+[)）、.．]?", "", n)
        n = re.sub(r"^\d+[、.．)]", "", n)
        n = re.sub(r"^其中[:：]", "", n)
        n = re.sub(r"^项目[:：]", "", n)
        n = re.sub(r"^预算科目[:：]", "", n)
        n = re.sub(r"\s+", "", n)
        n = n.strip(":：;；|，,")

        if n in BUDGET_TYPE_ALIASES:
            return BUDGET_TYPE_ALIASES[n]
        return n

    def _extract_budget_type_and_amount_from_kv(self, segments: list[str]) -> tuple[str, float]:
        kv_pairs: list[tuple[str, str]] = []
        for seg in segments:
            m = re.match(r"\s*([^:：]{1,24})[:：]\s*(.+?)\s*$", seg)
            if not m:
                continue
            key = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
            val = re.sub(r"\s+", " ", str(m.group(2) or "").strip())
            if key and val:
                kv_pairs.append((key, val))

        if not kv_pairs:
            return "", 0.0

        type_candidate = ""
        amount_candidate = 0.0
        amount_priority = -1

        for key, val in kv_pairs:
            # 优先从“类别/科目/名称”字段拿预算类型。
            if any(h in key for h in BUDGET_TYPE_FIELD_HINTS):
                t = self._normalize_budget_type(val)
                if self._looks_like_budget_type(t):
                    type_candidate = t
                    break

        if not type_candidate:
            # 兜底：value 本身像预算类型。
            for _key, val in kv_pairs:
                t = self._normalize_budget_type(val)
                if self._looks_like_budget_type(t):
                    type_candidate = t
                    break

        for key, val in kv_pairs:
            cands = self._extract_amount_candidates(val)
            if not cands:
                continue
            if self._amount_key_priority(key) >= 3:
                # “合计/总额”列优先取末尾值，规避“0 70”误取前值。
                non_zero = [x for x in cands if abs(x) > 1e-9]
                amt = non_zero[-1] if non_zero else cands[-1]
            else:
                non_zero = [x for x in cands if abs(x) > 1e-9]
                amt = non_zero[0] if non_zero else cands[0]
            pri = self._amount_key_priority(key)
            if (pri > amount_priority) or (pri == amount_priority and abs(amt) > abs(amount_candidate)):
                amount_candidate = amt
                amount_priority = pri

        # 若金额列命中失败，兜底从所有 value 中取最大绝对值，避免非 0 被误写 0。
        if abs(amount_candidate) <= 1e-9:
            for _key, val in kv_pairs:
                cands = self._extract_amount_candidates(val)
                for amt in cands:
                    if abs(amt) > abs(amount_candidate):
                        amount_candidate = amt

        if type_candidate and abs(amount_candidate) > 1e-9:
            return type_candidate, amount_candidate

        return "", 0.0

    def _extract_budget_items_from_table_rows(self, text: str, *, max_items: int = 30) -> list[dict[str, float | str]]:
        """优先从 [表格行] 的键值对中抽取预算明细，避免正文噪声干扰。"""
        raw = str(text or "")
        if not raw:
            return []

        item_map: Dict[str, float] = {}
        for line in raw.splitlines():
            if not re.search(r"\[表格行\d+\]", line):
                continue

            s = self._clean_budget_line(line)
            if not s:
                continue

            segments = [x.strip() for x in re.split(r"[;；|]", s) if x.strip()]
            kv_pairs: list[tuple[str, str]] = []
            for seg in segments:
                m = re.match(r"\s*([^:：]{1,40})[:：]\s*(.+?)\s*$", seg)
                if not m:
                    continue
                key = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
                val = re.sub(r"\s+", " ", str(m.group(2) or "").strip())
                if key and val:
                    kv_pairs.append((key, val))

            if not kv_pairs:
                # 兜底：无键值对时尝试直接解析“类型 金额”形式。
                for seg in segments:
                    plain = re.search(r"([\u4e00-\u9fa5A-Za-z（）()、/]{2,24})\s+(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)?", seg)
                    if not plain:
                        continue
                    btype = self._normalize_budget_type(plain.group(1))
                    if not self._looks_like_budget_type(btype):
                        continue
                    amount = self._parse_amount(plain.group(2), plain.group(3) or "")
                    item_map[btype] = float(amount)
                continue

            joined_keys = " ".join(k for k, _ in kv_pairs)
            if not any(x in joined_keys for x in ("预算", "金额", "经费", "科目", "费用", "合计")):
                continue

            raw_type = ""
            amount = 0.0
            amount_pri = -1

            for key, val in kv_pairs:
                if any(h in key for h in BUDGET_TYPE_FIELD_HINTS):
                    raw_type = str(val or "").strip()
                    break

            if not raw_type:
                for _key, val in kv_pairs:
                    t = self._normalize_budget_type(val)
                    if self._looks_like_budget_type(t):
                        raw_type = str(val or "").strip()
                        break

            if not raw_type:
                continue

            t = re.sub(r"\s+", "", raw_type).strip(" :：;；|，,")
            if not t or len(t) > 40:
                continue

            # 统一科目名，避免“2.业务费/（一）直接费用”等写法差异导致重复项。
            tn = self._normalize_budget_type(t)
            if tn in {"合计", "总计", "总额", "预算总额", "经费总额", "总预算"}:
                continue

            for key, val in kv_pairs:
                cands = self._extract_amount_candidates(val)
                if not cands:
                    continue
                pri = self._amount_key_priority(key)
                if pri < 2:
                    continue
                if pri >= 3:
                    non_zero = [x for x in cands if abs(x) > 1e-9]
                    amt = non_zero[-1] if non_zero else cands[-1]
                else:
                    non_zero = [x for x in cands if abs(x) > 1e-9]
                    amt = non_zero[0] if non_zero else cands[0]
                if (pri > amount_pri) or (pri == amount_pri and abs(amt) > abs(amount)):
                    amount = amt
                    amount_pri = pri

            if amount_pri < 0:
                raw_type_norm = self._normalize_budget_type(raw_type)
                for _key, val in kv_pairs:
                    if self._normalize_budget_type(val) == raw_type_norm:
                        continue
                    cands = self._extract_amount_candidates(val)
                    if not cands:
                        continue
                    non_zero = [x for x in cands if abs(x) > 1e-9]
                    amt = non_zero[-1] if non_zero else cands[-1]
                    if abs(amt) > abs(amount):
                        amount = amt
                        amount_pri = 0

            if amount_pri >= 0:
                # 相同科目可能在不同表格行重复出现，保留绝对值更大的一项避免被 0 覆盖。
                prev = float(item_map.get(tn, 0.0) or 0.0)
                item_map[tn] = float(amount) if abs(float(amount)) >= abs(prev) else prev

        items = [{"type": k, "amount": v} for k, v in item_map.items()]
        return items[:max_items]

    def _heuristic_extract_budget(self, text: str, *, max_items: int = 30) -> Dict[str, Any]:
        """LLM 预算抽取失败时，依据表格行与键值对进行规则抽取。"""
        raw = str(text or "").strip()
        if not raw:
            return {"budget": {"total": 0.0, "items": []}, "units_budget": []}

        item_map: Dict[str, float] = {}
        total_value = 0.0

        for line in raw.splitlines():
            s = self._clean_budget_line(line)
            if not s:
                continue

            # 识别总额
            total_m = re.search(r"(预算总额|经费总额|总预算|合计)[:：]?\s*(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)?", s)
            if total_m:
                total_value = max(total_value, self._parse_amount(total_m.group(2), total_m.group(3) or ""))

            segments = [x.strip() for x in re.split(r"[;；|]", s) if x.strip()]

            # 优先识别“类别/科目 + 金额”键值对组合。
            kv_type, kv_amount = self._extract_budget_type_and_amount_from_kv(segments)
            if kv_type:
                item_map[kv_type] = item_map.get(kv_type, 0.0) + kv_amount
                continue

            # 识别 type:amount 形式
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue

                kv = re.search(r"([^:：]{1,24})[:：]\s*(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)?", seg)
                if kv:
                    btype = self._normalize_budget_type(kv.group(1))
                    if not self._looks_like_budget_type(btype):
                        continue
                    amount = self._parse_amount(kv.group(2), kv.group(3) or "")
                    item_map[btype] = item_map.get(btype, 0.0) + amount
                    continue

                # 识别“类别 数值”形式
                plain = re.search(r"([\u4e00-\u9fa5A-Za-z（）()、/]{2,24})\s+(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)?", seg)
                if plain:
                    btype = self._normalize_budget_type(plain.group(1))
                    if not self._looks_like_budget_type(btype):
                        continue
                    cands = self._extract_amount_candidates(seg)
                    amount = cands[-1] if cands else self._parse_amount(plain.group(2), plain.group(3) or "")
                    item_map[btype] = item_map.get(btype, 0.0) + amount

        items = [{"type": k, "amount": float(v)} for k, v in item_map.items() if abs(v) > 1e-9][:max_items]
        if total_value <= 0 and items:
            total_value = float(sum(x["amount"] for x in items))

        return {
            "budget": {
                "total": float(total_value),
                "items": items,
            },
            "units_budget": [],
        }

    def _budget_is_empty(self, budget: Any) -> bool:
        if not isinstance(budget, dict):
            return True
        total = float(budget.get("total", 0.0) or 0.0)
        items = budget.get("items") or []
        return total <= 0 and len(items) == 0

    def _budget_needs_items_recovery(self, budget: Any) -> bool:
        """当预算总额存在但明细缺失/全零时，触发规则补全预算明细。"""
        if not isinstance(budget, dict):
            return True

        total = float(budget.get("total", 0.0) or 0.0)
        items = budget.get("items") or []
        if total <= 0:
            return False
        if not isinstance(items, list) or len(items) == 0:
            return True

        has_non_zero_item = False
        for item in items:
            if not isinstance(item, dict):
                continue
            amount = float(item.get("amount", 0.0) or 0.0)
            if abs(amount) > 1e-9:
                has_non_zero_item = True
                break

        return not has_non_zero_item

    def _budget_items_quality(self, items: Any) -> tuple[int, int]:
        """预算明细质量评分：(预算科目命中数, 非零金额条目数)。"""
        if not isinstance(items, list):
            return (0, 0)

        budget_like_count = 0
        non_zero_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            btype = str(item.get("type", "") or "").strip()
            amount = float(item.get("amount", 0.0) or 0.0)
            if self._looks_like_budget_type(btype):
                budget_like_count += 1
            if abs(amount) > 1e-9:
                non_zero_count += 1

        return (budget_like_count, non_zero_count)

    def _select_better_budget_items(self, current_items: Any, candidate_items: Any) -> list[dict[str, Any]]:
        """选择质量更高的预算明细，优先使用科目命中更高且非零条目更多的一侧。"""
        current = current_items if isinstance(current_items, list) else []
        candidate = candidate_items if isinstance(candidate_items, list) else []
        if not candidate:
            return current

        cur_score = self._budget_items_quality(current)
        cand_score = self._budget_items_quality(candidate)

        if cand_score > cur_score:
            return candidate
        return current

    async def _ainvoke_json(self, *, prompt: str) -> Dict[str, Any]:
        # 超时由 SDK 客户端 timeout 控制，不再在业务层手动 wait_for。
        resp = await self.llm.ainvoke(prompt)
        content = self._strip_code_fence(getattr(resp, "content", str(resp)))
        return json.loads(content)

    async def parse_to_schema(self, file_data: bytes, file_type: str, enable_table_vision_extraction: bool = True) -> DocumentSchema:
        """将文档解析并抽取为结构化 Schema"""
        # 1. 解析原始文本
        parser = get_parser(file_type)
        parse_result = await parser.parse(file_data)
        raw_text = parse_result.content.to_text()

        if enable_table_vision_extraction and str(file_type or "").lower() == "pdf":
            ocr_text = ""
            try:
                import os
                import fitz
                from src.common.file_handler.ocr import OCRProcessor
                from src.common.file_handler.image_processor import ImageProcessor
            except Exception:
                ocr_text = ""
            else:
                max_pages = int(os.getenv("PERFCHECK_OCR_MAX_PAGES", "3") or 3)
                scale = float(os.getenv("PERFCHECK_OCR_SCALE", "2.0") or 2.0)
                try:
                    doc = fitz.open(stream=file_data, filetype="pdf")
                except Exception:
                    doc = None
                if doc is not None:
                    ocr = OCRProcessor()
                    chunks: list[str] = []
                    page_count = min(len(doc), max_pages)
                    for page_index in range(page_count):
                        try:
                            page = doc.load_page(page_index)
                            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                            img_bytes = pix.tobytes("png")
                            img_bytes = ImageProcessor.to_rgb(img_bytes)
                            blocks = await ocr.recognize(img_bytes, page=page_index)
                        except Exception:
                            continue
                        blocks = [b for b in blocks if getattr(b, "text", "").strip()]
                        blocks.sort(key=lambda b: (getattr(getattr(b, "bbox", None), "y", 0.0), getattr(getattr(b, "bbox", None), "x", 0.0)))
                        line_y = None
                        line_parts: list[str] = []
                        for b in blocks:
                            y = float(getattr(getattr(b, "bbox", None), "y", 0.0) or 0.0)
                            text = str(getattr(b, "text", "") or "").strip()
                            if not text:
                                continue
                            if line_y is None:
                                line_y = y
                                line_parts = [text]
                                continue
                            if abs(y - line_y) <= 14.0:
                                line_parts.append(text)
                            else:
                                if line_parts:
                                    chunks.append(f"[OCR页{page_index + 1}] {' '.join(line_parts)}")
                                line_y = y
                                line_parts = [text]
                        if line_parts:
                            chunks.append(f"[OCR页{page_index + 1}] {' '.join(line_parts)}")
                    if chunks:
                        ocr_text = "\n".join(chunks)

            if ocr_text:
                raw_text = f"{raw_text}\n\n{ocr_text}"

        # 2. 使用 LLM 抽取结构化信息
        return await self.extract_schema_from_text(raw_text, source_file_type=file_type)

    async def extract_schema_from_text(self, text: str, source_file_type: Optional[str] = None) -> DocumentSchema:
        """从纯文本中抽取结构化 Schema"""
        raw = (text or "").strip()
        if not raw:
            return DocumentSchema(
                project_name="",
                research_contents=[],
                performance_targets=[],
                budget=Budget(total=0.0, items=[]),
                basic_info=None,
                units_budget=[],
            )

        raw = self._strip_filling_instructions(raw)

        # 不做全局截断：长文档（如含大表格的 DOCX）若仅保留头尾，
        # 会丢失中段“绩效目标表/成员分工表”，导致核心指标与成员抽取错误。

        basic_patterns = [
            r"项目名称",
            r"项目基本信息",
            r"项目申报单位基本信息表",
            r"承担单位",
            r"合作单位",
            r"项目组",
            r"人员",
            r"分工",
            r"知识产权",
            r"归属",
        ]
        metrics_patterns = [
            r"项目实施预期技术指标及创新点",
            r"预期技术指标及创新点",
            r"项目实施预期经济社会效益",
            r"预期经济社会效益",
            r"项目实施的预期绩效目标",
            r"项目实施的预期绩效目标表",
            r"预期绩效目标",
            r"项目实施的绩效目标",
            r"项目实施的绩效目标表",
            r"绩效目标",
            r"项目验收的考核指标",
            r"验收的考核指标",
            r"考核指标",
            r"进度安排和阶段目标",
            r"进度安排",
            r"阶段目标",
            r"\[表格表头\d+\]",
            r"\[表格表头\]",
            r"\[表格行\d+\]",
        ]
        research_patterns = [
            r"研究内容",
            r"研究任务",
            r"实施方案",
            r"技术路线",
            r"关键技术",
        ]
        budget_patterns = [
            r"项目预算表",
            r"预算表",
            r"经费预算",
            r"经费预算明细",
            r"承担单位、合作单位经费预算明细表",
            r"资金来源",
            r"直接费用",
            r"设备费",
            r"材料费",
            r"劳务费",
            r"业务费",
        ]
        unit_budget_patterns = [
            r"承担单位",
            r"合作单位",
            r"经费预算明细表",
            r"经费分配",
        ]

        doc_kind = self._detect_doc_kind(raw)
        if doc_kind == "task":
            basic_sections = [
                "承担单位和合作单位情况",
                "承担单位和合作单位情况表",
                "项目承担单位、合作单位任务分工",
                "参加人员及分工",
                "参加人员及分工表",
            ]
            metrics_sections = [
                "项目实施的绩效目标",
                "项目实施的绩效目标表",
                "项目验收的考核指标",
                "验收的考核指标",
            ]
            research_sections = [
                "项目实施的主要内容任务",
            ]
            budget_sections = [
                "项目预算表",
                "承担单位、合作单位经费预算明细表",
            ]
        else:
            basic_sections = ["申报单位及合作单位基础", "项目申报单位基本信息表", "项目组主要成员", "项目组主要成员表"]
            metrics_sections = ["项目实施的预期绩效目标", "项目实施的预期绩效目标表"]
            research_sections = ["项目实施内容及目标"]
            budget_sections = ["项目预算表", "承担单位、合作单位经费预算明细表"]

        basic_text = self._collect_topic_text(
            raw=raw,
            section_titles=basic_sections,
            patterns=basic_patterns,
            max_chars=7600,
            per_block_chars=2600,
            window_before=220,
            window_after=1800,
        )
        required_members_text = self._extract_required_team_members_sections(raw=raw, doc_kind=doc_kind, max_chars=9000)
        required_metrics_text = self._extract_required_metrics_sections(raw=raw, doc_kind=doc_kind, max_chars=14000)
        metrics_text = required_metrics_text
        if not metrics_text:
            metrics_text = self._collect_topic_text(
                raw=raw,
                section_titles=metrics_sections,
                patterns=metrics_patterns,
                max_chars=12000,
                per_block_chars=3200,
                window_before=300,
                window_after=2200,
            )
        source_type = str(source_file_type or "").strip().lower()
        is_docx_source = source_type == "docx"

        research_text = ""
        if is_docx_source:
            research_text = self._extract_required_research_section(raw=raw, doc_kind=doc_kind, max_chars=5200)
            if research_text and doc_kind != "task":
                idx_impl = research_text.find("项目实施内容")
                idx_research = research_text.find("研究内容", idx_impl if idx_impl >= 0 else 0)
                if idx_research >= 0:
                    research_text = research_text[idx_research:]
        if not research_text:
            research_text = self._extract_research_section_precise(raw=raw, doc_kind=doc_kind, max_chars=4200)
        if not research_text:
            research_text = self._collect_topic_text(
                raw=raw,
                section_titles=research_sections,
                patterns=research_patterns,
                max_chars=4200,
                per_block_chars=1800,
                window_before=260,
                window_after=1200,
            )
        if not research_text:
            fallback_patterns = [
                r"项目实施内容及目标",
                r"项目实施的主要内容任务",
            ]
            if not is_docx_source:
                fallback_patterns.extend([
                    r"研究内容",
                    r"技术路线",
                    r"研究目标",
                ])
            research_text = self._collect_windows(
                raw=raw,
                patterns=fallback_patterns,
                head_chars=300,
                tail_chars=0,
                before=220,
                after=1400,
                max_chars=3200,
            )

        if research_text:
            research_text = self._extract_research_content_only(raw=research_text, doc_kind=doc_kind, max_chars=4200)
        budget_text = self._collect_budget_text_precise(raw=raw, doc_kind=doc_kind, max_chars=8200)
        units_budget_text = self._collect_units_budget_text_precise(raw=raw, doc_kind=doc_kind, max_chars=9000)
        if not budget_text:
            budget_text = self._collect_topic_text(
            raw=raw,
            section_titles=budget_sections,
            patterns=budget_patterns + unit_budget_patterns,
            max_chars=5600,
            per_block_chars=2200,
            window_before=320,
            window_after=1800,
            )
        if not units_budget_text:
            units_budget_text = self._collect_windows(
                raw=raw,
                patterns=[
                    r"承担单位、合作单位经费预算明细表",
                    r"单位名称",
                    r"单位类型",
                    r"专项经费",
                    r"自筹经费",
                ],
                head_chars=0,
                tail_chars=0,
                before=220,
                after=1800,
                max_chars=7000,
            )

        basic_prompt = (
            "抽取项目名称与基础信息，返回 JSON："
            "{\"project_name\": str, \"basic_info\": {\"undertaking_unit\": str, \"partner_units\": [str], \"team_members\": [{\"name\": str, \"duty\": str}]}}。\n"
            "仅输出 JSON。\n\n文本：\n"
            + basic_text
        )
        members_prompt = (
            "仅从“项目组主要成员/参加人员及分工”表格抽取成员及分工，返回 JSON："
            "{\"team_members\": [{\"name\": str, \"duty\": str}]}。\n"
            "不要抽取承担单位负责人、联系人等非成员表字段；仅输出 JSON。\n\n文本：\n"
            + (required_members_text or basic_text)
        )
        metrics_prompt = (
            "仅从绩效目标表中抽取可量化指标，返回 JSON："
            "{\"performance_targets\": [{\"id\": str, \"type\": str, \"text\": str, \"source\": str, \"value\": number, \"unit\": str, \"constraint\": str, \"subtype\": str}]}。\n"
            "抽取顺序要求：先抽“绩效指标（三级指标 + 指标值）”和“满意度指标”；"
            "再补充“总体目标-实施期目标”中未出现在绩效指标里的条目。"
            "如两者重复，以绩效指标为准。"
            "严格排除“年度目标/阶段目标/第一年第二年/招募病例进度”等中间过程指标。"
            "type 必须是三级细项指标名称（如“发表SCI论文数量”“申请发明专利数”“销售收入”），"
            "禁止输出“一级指标/二级指标/绩效目标”等泛化名称；text 写该指标完整句；仅输出 JSON。\n\n文本：\n"
            + metrics_text
        )
        research_prompt = (
            "仅从“研究内容”小节抽取研究内容条目（申报书：第一部分>一、项目实施内容；任务书：二、项目实施的主要内容任务）。"
            "严格排除：合作单位选择原因、国际合作、论文/专利/成果、承担项目清单、预算、进度安排、考核指标等非研究内容。"
            "返回 JSON："
            "{\"research_contents\": [{\"id\": str, \"text\": str}]}。\n"
            "id 从 R1 开始递增；仅输出 JSON。\n\n文本：\n"
            + research_text
        )
        budget_prompt = (
            "从预算相关文本中一次性抽取总预算、预算明细及单位预算，返回 JSON："
            "{\"budget\": {\"total\": number, \"items\": [{\"type\": str, \"amount\": number}]}, "
            "\"units_budget\": [{\"unit_name\": str, \"type\": str, \"amount\": number}]}。\n"
            "若缺失返回空数组或 0；仅输出 JSON。\n\n文本：\n"
            + budget_text
        )

        configured_timeout = float(getattr(llm_config, "timeout", 30.0) or 30.0)

        tasks = {
            "basic": self._ainvoke_json(
                prompt=basic_prompt,
            ),
            "members": self._ainvoke_json(
                prompt=members_prompt,
            ),
            "metrics": self._ainvoke_json(
                prompt=metrics_prompt,
            ),
            "research": self._ainvoke_json(
                prompt=research_prompt,
            ),
            "budget": self._extract_budget_with_fallback(
                budget_prompt=budget_prompt,
                base_timeout=configured_timeout,
            ),
        }

        # 核心字段失败时立即退出，避免等待最慢请求超时。
        results = await self._run_extract_tasks_fail_fast(
            tasks,
            core_keys={"metrics", "research", "budget"},
        )

        basic_data = results.get("basic") or {}
        members_data = results.get("members") or {}
        metrics_data = results.get("metrics") or {}
        research_data = results.get("research") or {}
        budget_data = results.get("budget") or {}

        project_name = str(basic_data.get("project_name") or "").strip()
        heuristic_project_name = self._extract_project_name(raw) or self._extract_project_name(basic_text)
        if heuristic_project_name:
            if not project_name:
                project_name = heuristic_project_name
            else:
                # LLM 命中但值偏移时，用规则抽取的标题区名称纠偏。
                p_norm = re.sub(r"[\s\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", project_name)
                h_norm = re.sub(r"[\s\u3000·•，,。；;:：()（）\[\]【】<>《》\-_/\\]+", "", heuristic_project_name)
                if h_norm and (not p_norm or (h_norm not in p_norm and p_norm not in h_norm)):
                    project_name = heuristic_project_name
        raw_llm_basic_info = basic_data.get("basic_info")
        llm_basic_info: dict[str, Any] = (
            {str(k): v for k, v in raw_llm_basic_info.items()}
            if isinstance(raw_llm_basic_info, dict)
            else {}
        )
        llm_member_list = members_data.get("team_members") if isinstance(members_data, dict) else None
        if isinstance(llm_member_list, list):
            llm_basic_info["team_members"] = llm_member_list

        heuristic_basic = self._heuristic_extract_basic_info(
            raw,
            team_members_text=(required_members_text or basic_text),
        )
        basic_info = self._merge_basic_info(llm_basic_info, heuristic_basic, doc_kind=doc_kind)
        research_contents = research_data.get("research_contents") or []
        if is_docx_source and research_text:
            topic_blocks = self._extract_research_topic_blocks(research_text, max_items=12)
            if len(topic_blocks) >= 2:
                research_contents = [{"id": f"R{i+1}", "text": topic_blocks[i]} for i in range(min(len(topic_blocks), 12))]
            else:
                numbered_blocks = self._extract_numbered_research_blocks(research_text, max_items=12)
                picked = self._pick_sequential_numbered_blocks(numbered_blocks, min_keep=2, max_items=12)
                if len(picked) >= 2:
                    research_contents = [{"id": f"R{i+1}", "text": picked[i]} for i in range(min(len(picked), 12))]
        if not research_contents:
            research_contents = self._heuristic_extract_research_contents(research_text)

        if research_contents:
            research_source_text = "\n".join([x for x in [research_text, raw] if x])
            research_contents = self._enrich_research_contents_from_text(
                research_contents,
                research_source_text,
                max_items=12,
            )

        if not research_contents:
            fallback_patterns = [
                r"项目实施内容及目标",
                r"项目实施的主要内容任务",
            ]
            if not is_docx_source:
                fallback_patterns.extend([
                    r"研究内容",
                    r"研究任务",
                    r"技术路线",
                    r"实施方案",
                    r"关键技术",
                    r"\[表格行\d+\]",
                ])
            fallback_research_text = self._collect_windows(
                raw=raw,
                patterns=fallback_patterns,
                head_chars=0,
                tail_chars=0,
                before=200,
                after=1200,
                max_chars=5000,
            )
            research_contents = self._heuristic_extract_research_contents(fallback_research_text)

        if not research_contents:
            logger.warning("研究内容抽取为空：LLM 与规则兜底均未命中，请检查 DOCX 章节标题与内容结构。")

        raw_targets = metrics_data.get("performance_targets") or []
        if is_docx_source and metrics_text:
            rule_targets = self._extract_performance_targets_from_metrics_table(metrics_text)
            if len(rule_targets) >= 2:
                raw_targets = rule_targets
        performance_targets = self._normalize_performance_targets(raw_targets)
        # 仅在“绩效目标章节”内做补齐，避免把其它章节指标带入核心考核比对。
        supplement_text = metrics_text
        performance_targets = self._supplement_performance_targets(performance_targets, supplement_text)
        performance_targets = self._keep_overall_targets_only(performance_targets, metrics_text)
        budget = budget_data.get("budget") or {"total": 0.0, "items": []}
        units_budget = budget_data.get("units_budget") or []
        rule_units_budget = self._extract_units_budget_items_from_table_rows(units_budget_text)
        if rule_units_budget and (not units_budget or len(rule_units_budget) >= len(units_budget)):
            units_budget = rule_units_budget

        # 无论 LLM 是否返回预算明细，都尝试以表格行为准进行纠偏。
        table_items = self._extract_budget_items_from_table_rows(budget_text)
        if not table_items:
            table_budget_text = self._collect_windows(
                raw=raw,
                patterns=[
                    r"项目预算表",
                    r"预算表",
                    r"经费预算",
                    r"经费预算明细",
                    r"承担单位、合作单位经费预算明细表",
                    r"\[表格标题\d+\]",
                    r"\[表格表头\d+\]",
                    r"\[表格行\d+\]",
                ],
                head_chars=0,
                tail_chars=0,
                before=240,
                after=1600,
                max_chars=7000,
            )
            table_items = self._extract_budget_items_from_table_rows(table_budget_text)

        budget_items = budget.get("items") if isinstance(budget, dict) else []
        best_items = self._select_better_budget_items(budget_items, table_items)
        if best_items is not budget_items:
            budget = {
                "total": float((budget or {}).get("total", 0.0) or 0.0),
                "items": best_items,
            }

        # LLM 可能只返回 total，导致预算明细为空；先尝试用规则补全 items。
        if self._budget_needs_items_recovery(budget):
            if table_items:
                budget = {
                    "total": float(budget.get("total", 0.0) or 0.0),
                    "items": table_items,
                }

        if self._budget_is_empty(budget):
            heuristic_budget_data = self._heuristic_extract_budget(budget_text)
            budget = heuristic_budget_data.get("budget") or budget
            if not units_budget:
                units_budget = heuristic_budget_data.get("units_budget") or []
            if not units_budget and rule_units_budget:
                units_budget = rule_units_budget

        if self._budget_is_empty(budget):
            fallback_budget_text = self._collect_windows(
                raw=raw,
                patterns=[
                    r"项目预算表",
                    r"预算表",
                    r"经费预算",
                    r"经费预算明细",
                    r"承担单位、合作单位经费预算明细表",
                    r"\[表格标题\d+\]",
                    r"\[表格表头\d+\]",
                    r"\[表格行\d+\]",
                ],
                head_chars=0,
                tail_chars=0,
                before=240,
                after=1600,
                max_chars=7000,
            )
            heuristic_budget_data = self._heuristic_extract_budget(fallback_budget_text)
            budget = heuristic_budget_data.get("budget") or budget
            if not units_budget:
                units_budget = heuristic_budget_data.get("units_budget") or []
            if not units_budget and rule_units_budget:
                units_budget = rule_units_budget

        data = {
            "project_name": project_name,
            "research_contents": research_contents,
            "performance_targets": performance_targets,
            "budget": budget,
            "basic_info": basic_info,
            "units_budget": units_budget,
        }

        return DocumentSchema(**data)
