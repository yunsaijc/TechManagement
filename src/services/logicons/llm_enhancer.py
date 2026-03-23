"""LogiCons LLM 增强器

在规则引擎基础上，利用大模型做跨段落语义冲突补漏。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, List

from src.common.llm import get_default_llm_client
from src.common.models.logicons import (
    ConflictCategory,
    ConflictItem,
    ConflictSeverity,
    DocSpan,
)


class LogiConsLLMEnhancer:
    """使用大模型补充逻辑冲突检测。"""

    _FOCUS_INSTRUCTION = {
        "timeline": "重点检查执行期、进度节点、里程碑是否跨期或前后矛盾。",
        "budget": "重点检查资金总额、明细合计、年度预算、来源拆分是否算不平。",
        "indicator": "重点检查总体指标与分阶段指标是否相互矛盾或口径冲突。",
        "semantic": "重点检查关键叙述是否前后否定、角色/单位/配置是否冲突。",
    }

    def __init__(self):
        self._llm = None
        self.last_status = "idle"
        self.last_message = ""

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_default_llm_client()
        return self._llm

    async def find_additional_conflicts(
        self,
        *,
        text: str,
        existing_conflicts: List[ConflictItem],
        timeout_seconds: float = 70.0,
    ) -> List[ConflictItem]:
        """调用 LLM 对全文做补充冲突检测。"""
        self.last_status = "running"
        self.last_message = ""

        try:
            llm = self._get_llm()
        except Exception as e:
            self.last_status = "error"
            self.last_message = f"LLM 客户端初始化失败: {str(e)}"
            return []

        # 轻量探针：用于确认链路是否真实调用到 LLM。
        probe_ok = False
        try:
            probe_resp = await asyncio.wait_for(llm.ainvoke("请仅回复：ok"), timeout=min(12.0, timeout_seconds))
            probe_text = self._extract_text(probe_resp)
            probe_ok = bool((probe_text or "").strip())
        except Exception:
            probe_ok = False

        existing = [
            {
                "rule_code": c.rule_code,
                "category": c.category.value,
                "severity": c.severity.value,
                "message": c.message,
            }
            for c in existing_conflicts
        ]

        chunks = self._chunk_text(text, max_chars=1000, overlap_chars=160, max_chunks=2)
        if not chunks:
            self.last_status = "no_new"
            self.last_message = "输入文本为空，未执行 LLM 增强。"
            return []

        semaphore = asyncio.Semaphore(2)
        per_call_timeout = max(20.0, min(45.0, timeout_seconds - 10.0))

        async def _run_one(focus: str, chunk: dict[str, Any]) -> dict[str, Any]:
            prompt = self._build_prompt(
                text=chunk["text"],
                text_location=chunk["location"],
                focus=focus,
                existing=existing,
            )
            try:
                async with semaphore:
                    resp = await asyncio.wait_for(llm.ainvoke(prompt), timeout=per_call_timeout)
            except Exception:
                return {"called": False, "parsed": False, "conflicts": []}

            raw = self._extract_text(resp)
            called = bool((raw or "").strip())
            payload = self._try_parse_json(raw)
            if not payload:
                return {"called": called, "parsed": False, "conflicts": []}

            conflicts: List[ConflictItem] = []
            for item in payload.get("additional_conflicts", []):
                conflict = self._to_conflict(item, default_location=chunk["location"])
                if conflict is None:
                    continue
                conflicts.append(conflict)
            return {"called": called, "parsed": True, "conflicts": conflicts}

        tasks = [
            _run_one(focus, chunk)
            for focus in ("timeline", "budget", "indicator")
            for chunk in chunks
        ]

        try:
            batches = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
        except Exception as e:
            if probe_ok:
                self.last_status = "no_new"
                self.last_message = "LLM 已调用成功，但增强阶段超时，未产生新增冲突。"
                return []
            self.last_status = "error"
            self.last_message = f"LLM 增强超时或调用失败: {type(e).__name__}"
            return []

        additional: List[ConflictItem] = []
        called_batches = 0
        parsed_batches = 0
        for batch in batches:
            if batch.get("called"):
                called_batches += 1
            if batch.get("parsed"):
                parsed_batches += 1
            additional.extend(batch.get("conflicts", []))

        additional = self._deduplicate_conflicts(additional, existing_conflicts)

        if additional:
            self.last_status = "ok"
            self.last_message = f"LLM 增强新增冲突 {len(additional)} 条"
            return additional

        if called_batches == 0 and probe_ok:
            self.last_status = "no_new"
            self.last_message = "LLM 已调用成功，但增强请求超时或无有效返回。"
            return []

        if called_batches == 0:
            self.last_status = "error"
            self.last_message = "LLM 增强未返回可解析结果，请检查模型配置或接口可用性。"
            return []

        if parsed_batches == 0:
            self.last_status = "no_new"
            self.last_message = "LLM 已调用成功，但返回内容不是可解析 JSON；建议收紧提示词或启用结构化输出。"
            return []

        self.last_status = "no_new"
        self.last_message = "LLM 增强未发现新增冲突"
        return []

    def _build_prompt(
        self,
        *,
        text: str,
        text_location: str,
        focus: str,
        existing: list[dict[str, Any]],
    ) -> str:
        focus_hint = self._FOCUS_INSTRUCTION.get(focus, "请从全局一致性角度发现冲突。")

        return (
            "你是科技项目文档逻辑一致性审计专家。\n"
            f"本轮检测焦点: {focus_hint}\n"
            "请只基于给定文本片段输出新增冲突。\n"
            "要求：\n"
            "1. 只输出 JSON，不要输出其他内容。\n"
            "2. 不要重复 existing_conflicts。\n"
            "3. 每条冲突必须给证据原文。\n"
            "4. 若无新增冲突，输出 {\"additional_conflicts\": []}。\n\n"
            "输出格式：\n"
            "{\n"
            "  \"additional_conflicts\": [\n"
            "    {\n"
            "      \"rule_code\": \"L-T001\",\n"
            "      \"category\": \"timeline|budget|indicator|semantic\",\n"
            "      \"severity\": \"high|medium|low\",\n"
            "      \"message\": \"冲突描述\",\n"
            "      \"suggestion\": \"修正建议\",\n"
            "      \"evidences\": [\n"
            "        {\"section\": \"章节\", \"location\": \"line:xx\", \"quote\": \"证据原文\"}\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"existing_conflicts={json.dumps(existing, ensure_ascii=False)}\n"
            f"chunk_location={text_location}\n"
            f"chunk_text={json.dumps(text, ensure_ascii=False)}"
        )

    def _chunk_text(
        self,
        text: str,
        *,
        max_chars: int,
        overlap_chars: int,
        max_chunks: int,
    ) -> list[dict[str, Any]]:
        clean = (text or "").strip()
        if not clean:
            return []

        clean = re.sub(r"\r\n?", "\n", clean)
        chunks: list[dict[str, Any]] = []
        start = 0
        idx = 1
        n = len(clean)

        while start < n and len(chunks) < max_chunks:
            end = min(n, start + max_chars)
            piece = clean[start:end]
            chunks.append({"location": f"char:{start}-{end}", "text": piece})
            if end >= n:
                break
            start = max(0, end - overlap_chars)
            idx += 1

        return chunks

    def _deduplicate_conflicts(
        self,
        candidates: List[ConflictItem],
        existing_conflicts: List[ConflictItem],
    ) -> List[ConflictItem]:
        seen = {(c.rule_code, c.message.strip()) for c in existing_conflicts}
        out: List[ConflictItem] = []
        for c in candidates:
            key = (c.rule_code, c.message.strip())
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out

    def _extract_text(self, resp: Any) -> str:
        if isinstance(resp, str):
            return resp
        content = getattr(resp, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for chunk in content:
                if isinstance(chunk, dict):
                    value = chunk.get("text")
                    if value:
                        parts.append(str(value))
                else:
                    parts.append(str(chunk))
            return "\n".join(parts)
        return str(resp)

    def _try_parse_json(self, text: str) -> dict[str, Any] | None:
        text = (text or "").strip()
        if not text:
            return None

        try:
            return json.loads(text)
        except Exception:
            pass

        # 兼容 markdown code fence 输出
        if "```" in text:
            chunks = text.split("```")
            for chunk in chunks:
                candidate = chunk.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if not candidate:
                    continue
                try:
                    return json.loads(candidate)
                except Exception:
                    continue

        return None

    def _to_conflict(self, item: dict[str, Any], default_location: str) -> ConflictItem | None:
        try:
            category = ConflictCategory(item.get("category", "semantic"))
            severity = ConflictSeverity(item.get("severity", "medium"))
        except Exception:
            return None

        evidences: List[DocSpan] = []
        for ev in item.get("evidences", []):
            section = str(ev.get("section", "未知章节")).strip() or "未知章节"
            location = str(ev.get("location", default_location)).strip() or default_location
            quote = str(ev.get("quote", "")).strip()
            if not quote:
                continue
            evidences.append(DocSpan(section=section, location=location, quote=quote))

        return ConflictItem(
            conflict_id="",
            rule_code=str(item.get("rule_code", "L-SEM-001")),
            category=category,
            severity=severity,
            message=str(item.get("message", "检测到潜在语义冲突")),
            suggestion=str(item.get("suggestion", "请核对相关章节口径并修正文案。")),
            evidences=evidences,
        )
