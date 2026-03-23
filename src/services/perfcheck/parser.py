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
    "项目承担单位、合作单位任务分工、知识产权归属",
    "参加人员及分工",
    "参加人员及分工表",
    "项目实施的绩效目标",
    "项目实施的绩效目标表",
    "项目预算表",
    "承担单位、合作单位经费预算明细表",
]

PERFCHECK_EXTRACT_PROMPT = """你是项目核验抽取器，请把输入文本转换为 JSON。

硬性要求：
1) 只输出 JSON，不要 Markdown、解释或注释。
2) 字段固定如下：
     - project_name: str
     - research_contents: [{id, text}]
     - performance_targets: [{id, type, subtype, text, source, value, unit, constraint}]
     - budget: {total, items:[{type, amount}]}
     - basic_info: {undertaking_unit, partner_units:[str], team_members:[{name, duty}], ip_ownership}
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
        "team_members": [],
        "ip_ownership": ""
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
            if not text:
                item["text"] = item["type"]
            normalized.append(item)
        return normalized

    async def _ainvoke_json(self, *, prompt: str) -> Dict[str, Any]:
        # 超时由 SDK 客户端 timeout 控制，不再在业务层手动 wait_for。
        resp = await self.llm.ainvoke(prompt)
        content = self._strip_code_fence(getattr(resp, "content", str(resp)))
        return json.loads(content)

    async def parse_to_schema(self, file_data: bytes, file_type: str) -> DocumentSchema:
        """将文档解析并抽取为结构化 Schema"""
        # 1. 解析原始文本
        parser = get_parser(file_type)
        parse_result = await parser.parse(file_data)
        raw_text = parse_result.content.to_text()

        # 2. 使用 LLM 抽取结构化信息
        return await self.extract_schema_from_text(raw_text)

    async def extract_schema_from_text(self, text: str) -> DocumentSchema:
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

        if len(raw) > 30000:
            head = raw[: len(raw) // 3]
            tail = raw[-(len(raw) // 4) :]
            raw = f"{head}\n\n[TRUNCATED]\n\n{tail}"

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
            r"\[表格表头\d+\]",
            r"\[表格表头\]",
            r"\[表格行\d+\]",
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
                "项目承担单位、合作单位任务分工、知识产权归属",
                "参加人员及分工",
                "参加人员及分工表",
            ]
            metrics_sections = [
                "项目验收的考核指标",
                "项目实施的绩效目标",
                "项目实施的绩效目标表",
                "进度安排和阶段目标",
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
            metrics_sections = ["项目实施内容及目标", "项目实施的预期绩效目标表"]
            research_sections = ["项目实施内容及目标"]
            budget_sections = ["项目预算表", "承担单位、合作单位经费预算明细表"]

        basic_text = self._collect_topic_text(
            raw=raw,
            section_titles=basic_sections,
            patterns=basic_patterns,
            max_chars=3600,
            per_block_chars=1300,
            window_before=220,
            window_after=900,
        )
        metrics_text = self._collect_topic_text(
            raw=raw,
            section_titles=metrics_sections,
            patterns=metrics_patterns,
            max_chars=7600,
            per_block_chars=2300,
            window_before=300,
            window_after=1500,
        )
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
            research_text = self._collect_windows(
                raw=raw,
                patterns=[
                    r"项目实施内容及目标",
                    r"项目实施的主要内容任务",
                    r"研究内容",
                    r"技术路线",
                    r"研究目标",
                ],
                head_chars=300,
                tail_chars=0,
                before=220,
                after=1400,
                max_chars=3200,
            )
        budget_text = self._collect_topic_text(
            raw=raw,
            section_titles=budget_sections,
            patterns=budget_patterns + unit_budget_patterns,
            max_chars=5600,
            per_block_chars=2200,
            window_before=320,
            window_after=1800,
        )

        basic_prompt = (
            "抽取项目名称与基础信息，返回 JSON："
            "{\"project_name\": str, \"basic_info\": {\"undertaking_unit\": str, \"partner_units\": [str], \"team_members\": [{\"name\": str, \"duty\": str}], \"ip_ownership\": str}}。\n"
            "仅输出 JSON。\n\n文本：\n"
            + basic_text
        )
        metrics_prompt = (
            "抽取核心考核指标（绩效目标/验收考核/阶段目标/技术指标），返回 JSON："
            "{\"performance_targets\": [{\"id\": str, \"type\": str, \"text\": str, \"source\": str, \"value\": number, \"unit\": str, \"constraint\": str, \"subtype\": str}]}。\n"
            "仅保留可量化指标；id 从 P1 递增。type 必须是三级细项指标名称（如“发表SCI论文数量”“申请发明专利数”“销售收入”），"
            "禁止输出“一级指标/二级指标/绩效目标”等泛化名称；text 写该指标完整句；仅输出 JSON。\n\n文本：\n"
            + metrics_text
        )
        research_prompt = (
            "仅从申报书\"一、项目实施内容及目标\"或任务书\"二、项目实施的主要内容任务\"抽取研究内容条目，返回 JSON："
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
            "metrics": self._ainvoke_json(
                prompt=metrics_prompt,
            ),
            "research": self._ainvoke_json(
                prompt=research_prompt,
            ),
            "budget": self._ainvoke_json(
                prompt=budget_prompt,
            ),
        }

        # 预算字段采用“主路径 + 回退”以提高成功率，降低核心字段失败概率。
        tasks["budget"] = self._extract_budget_with_fallback(
            budget_prompt=budget_prompt,
            base_timeout=configured_timeout,
        )

        # 核心字段失败时立即退出，避免等待最慢请求超时。
        results = await self._run_extract_tasks_fail_fast(
            tasks,
            core_keys={"metrics", "research", "budget"},
        )

        basic_data = results.get("basic") or {}
        metrics_data = results.get("metrics") or {}
        research_data = results.get("research") or {}
        budget_data = results.get("budget") or {}

        project_name = str(basic_data.get("project_name") or "").strip()
        basic_info = basic_data.get("basic_info")
        research_contents = research_data.get("research_contents") or []
        performance_targets = self._normalize_performance_targets(
            metrics_data.get("performance_targets") or []
        )
        budget = budget_data.get("budget") or {"total": 0.0, "items": []}
        units_budget = budget_data.get("units_budget") or []

        data = {
            "project_name": project_name,
            "research_contents": research_contents,
            "performance_targets": performance_targets,
            "budget": budget,
            "basic_info": basic_info,
            "units_budget": units_budget,
        }

        return DocumentSchema(**data)
