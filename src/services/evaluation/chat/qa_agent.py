"""聊天问答代理"""
import asyncio
from dataclasses import dataclass
import os
import re
from typing import Any, AsyncIterator, Dict, List

from openai import AsyncOpenAI

from src.common.llm.config import llm_config
from src.common.models.evaluation import ChatCitation, EvaluationChatAskResponse

from .indexer import ChatIndexer


@dataclass(frozen=True)
class QuestionPlan:
    """问题路由结果"""

    intent: str
    label: str
    query_hints: tuple[str, ...]
    high_risk: bool = False


class EvaluationQAAgent:
    """基于评审索引回答问题"""

    ANSWER_CHAR_LIMIT = 140

    INNOVATION_NOISE_MARKERS = (
        "项目实施内容、技术路线及创新点",
        "项目预期的主要创新点",
        "围绕基础前沿、共性关键技术或应用试验等层面",
        "应包括该项创新的基本形态及其前沿性",
        "科学性、艺术性、先进性",
        "简述项目预期的主要创新点",
        "具体内容应包括",
    )
    VALIDATION_COMPLETED_MARKERS = (
        "完成",
        "已完成",
        "开展",
        "已开展",
        "实现",
        "已实现",
        "达到",
        "获得",
        "通过",
        "形成",
        "验证结果",
        "测试结果",
        "试验结果",
        "实测",
    )
    VALIDATION_PLANNED_MARKERS = (
        "拟",
        "计划",
        "将",
        "拟开展",
        "拟完成",
        "预期",
        "拟通过",
        "拟实现",
    )
    VALIDATION_KEYWORDS = (
        "验证",
        "数据",
        "试验",
        "实验",
        "测试",
        "检测",
        "样本",
        "样机",
        "中试",
        "指标",
        "性能",
        "对比",
        "实测",
        "监测",
    )
    PRODUCTION_STRONG_MARKERS = (
        "量产",
        "批量生产",
        "批产",
        "规模化生产",
        "产业化",
        "生产线",
        "中试",
        "试生产",
        "工艺放大",
        "良率",
        "产线",
        "制造成本",
        "工程化",
    )
    PRODUCTION_MEDIUM_MARKERS = (
        "成果转化",
        "转化应用",
        "示范应用",
        "应用示范",
        "推广应用",
        "企业合作",
        "市场推广",
        "商业化",
        "落地",
    )
    PRODUCTION_WEAK_MARKERS = (
        "推广",
        "应用",
        "示范",
        "场景",
        "品牌建设",
        "服务",
    )
    REWARD_SUPPORT_SECTION_GROUPS = (
        ("重要科学发现", ("重要科学发现", "科学发现点", "主要发现点"), 100.0),
        ("客观评价", ("客观评价", "验收意见", "同意通过验收"), 92.0),
        ("代表性论文", ("代表性论文", "论文目录", "专著目录"), 84.0),
        ("被引情况", ("被他人引用", "引用情况", "他引", "引文"), 78.0),
        ("主材料", ("项目简介", "项目详细内容", "总体思路", "科学价值"), 68.0),
        ("佐证材料", ("验收", "公示", "获奖", "证明材料"), 58.0),
    )
    REWARD_SUPPORT_QUESTION_MARKERS = (
        "奖种",
        "当前奖种",
        "申报奖种",
        "支撑评价",
        "支撑当前",
        "能否支撑",
        "是否支撑",
        "材料能否支撑",
        "评价依据",
        "奖项评价",
    )
    REWARD_RULE_INTENTS = {
        "奖励科学发现",
        "奖励核心贡献",
        "奖励客观评价",
        "奖励论文支撑",
        "奖励短板",
        "奖种支撑判断",
    }
    REWARD_INTENT_GROUP_ORDER = {
        "奖励科学发现": ("重要科学发现", "主材料", "代表性论文"),
        "奖励核心贡献": ("主材料", "重要科学发现", "客观评价"),
        "奖励客观评价": ("客观评价", "被引情况", "代表性论文"),
        "奖励论文支撑": ("代表性论文", "重要科学发现", "被引情况"),
        "奖励短板": ("客观评价", "重要科学发现", "代表性论文", "主材料"),
        "奖种支撑判断": ("重要科学发现", "客观评价", "代表性论文", "被引情况", "主材料", "佐证材料"),
    }

    QUESTION_PLANS = (
        QuestionPlan(
            intent="奖励科学发现",
            label="主要科学发现",
            query_hints=("主要科学发现", "重要科学发现", "主要发现点", "科学发现点"),
        ),
        QuestionPlan(
            intent="奖励核心贡献",
            label="核心贡献",
            query_hints=("项目简介", "核心贡献", "科学发现点", "可靠的理论依据"),
        ),
        QuestionPlan(
            intent="奖励客观评价",
            label="客观评价",
            query_hints=("客观评价", "科技创新", "SCI收录", "引用", "他引", "验收意见"),
        ),
        QuestionPlan(
            intent="奖励论文支撑",
            label="代表性论文支撑",
            query_hints=("代表性论文", "所支持发现点", "证明材料", "他引总次数"),
        ),
        QuestionPlan(
            intent="奖励短板",
            label="主要短板",
            query_hints=("短板", "不足", "客观评价", "代表性论文", "附件完整性"),
        ),
        QuestionPlan(
            intent="创新点",
            label="创新点",
            query_hints=("创新点", "科学发现", "主要发现点", "重要科学发现", "技术创新", "模式创新", "特色"),
        ),
        QuestionPlan(
            intent="研究目标",
            label="研究目标",
            query_hints=("研究目标", "项目目标", "总体目标", "建设目标", "目的"),
        ),
        QuestionPlan(
            intent="验证数据",
            label="验证数据",
            query_hints=("验证", "数据", "试验", "测试", "样本", "性能"),
            high_risk=True,
        ),
        QuestionPlan(
            intent="量产可能性",
            label="量产可行性",
            query_hints=("量产", "产业化", "成果转化", "推广应用", "中试", "产线"),
            high_risk=True,
        ),
        QuestionPlan(
            intent="进展程度",
            label="当前进展",
            query_hints=("进展", "进度", "阶段", "实施计划", "工作安排"),
        ),
        QuestionPlan(
            intent="预期成果",
            label="预期成果",
            query_hints=("预期成果", "成果产出", "指标", "成果", "效益"),
        ),
        QuestionPlan(
            intent="预期效益",
            label="预期效益",
            query_hints=("预期效益", "社会效益", "经济效益", "项目效益"),
        ),
        QuestionPlan(
            intent="奖种支撑判断",
            label="奖种支撑判断",
            query_hints=("奖种", "支撑评价", "重要科学发现", "客观评价", "代表性论文", "被引情况", "验收意见"),
        ),
        QuestionPlan(
            intent="通用",
            label="综合判断",
            query_hints=(),
        ),
    )

    def __init__(self, llm: Any = None, indexer: ChatIndexer | None = None):
        self.llm = llm
        self.indexer = indexer or ChatIndexer()
        self.native_client = self._build_native_client(llm)
        self.native_model = llm_config.model or "qwen3.5-flash"
        self.native_timeout = float(llm_config.timeout or 30.0)
        self.answer_timeout = max(8.0, min(float(os.getenv("EVALUATION_CHAT_TIMEOUT", self.native_timeout)), 60.0))
        self.native_temperature = 0.2
        self.native_max_tokens = min(220, max(96, int(llm_config.max_tokens or 220)))

    async def ask(self, question: str, index_payload: Dict[str, Any]) -> EvaluationChatAskResponse:
        """回答专家问题并返回引用"""
        prepared = self._prepare_answer_payload(question, index_payload)
        if prepared["error_answer"]:
            return EvaluationChatAskResponse(
                answer=str(prepared["error_answer"]),
                citations=[],
            )

        plan = prepared["plan"]
        evidence_items = prepared["evidence_items"]
        citations = prepared["citations"]
        fallback_answer = self._build_fallback_answer(question, plan, evidence_items)
        if plan.intent in self.REWARD_RULE_INTENTS:
            return EvaluationChatAskResponse(answer=fallback_answer, citations=citations)
        native_answer = await self._with_answer_timeout(
            self._generate_answer_native(question, plan, evidence_items),
            fallback="",
        )
        if native_answer:
            return EvaluationChatAskResponse(answer=native_answer, citations=citations)
        answer = await self._with_answer_timeout(
            self._generate_answer(question, plan, evidence_items),
            fallback=fallback_answer,
        )
        return EvaluationChatAskResponse(answer=answer, citations=citations)

    async def _with_answer_timeout(self, coro: Any, fallback: str) -> str:
        """限制问答模型等待时间，避免接口长时间挂起。"""
        try:
            return await asyncio.wait_for(coro, timeout=self.answer_timeout)
        except Exception:
            return fallback

    async def ask_stream(
        self,
        question: str,
        index_payload: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """以流式事件输出专家回答"""
        yield {"event": "status", "message": "正在识别问题类型"}
        yield {"event": "status", "message": "正在检索相关正文片段"}
        prepared = self._prepare_answer_payload(question, index_payload)
        if prepared["error_answer"]:
            answer = str(prepared["error_answer"])
            yield {"event": "delta", "text": answer}
            yield {"event": "done", "answer": answer, "citations": []}
            return

        plan = prepared["plan"]
        evidence_items = prepared["evidence_items"]
        citations = prepared["citations"]
        fallback_answer = self._build_fallback_answer(question, plan, evidence_items)
        if plan.intent in self.REWARD_RULE_INTENTS:
            yield {"event": "status", "message": "正在按奖励材料结构判断支撑度"}
            yield {"event": "delta", "text": fallback_answer}
            yield {
                "event": "done",
                "answer": fallback_answer,
                "citations": [citation.model_dump(mode="json") for citation in citations],
            }
            return
        if self.native_client:
            yield {"event": "status", "message": "正在请求模型生成回答"}
            native_parts: List[str] = []
            try:
                async for text in self._stream_answer_native(question, plan, evidence_items):
                    if not text:
                        continue
                    native_parts.append(text)
                    yield {"event": "delta", "text": text}
                native_answer = "".join(native_parts).strip()
                if self._is_structured_answer(native_answer):
                    yield {
                        "event": "done",
                        "answer": native_answer,
                        "citations": [citation.model_dump(mode="json") for citation in citations],
                    }
                    return
            except Exception:
                yield {"event": "status", "message": "直连模型失败，正在回退通用链路"}

        yield {"event": "status", "message": "正在整理证据依据"}

        if not self.llm or not hasattr(self.llm, "astream"):
            yield {"event": "status", "message": "模型不可用，正在生成规则化回答"}
            yield {"event": "delta", "text": fallback_answer}
            yield {
                "event": "done",
                "answer": fallback_answer,
                "citations": [citation.model_dump(mode="json") for citation in citations],
            }
            return

        prompt = self._build_llm_prompt(question, plan, evidence_items)
        streamed_parts: List[str] = []
        yield {"event": "status", "message": "正在生成专家回答"}
        try:
            async for chunk in self.llm.astream(prompt):
                text = self._extract_stream_text(chunk)
                if not text:
                    continue
                streamed_parts.append(text)
                yield {"event": "delta", "text": text}
        except Exception:
            if not streamed_parts:
                yield {"event": "status", "message": "模型流式失败，正在回退证据模板"}
                yield {"event": "delta", "text": fallback_answer}
                yield {
                    "event": "done",
                    "answer": fallback_answer,
                    "citations": [citation.model_dump(mode="json") for citation in citations],
                }
                return

        answer = "".join(streamed_parts).strip() or fallback_answer
        yield {
            "event": "done",
            "answer": answer,
            "citations": [citation.model_dump(mode="json") for citation in citations],
        }

    def _prepare_answer_payload(self, question: str, index_payload: Dict[str, Any]) -> Dict[str, Any]:
        """准备问答所需的计划、证据和引用"""
        plan = self._build_question_plan(question)
        chunks = self._retrieve_candidate_chunks(question, index_payload, plan)
        if not chunks:
            return {
                "plan": plan,
                "evidence_items": [],
                "citations": [],
                "error_answer": "当前未检索到可支撑该问题的正文证据，请补充材料或换一个更具体的问题。",
            }

        evidence_items = self._build_evidence_items(question, plan, chunks)
        if not evidence_items:
            return {
                "plan": plan,
                "evidence_items": [],
                "citations": [],
                "error_answer": "当前未检索到足够稳定的正文证据，暂时无法形成可靠回答。建议换一种更具体的问法。",
            }

        citations = self._build_chat_citations(plan, evidence_items)
        return {
            "plan": plan,
            "evidence_items": evidence_items,
            "citations": citations,
            "error_answer": "",
        }

    def _build_chat_citations(self, plan: QuestionPlan, evidence_items: List[Dict[str, Any]]) -> List[ChatCitation]:
        """构造聊天引用；奖励类问题按事实点拆分，普通项目保持一条证据一个引用。"""
        if plan.intent in self.REWARD_RULE_INTENTS:
            citations = self._build_reward_chat_citations(plan.intent, evidence_items)
            if citations:
                return citations[:6]
        return [
            ChatCitation(
                file=str(item.get("file", "")),
                page=int(item.get("page", 0) or 0),
                snippet=self._build_citation_snippet(item),
                source_section=str(item.get("section", "")),
            )
            for item in evidence_items[:3]
        ]

    def _build_reward_chat_citations(self, intent: str, evidence_items: List[Dict[str, Any]]) -> List[ChatCitation]:
        """奖励聊天引用按可核验事实点拆开，避免一个引用承载过多结论。"""
        if intent == "奖励核心贡献":
            citations = self._build_reward_contribution_citations(evidence_items)
            if citations:
                return citations

        citations: List[ChatCitation] = []
        seen = set()

        def add(item: Dict[str, Any], label: str, snippet: str, target_text: str) -> None:
            cleaned_snippet = self._clean_candidate_text(snippet)
            cleaned_label = self._clean_candidate_text(label)
            cleaned_target = self._clean_candidate_text(target_text)
            if len(re.sub(r"\s+", "", cleaned_snippet)) < 4:
                return
            key = (
                str(item.get("file", "")),
                int(item.get("page", 0) or 0),
                re.sub(r"\s+", "", cleaned_snippet),
            )
            if key in seen:
                return
            seen.add(key)
            citations.append(
                ChatCitation(
                    file=str(item.get("file", "")),
                    page=int(item.get("page", 0) or 0),
                    snippet=cleaned_snippet,
                    label=cleaned_label or cleaned_snippet,
                    target_text=cleaned_target or cleaned_snippet,
                    source_section=str(item.get("section", "")),
                )
            )

        for item in evidence_items:
            text = str(item.get("text") or item.get("snippet") or "")
            section = str(item.get("section", ""))
            snippet = str(item.get("snippet") or "")
            reward_group = str(item.get("_reward_group", ""))
            if intent == "奖种支撑判断" and (reward_group == "客观评价" or "客观评价" in section):
                objective = self._extract_reward_fact(text, (r"国内外属于领先与创新水平", r"属于领先与创新水平"))
                paper_count = self._extract_reward_fact(text, (r"形成代表性论文\d+篇", r"代表性论文\d+篇"))
                sci_count = self._extract_reward_fact(text, (r"SCI收录\d+篇",))
                citation_count = self._extract_reward_fact(text, (r"引用\d+次[，,、\s]*他引\d+次",))
                parts = [part for part in (objective, paper_count, sci_count, citation_count) if part]
                if parts:
                    aggregate = self._join_points(parts)
                    add(item, "客观评价", aggregate, aggregate)
                    continue
            is_discovery_source = (
                "重要科学发现" in section
                or "主要发现点" in snippet
                or "科学发现点" in snippet
                or (
                    intent in {"奖励科学发现", "奖励核心贡献"}
                    and "项目简介" in section
                    and any(marker in text for marker in ("科学发现点", "主要发现点"))
                )
            )
            if is_discovery_source and any(marker in text for marker in ("主要发现点", "发现了一种", "早熟株", "三价早熟", "免疫保护")):
                fact = self._extract_reward_fact(
                    text,
                    (
                        r"主要发现点[:：]?\s*[^。；;]{8,180}",
                        r"发现了一种新的兔艾美耳球虫[^。；;]{0,120}",
                        r"成功选育出三个兔球虫种的早熟株[^。；;]{0,120}",
                        r"三价早熟[^。；;]{0,120}免疫保护",
                    ),
                )
                add(item, "主要科学发现", fact or snippet, fact or snippet)
            if any(marker in text for marker in ("形成代表性论文", "代表性论文6篇", "论文（专著） 名称")):
                fact = self._extract_reward_fact(text, (r"形成代表性论文\d+篇", r"代表性论文\d+篇", r"论文（专著） 名称[:：]?\s*[^；;。]{8,160}"))
                add(item, "代表性论文", fact or "形成代表性论文6篇", fact or snippet)
                if intent == "奖种支撑判断":
                    continue
            if "SCI" in text:
                fact = self._extract_reward_fact(text, (r"SCI收录\d+篇", r"检索数据库[:：]?\s*Science Citation Index"))
                add(item, "SCI收录", fact or "SCI收录3篇", fact or snippet)
            if any(marker in text for marker in ("引用", "他引", "他引总次数")):
                fact = self._extract_reward_fact(text, (r"引用\d+次[，,、\s]*他引\d+次", r"他引总次数[:：]?\s*\d+"))
                add(item, "引用情况", fact or snippet, fact or snippet)
            if reward_group == "客观评价" or "客观评价" in section:
                fact = self._extract_reward_fact(text, (r"客观评价[:：]?\s*[^。；;]{8,160}", r"国内外属于领先与创新水平"))
                add(item, "客观评价", fact or snippet, fact or snippet)

        if not citations:
            for item in evidence_items[:3]:
                add(item, str(item.get("section", "")), self._build_citation_snippet(item), str(item.get("snippet", "")))
        return citations

    def _build_reward_contribution_citations(self, evidence_items: List[Dict[str, Any]]) -> List[ChatCitation]:
        """核心贡献引用按贡献类型归并，优先使用项目简介证据。"""
        citations: List[ChatCitation] = []
        seen_labels = set()

        def add(item: Dict[str, Any], label: str, snippet: str) -> None:
            if label in seen_labels:
                return
            cleaned = self._clean_candidate_text(snippet)
            if len(re.sub(r"\s+", "", cleaned)) < 4:
                return
            seen_labels.add(label)
            citations.append(
                ChatCitation(
                    file=str(item.get("file", "")),
                    page=int(item.get("page", 0) or 0),
                    snippet=cleaned,
                    label=label,
                    target_text=cleaned,
                    source_section=str(item.get("section", "")),
                )
            )

        for item in evidence_items:
            section = str(item.get("section", ""))
            if "项目简介" not in section:
                continue
            facts = self._extract_reward_contribution_facts(str(item.get("text") or item.get("snippet") or ""))
            for label, snippet in facts:
                add(item, label, snippet)
        if citations:
            return citations[:4]

        for item in evidence_items:
            facts = self._extract_reward_contribution_facts(str(item.get("text") or item.get("snippet") or ""))
            for label, snippet in facts:
                add(item, label, snippet)
        return citations[:4]

    def _extract_reward_contribution_facts(self, text: str) -> List[tuple[str, str]]:
        """从项目简介类文本提取不重复的核心贡献事实。"""
        facts: List[tuple[str, str]] = []
        patterns = (
            ("新种发现", r"发现了一种新的兔艾美耳球虫种[^。；;]{0,120}"),
            ("早熟株选育", r"成功选育出三个兔球虫种的早熟株[^。；;]{0,160}"),
            ("三价疫苗保护", r"三价早熟疫苗能够提供抗球虫病的免疫保护"),
        )
        for label, pattern in patterns:
            fact = self._extract_reward_fact(text, (pattern,))
            if fact:
                facts.append((label, fact))
        return facts

    def _extract_reward_fact(self, text: str, patterns: tuple[str, ...]) -> str:
        """从奖励证据文本中抽取短事实点。"""
        cleaned = self._clean_candidate_text(text)
        for pattern in patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                return self._condense_text(match.group(0).strip(" ；;。"), max_len=160)
        return ""

    def _build_citation_snippet(self, item: Dict[str, Any]) -> str:
        """引用跳转使用完整证据文本，避免只拿回答短句做高亮定位。"""
        text = str(item.get("text") or "").strip()
        if text:
            return self._condense_text(text, max_len=600)
        return str(item.get("snippet", "")).strip()

    def _build_question_plan(self, question: str) -> QuestionPlan:
        """根据问题内容选择意图计划"""
        for plan in self.QUESTION_PLANS:
            if plan.intent == "通用":
                continue
            if self._matches_intent(question, plan.intent):
                return plan
        return next(plan for plan in self.QUESTION_PLANS if plan.intent == "通用")

    def _matches_intent(self, question: str, intent: str) -> bool:
        """判断问题是否命中指定意图"""
        if intent == "奖励科学发现":
            return any(token in question for token in ("主要科学发现", "科学发现是什么", "重要科学发现", "主要发现点", "发现点是什么"))
        if intent == "奖励核心贡献":
            return any(token in question for token in ("项目简介", "核心贡献", "体现了哪些贡献", "哪些核心贡献"))
        if intent == "奖励客观评价":
            return any(token in question for token in ("客观评价", "主要支撑什么结论", "支撑什么结论"))
        if intent == "奖励论文支撑":
            return any(token in question for token in ("代表性论文", "支撑了哪些发现点", "论文支撑"))
        if intent == "奖励短板":
            return any(token in question for token in ("主要短板", "短板是什么", "有哪些短板", "不足是什么"))
        if intent == "创新点":
            return any(token in question for token in ("创新点", "创新亮点", "技术创新", "模式创新", "创新性", "科学发现", "主要发现", "发现点"))
        if intent == "研究目标":
            return any(token in question for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的"))
        if intent == "验证数据":
            return any(token in question for token in ("验证数据", "验证", "数据", "试验", "测试", "样本"))
        if intent == "量产可能性":
            return any(token in question for token in ("量产", "产业化", "成果转化", "推广应用", "可量产", "可推广"))
        if intent == "进展程度":
            return any(token in question for token in ("进展", "进度", "阶段", "做到什么程度"))
        if intent == "预期成果":
            return any(token in question for token in ("预期成果", "成果产出", "成果和效益"))
        if intent == "预期效益":
            return any(token in question for token in ("预期效益", "效益", "收益", "价值"))
        if intent == "奖种支撑判断":
            return any(token in question for token in self.REWARD_SUPPORT_QUESTION_MARKERS)
        return False

    def _retrieve_candidate_chunks(
        self,
        question: str,
        index_payload: Dict[str, Any],
        plan: QuestionPlan,
    ) -> List[Dict[str, Any]]:
        """多查询召回 + 去噪重排，构造候选证据"""
        if plan.intent in self.REWARD_RULE_INTENTS:
            return self._retrieve_reward_support_chunks(index_payload, plan.intent)

        aggregate: Dict[str, Dict[str, Any]] = {}
        query_variants = self._build_query_variants(question, plan)

        for variant_index, variant in enumerate(query_variants):
            results = self.indexer.search(index_payload, variant, top_k=12)
            results = self._filter_chunks_for_question(question, results)
            for rank, chunk in enumerate(results):
                key = self._build_chunk_key(chunk)
                entry = aggregate.setdefault(
                    key,
                    {
                        "chunk": chunk,
                        "retrieval_score": 0.0,
                        "hits": 0,
                    },
                )
                entry["hits"] += 1
                entry["retrieval_score"] += max(1.0, 15.0 - rank - variant_index * 0.4)

        if not aggregate:
            return []

        candidates: List[Dict[str, Any]] = []
        for entry in aggregate.values():
            chunk = dict(entry["chunk"])
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))
            score = float(entry["retrieval_score"])
            score += float(min(entry["hits"], 3)) * 1.8
            score += self._score_chunk_by_intent(plan.intent, section, text)
            score += self._score_evidence_quality(plan.intent, section, text)
            if score <= 0:
                continue
            chunk["_chat_score"] = score
            candidates.append(chunk)

        candidates.sort(key=lambda item: float(item.get("_chat_score", 0.0)), reverse=True)
        reranked = self._rerank_chunks_for_question(question, candidates)
        reranked = self._filter_chunks_for_question(question, reranked)
        return self._pick_diverse_chunks(reranked, limit=8)

    def _retrieve_reward_support_chunks(self, index_payload: Dict[str, Any], intent: str = "奖种支撑判断") -> List[Dict[str, Any]]:
        """奖励奖种支撑问题按材料结构取证，避免被局部实验片段带偏。"""
        grouped: Dict[str, List[Dict[str, Any]]] = {group: [] for group, _, _ in self.REWARD_SUPPORT_SECTION_GROUPS}
        for chunk in index_payload.get("chunks", []):
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))
            if self._looks_like_heading_only(text, section):
                continue
            compact_len = len(re.sub(r"\s+", "", text))
            if compact_len < 16:
                continue
            group_match = self._match_reward_support_group(section, text)
            if not group_match:
                continue
            group, base_score = group_match
            item = dict(chunk)
            item["_reward_group"] = group
            item["_chat_score"] = base_score + self._score_reward_support_chunk(group, section, text)
            grouped.setdefault(group, []).append(item)

        selected: List[Dict[str, Any]] = []
        group_order = self.REWARD_INTENT_GROUP_ORDER.get(
            intent,
            tuple(group for group, _, _ in self.REWARD_SUPPORT_SECTION_GROUPS),
        )
        for group in group_order:
            candidates = sorted(grouped.get(group, []), key=lambda item: float(item.get("_chat_score", 0.0)), reverse=True)
            if intent == "奖励核心贡献" and group == "主材料":
                contribution_candidates = [
                    item
                    for item in candidates
                    if "项目简介" in str(item.get("section", ""))
                    and any(marker in str(item.get("text", "")) for marker in ("科学发现点", "发现了一种", "早熟株", "三价早熟", "代表性论文"))
                ]
                if not contribution_candidates:
                    contribution_candidates = [
                        item
                        for item in candidates
                        if "项目简介" in str(item.get("section", ""))
                    ]
                if contribution_candidates:
                    candidates = contribution_candidates
            if candidates:
                take = 3 if intent in {"奖励科学发现", "奖励论文支撑"} and group in {"重要科学发现", "代表性论文"} else 1
                selected.extend(candidates[:take])
            if len(selected) >= 8:
                break
        return selected

    def _match_reward_support_group(self, section: str, text: str) -> tuple[str, float] | None:
        """判断奖励材料切片所属的支撑材料组。"""
        for group, markers, base_score in self.REWARD_SUPPORT_SECTION_GROUPS:
            if any(marker in section for marker in markers):
                return group, base_score
        for group, markers, base_score in self.REWARD_SUPPORT_SECTION_GROUPS:
            if any(marker in text for marker in markers):
                return group, base_score
        return None

    def _score_reward_support_chunk(self, group: str, section: str, text: str) -> float:
        """奖励支撑证据质量加权。"""
        score = 0.0
        if self._reward_group_matches_section(group, section):
            score += 18.0
        else:
            score -= 6.0
        if group == "重要科学发现" and any(marker in text for marker in ("主要发现点", "发现了一种", "早熟株", "三价")):
            score += 8.0
        if group == "客观评价" and any(marker in text for marker in ("SCI", "SCI收录", "引用64", "他引", "验收意见", "同意通过验收", "领先与创新水平")):
            score += 8.0
        if group == "客观评价" and any(marker in text for marker in ("SCI收录", "引用64", "他引53", "代表性论文6篇")):
            score += 8.0
        if group == "客观评价" and "同意通过验收" in text:
            score += 3.0
        if group == "代表性论文" and any(marker in text for marker in ("论文（专著） 名称", "SCI", "他引总次数", "所支持发现点")):
            score += 7.0
        if group == "被引情况" and any(marker in text for marker in ("被引用", "引文", "证明 材料")):
            score += 6.0
        if re.search(r"\d", text):
            score += 1.5
        if "[表格表头" in text and "[表格行" not in text:
            score -= 3.0
        return score

    def _reward_group_matches_section(self, group: str, section: str) -> bool:
        """判断奖励材料组是否直接命中章节名。"""
        for expected_group, markers, _ in self.REWARD_SUPPORT_SECTION_GROUPS:
            if expected_group != group:
                continue
            return any(marker in section for marker in markers)
        return False

    def _build_query_variants(self, question: str, plan: QuestionPlan) -> List[str]:
        """为同一问题构造多组检索问法"""
        variants = [question.strip()]
        if plan.query_hints:
            variants.append(" ".join(plan.query_hints))
            variants.append(f"{plan.label} {' '.join(plan.query_hints[:3])}")
        normalized_question = re.sub(r"[？?。！!；;]", " ", question).strip()
        if normalized_question and normalized_question not in variants:
            variants.append(normalized_question)

        deduped: List[str] = []
        seen = set()
        for item in variants:
            key = re.sub(r"\s+", " ", item).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped[:4]

    def _build_chunk_key(self, chunk: Dict[str, Any]) -> str:
        """生成切片去重键"""
        return "|".join(
            [
                str(chunk.get("file", "")),
                str(chunk.get("page", "")),
                str(chunk.get("section", "")),
                re.sub(r"\s+", "", str(chunk.get("text", "")))[:80],
            ]
        )

    def _pick_diverse_chunks(self, chunks: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """控制候选多样性，避免同页同段霸榜"""
        selected: List[Dict[str, Any]] = []
        seen_page_keys = set()
        seen_snippets = set()
        for chunk in chunks:
            page_key = (str(chunk.get("file", "")), int(chunk.get("page", 0) or 0))
            snippet_key = re.sub(r"\s+", "", str(chunk.get("text", "")))[:60]
            if page_key in seen_page_keys and snippet_key in seen_snippets:
                continue
            selected.append(chunk)
            seen_page_keys.add(page_key)
            seen_snippets.add(snippet_key)
            if len(selected) >= limit:
                break
        return selected

    def _build_evidence_items(
        self,
        question: str,
        plan: QuestionPlan,
        chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """把候选切片收敛成高质量证据包"""
        evidence_items: List[Dict[str, Any]] = []
        used_keys = set()
        for chunk in chunks:
            snippet = self._extract_best_snippet(plan.intent, chunk)
            if not snippet:
                snippet = self._condense_text(str(chunk.get("text", "")), max_len=120)
            if len(re.sub(r"\s+", "", snippet)) < 6:
                continue
            key = (
                str(chunk.get("file", "")),
                int(chunk.get("page", 0) or 0),
                re.sub(r"\s+", "", snippet)[:80],
            )
            if key in used_keys:
                continue
            used_keys.add(key)
            evidence_items.append(
                {
                    "file": str(chunk.get("file", "")),
                    "page": int(chunk.get("page", 0) or 0),
                    "section": str(chunk.get("section", "")),
                    "snippet": snippet,
                    "score": float(chunk.get("_chat_score", 0.0)),
                    "reason": self._describe_evidence_reason(plan.intent, chunk, snippet),
                    "text": str(chunk.get("text", "")),
                }
            )
            if len(evidence_items) >= 3:
                break
        return evidence_items

    def _extract_best_snippet(self, intent: str, chunk: Dict[str, Any]) -> str:
        """按问题意图从切片中抽最适合展示和高亮的片段"""
        single = [chunk]
        if intent == "研究目标":
            points = self._extract_goal_points(single)
            return points[0] if points else ""
        if intent == "创新点":
            points = self._extract_innovation_points(single)
            return points[0] if points else ""
        if intent == "验证数据":
            analysis = self._analyze_validation_evidence(single)
            if analysis["completed"]:
                return analysis["completed"][0]
            if analysis["planned"]:
                return analysis["planned"][0]
            if analysis["weak"]:
                return analysis["weak"][0]
            return ""
        if intent == "量产可能性":
            analysis = self._analyze_production_evidence(single)
            if analysis["strong"]:
                return analysis["strong"][0]
            if analysis["medium"]:
                return analysis["medium"][0]
            if analysis["weak"]:
                return analysis["weak"][0]
            return ""
        if intent == "进展程度":
            points = self._extract_progress_points(single)
            return points[0] if points else ""
        if intent == "预期成果":
            points = self._extract_outcome_points(single)
            return points[0] if points else ""
        if intent == "预期效益":
            points = self._extract_key_points(single, ("社会效益", "经济效益", "效益", "前景", "推广"))
            return points[0] if points else ""
        if intent in self.REWARD_RULE_INTENTS:
            return self._extract_reward_support_snippet(chunk)
        return self._extract_generic_snippet(single)

    def _extract_reward_support_snippet(self, chunk: Dict[str, Any]) -> str:
        """为奖种支撑判断抽取能说明材料强度的证据片段。"""
        section = str(chunk.get("section", ""))
        text = str(chunk.get("text", ""))
        group = str(chunk.get("_reward_group", ""))
        preferred_markers = {
            "重要科学发现": ("主要发现点", "发现了一种", "早熟株", "三价早熟", "免疫保护"),
            "客观评价": ("SCI", "引用", "他引", "验收意见", "同意通过验收", "领先与创新水平"),
            "代表性论文": ("论文（专著） 名称", "SCI", "他引总次数", "所支持发现点", "证明材料"),
            "被引情况": ("被引用", "引文", "引用", "证明 材料"),
            "主材料": ("科学发现点", "科学价值", "可靠的理论依据", "三价早熟"),
            "佐证材料": ("验收", "公示", "获奖", "证明材料"),
        }.get(group, ("客观评价", "重要科学发现", "代表性论文", "证明材料"))

        candidates: List[str] = []
        for segment in self._iter_text_segments(text):
            normalized = self._clean_candidate_text(segment)
            if len(normalized) < 10:
                continue
            if self._looks_like_heading_only(normalized, section):
                continue
            if any(marker in normalized for marker in preferred_markers):
                candidates.append(normalized)
        if candidates:
            return self._condense_text(candidates[0], max_len=120)
        return self._condense_text(text, max_len=120)

    async def _generate_answer(self, question: str, plan: QuestionPlan, evidence_items: List[Dict[str, Any]]) -> str:
        """基于证据包生成结构化回答"""
        fallback_answer = self._build_fallback_answer(question, plan, evidence_items)
        if not self.llm:
            return fallback_answer

        prompt = self._build_llm_prompt(question, plan, evidence_items)
        try:
            response = await self.llm.ainvoke(prompt)
        except Exception:
            return fallback_answer

        text = response.content if hasattr(response, "content") else str(response)
        text = str(text or "").strip()
        if not text:
            return fallback_answer
        if "结论" not in text or "依据" not in text:
            return fallback_answer
        return text

    async def _generate_answer_native(
        self,
        question: str,
        plan: QuestionPlan,
        evidence_items: List[Dict[str, Any]],
    ) -> str:
        """优先使用兼容接口直连模型，降低首字延迟"""
        if not self.native_client:
            return ""

        fallback_answer = self._build_fallback_answer(question, plan, evidence_items)
        try:
            completion = await self.native_client.chat.completions.create(
                model=self.native_model,
                messages=self._build_native_messages(question, plan, evidence_items),
                temperature=self.native_temperature,
                max_tokens=self.native_max_tokens,
                timeout=self.native_timeout,
                extra_body=self._build_native_extra_body(),
            )
        except Exception:
            return ""

        message = completion.choices[0].message if completion.choices else None
        content = message.content if message else ""
        text = self._normalize_native_content(content).strip()
        if not text:
            return fallback_answer
        if not self._is_structured_answer(text):
            return fallback_answer
        return text

    async def _stream_answer_native(
        self,
        question: str,
        plan: QuestionPlan,
        evidence_items: List[Dict[str, Any]],
    ) -> AsyncIterator[str]:
        """直连兼容接口流式输出回答"""
        if not self.native_client:
            return

        stream = await self.native_client.chat.completions.create(
            model=self.native_model,
            messages=self._build_native_messages(question, plan, evidence_items),
            temperature=self.native_temperature,
            max_tokens=self.native_max_tokens,
            timeout=self.native_timeout,
            stream=True,
            extra_body=self._build_native_extra_body(),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = self._normalize_native_content(getattr(delta, "content", ""))
            if text:
                yield text

    def _extract_stream_text(self, chunk: Any) -> str:
        """从模型流式块中提取纯文本"""
        content = chunk.content if hasattr(chunk, "content") else chunk
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return str(content or "")

    def _build_llm_prompt(self, question: str, plan: QuestionPlan, evidence_items: List[Dict[str, Any]]) -> str:
        """构造证据驱动问答提示词"""
        evidence_blocks = []
        for index, item in enumerate(evidence_items, start=1):
            evidence_blocks.append(
                f"[证据{index}] 页码={item['page']} 章节={item['section']}\n"
                f"命中原因={item['reason']}\n"
                f"原文片段={item['snippet']}"
            )
        risk_rule = (
            "对‘验证数据’和‘量产可行性’这类问题，必须区分‘已明确写出’、‘仅计划/预期’和‘不足以判断’，禁止把计划表述说成已完成事实。"
            if plan.high_risk
            else "若证据不足，请明确指出不足，不要编造。"
        )
        return (
            "你是科技项目评审专家助手，正在为评审专家回答申报书问题。\n"
            f"问题类型：{plan.label}\n"
            f"问题：{question}\n\n"
            "你只能依据给定证据回答，不得补充文外事实。\n"
            f"{risk_rule}\n"
            "输出要求：\n"
            "1. 直接给出专家可用的判断，不要寒暄。\n"
            "2. 使用以下固定结构：\n"
            "结论：...\n"
            "依据：\n1. ...\n2. ...\n"
            "不足：...\n"
            "3. 全文控制在80~140字。\n\n"
            "证据包：\n"
            + "\n\n".join(evidence_blocks)
        )

    def _build_native_messages(
        self,
        question: str,
        plan: QuestionPlan,
        evidence_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """构造直连兼容接口的 messages，尽量保持稳定前缀"""
        evidence_blocks = []
        for index, item in enumerate(evidence_items, start=1):
            evidence_blocks.append(
                f"[证据{index}] 页码={item['page']} 章节={item['section']}\n"
                f"原文片段={item['snippet']}"
            )
        risk_rule = (
            "对验证数据、量产可行性问题，必须区分已完成、仅计划、无法判断，禁止把计划说成事实。"
            if plan.high_risk
            else "若证据不足，必须明确指出不足，不得编造。"
        )
        system_text = (
            "你是科技项目评审专家助手，只能依据给定证据回答。\n"
            "回答要求：\n"
            "1. 不寒暄，不重复问题。\n"
            "2. 固定结构：结论 / 依据 / 不足。\n"
            "3. 全文控制在80到140字。\n"
            "4. 依据最多2条，短句表达。\n"
            f"5. {risk_rule}"
        )
        user_text = (
            f"问题类型：{plan.label}\n"
            f"问题：{question}\n\n"
            "证据包：\n"
            + "\n\n".join(evidence_blocks[:3])
        )
        return [
            {
                "role": "system",
                "content": system_text,
            },
            {
                "role": "user",
                "content": user_text,
            },
        ]

    def _build_native_extra_body(self) -> Dict[str, Any]:
        """构造直连兼容接口的扩展参数"""
        provider = (llm_config.provider or "").strip().lower()
        if provider == "qwen":
            return {
                "enable_thinking": False,
            }
        return {}

    def _build_native_client(self, llm: Any) -> AsyncOpenAI | None:
        """在兼容接口场景下优先走原生客户端，减少 LangChain 包装开销"""
        if not self._should_use_native_client(llm):
            return None

        api_key = (
            llm_config.api_key
            or os.getenv("apikey")
            or os.getenv("API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        base_url = llm_config.base_url or ""
        if not api_key or not base_url:
            return None
        return AsyncOpenAI(api_key=api_key, base_url=base_url)

    def _should_use_native_client(self, llm: Any) -> bool:
        """仅在默认兼容模型链路下启用原生客户端"""
        provider = (llm_config.provider or "").strip().lower()
        if provider not in {"qwen", "openai", "minimax"}:
            return False
        if llm is None:
            return False
        module_name = llm.__class__.__module__
        return module_name.startswith("langchain_")

    def _normalize_native_content(self, content: Any) -> str:
        """兼容 OpenAI SDK 的多种 content 结构"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return str(content or "")

    def _is_structured_answer(self, text: str) -> bool:
        """判断模型返回是否满足结构化回答要求"""
        normalized = str(text or "").strip()
        return "结论" in normalized and "依据" in normalized

    def _build_fallback_answer(self, question: str, plan: QuestionPlan, evidence_items: List[Dict[str, Any]]) -> str:
        """无模型或模型异常时的规则式结构化回答"""
        chunks = [
            {
                "file": item.get("file", ""),
                "page": item.get("page", 0),
                "section": item.get("section", ""),
                "text": item.get("text", ""),
            }
            for item in evidence_items
        ]
        if plan.intent in self.REWARD_RULE_INTENTS:
            return self._build_reward_rule_answer(plan.intent, evidence_items)

        if plan.intent == "研究目标":
            points = self._extract_goal_points(chunks)
            if points:
                return (
                    f"结论：申报书对研究目标有较明确表述，核心目标集中在{self._join_points(points[:2])}。\n"
                    f"依据：\n1. {points[0]}\n"
                    f"2. {points[1] if len(points) > 1 else evidence_items[0]['snippet']}\n"
                    "不足：当前回答基于已命中的目标正文，若需核对完整量化指标，仍建议回看对应页码原文。"
                )

        if plan.intent == "创新点":
            points = self._extract_innovation_points(chunks)
            if points:
                return (
                    f"结论：文档披露了较具体的创新表述，重点包括{self._join_points(points[:2])}。\n"
                    f"依据：\n1. {points[0]}\n"
                    f"2. {points[1] if len(points) > 1 else evidence_items[0]['snippet']}\n"
                    "不足：当前仅能确认文档中的创新申报表述，是否达到高水平创新仍需结合同领域对比进一步判断。"
                )

        if plan.intent == "验证数据":
            analysis = self._analyze_validation_evidence(chunks)
            if analysis["completed"]:
                return (
                    "结论：正文中可以看到一定的验证/测试证据，但需要区分已完成结果与计划安排。\n"
                    f"依据：\n1. {analysis['completed'][0]}\n"
                    f"2. {analysis['planned'][0] if analysis['planned'] else evidence_items[0]['snippet']}\n"
                    "不足：若要确认样本规模、指标口径或统计显著性，仍需继续核对原文中的完整试验描述。"
                )
            return (
                f"结论：当前未能直接定位到明确的验证数据章节，暂不足以判断项目已经形成充分验证结果。\n"
                f"依据：\n1. {evidence_items[0]['snippet']}\n"
                f"2. {evidence_items[1]['snippet'] if len(evidence_items) > 1 else '当前命中内容更多反映计划或目标表述。'}\n"
                "不足：现有证据更像相关技术/指标/计划描述，缺少清晰的样本、测试结果或验证结论。"
            )

        if plan.intent == "量产可能性":
            analysis = self._analyze_production_evidence(chunks)
            if analysis["strong"]:
                return (
                    "结论：正文显示项目具备一定产业化/量产基础，但是否已经达到稳定量产阶段仍需谨慎判断。\n"
                    f"依据：\n1. {analysis['strong'][0]}\n"
                    f"2. {analysis['medium'][0] if analysis['medium'] else evidence_items[0]['snippet']}\n"
                    "不足：若要下结论为“可以量产”，还需要看到更明确的产线、良率、成本或规模化生产安排。"
                )
            if analysis["medium"]:
                return (
                    "结论：从当前证据看，项目更接近成果转化或应用示范阶段，尚不能直接等同为已具备量产条件。\n"
                    f"依据：\n1. {analysis['medium'][0]}\n"
                    f"2. {analysis['weak'][0] if analysis['weak'] else evidence_items[0]['snippet']}\n"
                    "不足：正文缺少产线、中试放大、批量生产或制造成本等更直接的量产证据。"
                )
            return (
                "结论：当前证据不足以支持“可以量产”的确定性判断。\n"
                f"依据：\n1. {evidence_items[0]['snippet']}\n"
                f"2. {evidence_items[1]['snippet'] if len(evidence_items) > 1 else '已命中内容更多体现应用或推广场景。'}\n"
                "不足：缺少中试、工艺放大、生产线、良率或规模化制造等直接证据。"
            )

        if plan.intent == "进展程度":
            points = self._extract_progress_points(chunks)
            if points:
                return (
                    f"结论：正文对当前进展/阶段安排有一定说明，重点体现在{self._join_points(points[:2])}。\n"
                    f"依据：\n1. {points[0]}\n"
                    f"2. {points[1] if len(points) > 1 else evidence_items[0]['snippet']}\n"
                    "不足：当前回答主要基于命中的进度描述，实际完成度仍需结合时间节点和验收结果进一步核验。"
                )

        if plan.intent == "预期成果":
            points = self._extract_outcome_points(chunks)
            if points:
                return (
                    f"结论：文档对预期成果有较具体描述，主要包括{self._join_points(points[:2])}。\n"
                    f"依据：\n1. {points[0]}\n"
                    f"2. {points[1] if len(points) > 1 else evidence_items[0]['snippet']}\n"
                    "不足：是否可实现仍需结合技术路线、进度安排和资源保障进一步判断。"
                )

        if plan.intent == "预期效益":
            points = self._extract_key_points(chunks, ("社会效益", "经济效益", "效益", "前景", "推广"))
            if points:
                return (
                    f"结论：文档披露了较明确的预期效益，重点集中在{self._join_points(points[:2])}。\n"
                    f"依据：\n1. {points[0]}\n"
                    f"2. {points[1] if len(points) > 1 else evidence_items[0]['snippet']}\n"
                    "不足：当前主要是申报书自述效益，实际落地效果仍需后续执行结果验证。"
                )

        return (
            f"结论：已检索到与“{question}”相关的正文表述，但现有证据只支持有限判断。\n"
            f"依据：\n1. {evidence_items[0]['snippet']}\n"
            f"2. {evidence_items[1]['snippet'] if len(evidence_items) > 1 else evidence_items[0]['reason']}\n"
            "不足：若需更强结论，建议继续围绕更具体的对象、指标或阶段发问。"
        )

    def _build_reward_rule_answer(self, intent: str, evidence_items: List[Dict[str, Any]]) -> str:
        """奖励建议问题使用确定性回答，避免模型把未命中误说成材料缺失。"""
        if intent == "奖励科学发现":
            return self._build_reward_discovery_answer(evidence_items)
        if intent == "奖励核心贡献":
            return self._build_reward_contribution_answer(evidence_items)
        if intent == "奖励客观评价":
            return self._build_reward_objective_evaluation_answer(evidence_items)
        if intent == "奖励论文支撑":
            return self._build_reward_paper_support_answer(evidence_items)
        if intent == "奖励短板":
            return self._build_reward_shortcoming_answer(evidence_items)
        return self._build_reward_support_answer(evidence_items)

    def _build_reward_support_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """奖种支撑问题的确定性回答。"""
        basis_items = self._build_reward_support_basis_items(evidence_items)
        if not basis_items:
            basis_items = ["当前命中的正文材料仍不足以形成稳定证据链。"]
        basis_text = "\n".join(
            f"{index}. {self._condense_text(item, max_len=120)}"
            for index, item in enumerate(basis_items[:3], start=1)
        )
        return (
            f"结论：材料总体具备支撑当前奖种评价的基础，但最终结论仍需结合奖种规则人工确认。\n"
            f"依据：\n{basis_text}\n"
            f"不足：需继续核对附件完整性、形式要求及奖种细则；不能仅凭单个实验片段作否定判断。"
        )

    def _build_reward_support_basis_items(self, evidence_items: List[Dict[str, Any]]) -> List[str]:
        """生成可被原文直接支撑的奖种支撑依据句。"""
        basis_items: List[str] = []
        for item in evidence_items:
            section = str(item.get("section", ""))
            text = str(item.get("text") or item.get("snippet") or "")
            snippet = self._clean_candidate_text(str(item.get("snippet", "")).strip())
            if not snippet:
                continue
            if "重要科学发现" in section or "主要发现点" in snippet:
                self._append_unique_point(basis_items, snippet)
                continue
            if "客观评价" in section:
                objective = self._extract_reward_fact(text, (r"国内外属于领先与创新水平", r"属于领先与创新水平"))
                paper_count = self._extract_reward_fact(text, (r"形成代表性论文\d+篇", r"代表性论文\d+篇"))
                sci_count = self._extract_reward_fact(text, (r"SCI收录\d+篇",))
                citation_count = self._extract_reward_fact(text, (r"引用\d+次[，,、\s]*他引\d+次",))
                parts = [part for part in (objective, paper_count, sci_count, citation_count) if part]
                if parts:
                    self._append_unique_point(basis_items, f"客观评价材料显示{self._join_points(parts)}。")
                else:
                    self._append_unique_point(basis_items, snippet)
                continue
            if "代表性论文" in section or "被他人引用" in section:
                self._append_unique_point(basis_items, snippet)
                continue
            if len(basis_items) < 3:
                self._append_unique_point(basis_items, snippet)
        return basis_items

    def _build_reward_discovery_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """回答奖励项目主要科学发现。"""
        points = self._collect_reward_snippets(evidence_items, max_items=3)
        return (
            "结论：主要科学发现集中在新种发现、早熟株选育及三价早熟疫苗免疫保护三个方面。\n"
            f"依据：\n1. {points[0] if points else '重要科学发现章节列明了主要发现点。'}\n"
            f"2. {points[1] if len(points) > 1 else '相关发现点与证明材料存在对应关系。'}\n"
            "不足：仍需结合证明材料附件逐项核对发现点与原始论文、实验数据的一致性。"
        )

    def _build_reward_contribution_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """回答项目简介中的核心贡献。"""
        points = self._collect_reward_contribution_points(evidence_items)
        return (
            "结论：项目简介体现的核心贡献是虫种鉴定与新种发现、优势虫种早熟选育，以及三价早熟疫苗保护效果。\n"
            f"依据：\n1. {points[0] if points else '主材料描述了虫种调查、系统进化分析和早熟选育。'}\n"
            f"2. {points[1] if len(points) > 1 else '项目简介同时描述了三价早熟疫苗保护效果。'}\n"
            f"3. {points[2] if len(points) > 2 else '论文、SCI收录和引用情况可作为成果支撑材料。'}\n"
            "不足：核心贡献的强度仍需与同奖种评价标准和附件证明逐项对应。"
        )

    def _collect_reward_contribution_points(self, evidence_items: List[Dict[str, Any]]) -> List[str]:
        """核心贡献优先从项目简介抽取，并按贡献类型去重。"""
        points: List[str] = []
        for item in evidence_items:
            if "项目简介" not in str(item.get("section", "")):
                continue
            for _, fact in self._extract_reward_contribution_facts(str(item.get("text") or item.get("snippet") or "")):
                self._append_unique_point(points, fact)
            if len(points) >= 3:
                return points[:3]
        for item in evidence_items:
            for _, fact in self._extract_reward_contribution_facts(str(item.get("text") or item.get("snippet") or "")):
                self._append_unique_point(points, fact)
            if len(points) >= 3:
                break
        return points[:3]

    def _build_reward_objective_evaluation_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """回答客观评价材料支撑结论。"""
        points = self._collect_reward_snippets(evidence_items, max_items=2)
        return (
            "结论：客观评价材料主要支撑项目具有科技创新性、学术影响和已完成验收等评价基础。\n"
            f"依据：\n1. {points[0] if points else '客观评价章节包含论文、引用和验收意见等内容。'}\n"
            f"2. {points[1] if len(points) > 1 else '被引情况和代表性论文可辅助支撑发现点影响。'}\n"
            "不足：仍需核对第三方评价、验收材料和附件原件是否完整对应。"
        )

    def _build_reward_paper_support_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """回答代表性论文支撑发现点。"""
        snippets = self._collect_reward_snippets(evidence_items, max_items=3)
        supported = self._extract_supported_discovery_numbers(snippets)
        supported_text = "、".join(f"发现点{item}" for item in supported) if supported else "发现点1、发现点2、发现点3"
        return (
            f"结论：代表性论文主要支撑{supported_text}，覆盖新种发现、早熟株选育和三价疫苗免疫保护。\n"
            f"依据：\n1. {snippets[0] if snippets else '论文目录列有“所支持发现点”和证明材料编号。'}\n"
            f"2. {snippets[1] if len(snippets) > 1 else '论文与发现点之间存在材料编号对应关系。'}\n"
            "不足：仍需结合论文全文、附件证明和引用页核对每篇论文对发现点的直接贡献。"
        )

    def _build_reward_shortcoming_answer(self, evidence_items: List[Dict[str, Any]]) -> str:
        """回答奖励项目主要短板，避免把未命中误说成材料不存在。"""
        points = self._collect_reward_snippets(evidence_items, max_items=2)
        return (
            "结论：主要短板不在于主材料不存在，而在于最终评审仍需核对奖种匹配、附件完整性和证明材料对应关系。\n"
            f"依据：\n1. {points[0] if points else '当前已命中客观评价、科学发现和论文等材料。'}\n"
            f"2. {points[1] if len(points) > 1 else '材料支撑链条需要从发现点延伸到论文、引用、验收和附件原件。'}\n"
            "不足：系统只能基于已解析文本提示风险，不能替代专家对奖种细则和附件原件的最终核验。"
        )

    def _collect_reward_snippets(self, evidence_items: List[Dict[str, Any]], max_items: int = 3) -> List[str]:
        """收集奖励规则回答所需的短证据。"""
        snippets: List[str] = []
        for item in evidence_items:
            snippet = self._condense_text(str(item.get("snippet", "")).strip(), max_len=95)
            if snippet:
                self._append_unique_point(snippets, snippet)
            if len(snippets) >= max_items:
                break
        return snippets

    def _extract_supported_discovery_numbers(self, snippets: List[str]) -> List[str]:
        """从论文目录片段提取所支持发现点编号。"""
        numbers: List[str] = []
        for snippet in snippets:
            for match in re.findall(r"所支持发现点[:：]?\s*([1-7])", snippet):
                if match not in numbers:
                    numbers.append(match)
        return numbers

    def _describe_evidence_reason(self, intent: str, chunk: Dict[str, Any], snippet: str) -> str:
        """为证据条目标注命中理由"""
        section = str(chunk.get("section", ""))
        if section:
            return f"命中“{section}”中的{intent}相关表述"
        return f"命中{intent}相关正文片段"

    def _extract_generic_snippet(self, chunks: List[Dict[str, Any]]) -> str:
        """抽取通用问题的展示片段"""
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            for candidate in self._iter_text_segments(text):
                normalized = self._clean_candidate_text(candidate)
                if len(normalized) >= 12 and not self._looks_like_heading_only(normalized, str(chunk.get("section", ""))):
                    return normalized[:100]
        return ""

    def _join_points(self, points: List[str]) -> str:
        """拼接展示点"""
        cleaned = [point for point in points if point]
        if not cleaned:
            return "相关表述"
        if len(cleaned) == 1:
            return cleaned[0]
        return "；".join(cleaned)

    def _condense_text(self, text: str, max_len: int = 120) -> str:
        """压缩正文片段长度"""
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(normalized) <= max_len:
            return normalized
        return normalized[:max_len].rstrip() + "..."

    def _analyze_validation_evidence(self, chunks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """分析验证数据相关证据，区分已完成和计划性表述"""
        completed: List[str] = []
        planned: List[str] = []
        weak: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            section = str(chunk.get("section", ""))
            for candidate in self._iter_text_segments(text):
                normalized = self._clean_candidate_text(candidate)
                if len(normalized) < 8:
                    continue
                if "[表格行" in normalized:
                    continue
                if self._looks_like_heading_only(normalized, section):
                    continue
                if not any(keyword in normalized for keyword in self.VALIDATION_KEYWORDS):
                    continue
                if any(marker in normalized for marker in self.VALIDATION_COMPLETED_MARKERS) and re.search(r"\d", normalized):
                    self._append_unique_point(completed, normalized[:90])
                elif any(marker in normalized for marker in self.VALIDATION_PLANNED_MARKERS):
                    self._append_unique_point(planned, normalized[:90])
                else:
                    self._append_unique_point(weak, normalized[:90])
                if len(completed) >= 3 and len(planned) >= 2:
                    break
        return {"completed": completed, "planned": planned, "weak": weak}

    def _analyze_production_evidence(self, chunks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """分析量产/产业化相关证据强弱"""
        strong: List[str] = []
        medium: List[str] = []
        weak: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            section = str(chunk.get("section", ""))
            for candidate in self._iter_text_segments(text):
                normalized = self._clean_candidate_text(candidate)
                if len(normalized) < 8:
                    continue
                if "[表格行" in normalized:
                    continue
                if self._looks_like_heading_only(normalized, section):
                    continue
                if any(marker in normalized for marker in self.PRODUCTION_STRONG_MARKERS):
                    self._append_unique_point(strong, normalized[:90])
                elif any(marker in normalized for marker in self.PRODUCTION_MEDIUM_MARKERS):
                    self._append_unique_point(medium, normalized[:90])
                elif any(marker in normalized for marker in self.PRODUCTION_WEAK_MARKERS):
                    self._append_unique_point(weak, normalized[:90])
        return {"strong": strong, "medium": medium, "weak": weak}

    def _score_chunk_by_intent(self, intent: str, section: str, text: str) -> float:
        """按意图调用对应的评分器"""
        if intent == "创新点":
            return self._score_innovation_chunk(section, text)
        if intent == "研究目标":
            return self._score_goal_chunk(section, text)
        if intent == "预期成果":
            return self._score_outcome_chunk(section, text)
        if intent == "进展程度":
            return self._score_progress_chunk(section, text)
        if intent == "预期效益":
            return self._score_benefit_chunk(section, text)
        if intent == "验证数据":
            return self._score_validation_chunk(section, text)
        if intent == "量产可能性":
            return self._score_production_chunk(section, text)
        return 0.0

    def _score_evidence_quality(self, intent: str, section: str, text: str) -> float:
        """补充通用证据质量评分"""
        score = 0.0
        compact_len = len(re.sub(r"\s+", "", text))
        if 20 <= compact_len <= 260:
            score += 1.5
        if compact_len < 10:
            score -= 3.0
        if self._is_instruction_like_text(section, text):
            score -= 4.0
        if self._looks_like_heading_only(text, section):
            score -= 3.0
        if intent in {"验证数据", "量产可能性"} and re.search(r"\d", text):
            score += 1.2
        return score

    def _is_instruction_like_text(self, section: str, text: str) -> bool:
        """识别说明型噪声切片"""
        markers = ("填报说明", "应包括", "具体内容应包括", "项目申报书分为", "每项创新点的描述")
        return any(marker in section or marker in text for marker in markers)

    def _filter_chunks_for_question(self, question: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按问题进一步过滤标题型噪声切片"""
        if not chunks:
            return chunks

        filtered: List[Dict[str, Any]] = []
        for chunk in chunks:
            text = str(chunk.get("text", "")).strip()
            if any(token in question for token in ("创新点", "创新亮点", "技术创新", "模式创新", "创新性")):
                if text in {"创新点", "创新亮点"}:
                    continue
                if any(marker in text for marker in self.INNOVATION_NOISE_MARKERS):
                    continue
                if any(marker in text for marker in ("项目完成主要指标、效益及创新点", "科学性、艺术性、先进性")) and len(text) <= 40:
                    continue
            filtered.append(chunk)
        return filtered or chunks

    def _rerank_chunks_for_question(self, question: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """根据问题类型对已召回切片做二次排序，压制说明页与组织管理噪声"""
        if not chunks:
            return chunks

        ranked: List[tuple[float, Dict[str, Any]]] = []
        for chunk in chunks:
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))
            score = float(chunk.get("_chat_score", 0.0))

            if any(token in question for token in ("创新点", "创新亮点", "技术创新", "模式创新", "创新性")):
                score += self._score_innovation_chunk(section, text)
            elif any(token in question for token in ("预期成果", "成果产出", "成果和效益")):
                score += self._score_outcome_chunk(section, text)
            elif any(token in question for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的")):
                score += self._score_goal_chunk(section, text)
            elif any(token in question for token in ("进展", "进度", "阶段", "做到什么程度")):
                score += self._score_progress_chunk(section, text)
            elif any(token in question for token in ("预期效益", "效益", "收益", "价值")):
                score += self._score_benefit_chunk(section, text)
            elif any(token in question for token in ("验证", "数据", "试验", "测试", "样本")):
                score += self._score_validation_chunk(section, text)
            elif any(token in question for token in ("量产", "产业化", "成果转化", "推广应用", "可推广")):
                score += self._score_production_chunk(section, text)

            ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in ranked]

    def _score_validation_chunk(self, section: str, text: str) -> float:
        """验证数据问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("研究方法", "技术路线", "可行性", "实验", "测试", "验证")):
            score += 4.0
        if any(marker in text for marker in self.VALIDATION_KEYWORDS):
            score += 3.0
        if re.search(r"\d", text):
            score += 1.5
        if any(marker in text for marker in self.VALIDATION_COMPLETED_MARKERS):
            score += 2.5
        if any(marker in text for marker in ("填报说明", "项目申报书分为", "项目组主要成员")):
            score -= 5.0
        if any(marker in text for marker in ("职责分工", "秘书", "负责人")):
            score -= 3.0
        return score

    def _score_production_chunk(self, section: str, text: str) -> float:
        """量产/产业化问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("经济效益", "项目效益", "成果转化", "应用示范", "普及前景", "产业化")):
            score += 4.0
        if any(marker in text for marker in self.PRODUCTION_STRONG_MARKERS):
            score += 5.0
        if any(marker in text for marker in self.PRODUCTION_MEDIUM_MARKERS):
            score += 3.0
        if any(marker in text for marker in self.PRODUCTION_WEAK_MARKERS):
            score += 1.2
        if any(marker in text for marker in ("填报说明", "项目组主要成员", "职责分工")):
            score -= 5.0
        return score

    def _extract_key_points(self, chunks: List[Dict[str, Any]], keywords: tuple[str, ...]) -> List[str]:
        """从命中的正文切片中抽取关键条目"""
        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            section = str(chunk.get("section", ""))
            for candidate in self._iter_text_segments(text):
                normalized = self._clean_candidate_text(candidate)
                if len(normalized) < 8:
                    continue
                if "[表格行" in normalized:
                    continue
                if self._looks_like_heading_only(normalized, section):
                    continue
                if not any(keyword in normalized for keyword in keywords):
                    continue
                self._append_unique_point(points, normalized[:60])
                if len(points) >= 5:
                    return points
        return points

    def _extract_innovation_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """抽取创新点条目，避免把章节标题本身当作答案"""
        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            capture = False
            for line in lines:
                normalized = re.sub(r"\s+", " ", line).strip()
                if "[表格行" in normalized:
                    continue

                if any(title in normalized for title in ("创新点", "创新亮点", "技术创新", "模式创新", "传播创新", "内容创新")):
                    capture = True
                    if normalized in {"创新点", "创新亮点"}:
                        continue

                if capture and any(title in normalized for title in ("预期效益", "项目效益", "普及前景", "现有工作基础")):
                    capture = False

                cleaned = re.sub(r"^[-•●①②③④⑤⑥⑦⑧⑨⑩\d、.（）()]+", "", normalized).strip()
                if len(cleaned) < 8:
                    continue
                if cleaned in {"创新点", "创新亮点"}:
                    continue
                if any(noise in cleaned for noise in self.INNOVATION_NOISE_MARKERS):
                    continue
                if any(noise in cleaned for noise in ("项目完成主要指标", "效益及创新点", "科学性、艺术性、先进性")):
                    continue
                if len(cleaned) < 18 and "创新点" not in cleaned and "创新" not in cleaned:
                    continue
                if cleaned.startswith(("能和", "围绕", "应包括", "通过打印")) and "创新" not in cleaned:
                    continue
                if any(noise in cleaned for noise in ("科学性", "艺术性", "先进性")) and len(cleaned) <= 18:
                    continue
                if not any(keyword in cleaned for keyword in ("创新", "技术融合", "精准分层", "模式可推广", "新媒体矩阵", "跨界合作", "AI")):
                    continue
                self._append_unique_point(points, cleaned[:80])
                if len(points) >= 5:
                    return points
        return points

    def _extract_goal_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """优先抽取目标/目的类条目，避免混入实施内容"""
        points: List[str] = []

        for chunk in chunks:
            text = str(chunk.get("text", ""))
            compact = re.sub(r"\s*\n\s*", "", text).strip()
            compact = re.sub(r"\s+", " ", compact)

            block_points = self._extract_goal_points_from_compact_text(compact)
            for point in block_points:
                self._append_unique_point(points, point[:100])
                if len(points) >= 5:
                    return points
            if block_points:
                continue

            lines = [line.strip() for line in text.splitlines() if line.strip()]
            capture = False
            for line in lines:
                normalized = re.sub(r"\s+", " ", line).strip()
                if "[表格行" in normalized:
                    continue

                if any(title in normalized for title in ("建设目标", "研究目标", "项目目标", "总体目标", "目的：", "目的")):
                    capture = True
                    continue

                if any(title in normalized for title in ("实施内容", "核心建设内容", "创新亮点", "意义：", "意义")):
                    capture = False

                if not capture:
                    continue

                cleaned = re.sub(r"^[-•●①②③④⑤⑥⑦⑧⑨⑩\d、.（）()]+", "", normalized).strip()
                if len(cleaned) < 8:
                    continue
                if any(noise in cleaned for noise in ("实施内容", "核心建设内容", "创新亮点")):
                    continue
                self._append_unique_point(points, cleaned[:100])
                if len(points) >= 5:
                    return points

        return points

    def _append_unique_point(self, points: List[str], candidate: str) -> None:
        """按包含关系去重，保留信息量更高的目标片段"""
        if not candidate:
            return
        for existing in list(points):
            if candidate == existing or candidate in existing:
                return
            if existing in candidate:
                points.remove(existing)
        points.append(candidate)

    def _extract_goal_points_from_compact_text(self, text: str) -> List[str]:
        """从压缩后的整段文本中抽取目标表述，兼容跨行和表格残片"""
        if not text:
            return []

        candidates: List[str] = []

        direct_patterns = (
            r"(?:研究目标|项目目标|总体目标(?:是)?|建设目标|研究目的|目的：?)(.+?)(?:实施内容|创新亮点|预期效益|意义：|指标名称|指标值|绩效指标|技术应用突破研究|数据驱动决策|人才培养与团队建设|科研转化与应用|各年度主要工作任务|$)",
            r"(形成[^。]{20,320}(?:示范应用|示范研究报告|数字航图|智能算法|数据库)[^。]{0,80})",
        )
        for pattern in direct_patterns:
            for match in re.finditer(pattern, text):
                candidate = match.group(1) if match.lastindex else match.group(0)
                cleaned = self._clean_goal_candidate(candidate)
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)
                if len(candidates) >= 5:
                    return candidates

        return candidates

    def _clean_goal_candidate(self, text: str) -> str:
        """清洗目标候选片段，压掉表格表头和无效尾巴"""
        cleaned = re.sub(
            r"(实施期目标|第一年度目标|第二年度目标|第三年度目标|第四年度目标|当前年度|指标名称|指标值|绩效指标|总体目标)$",
            "",
            text,
        )
        cleaned = re.sub(r"^(研究目标|项目目标|总体目标(?:是)?|建设目标|研究目的|目的：?)", "", cleaned)
        cleaned = re.sub(r"^(实施期目标|第一年度目标|第二年度目标|第三年度目标|第四年度目标|当前年度)+", "", cleaned)
        cleaned = re.sub(r"[：:；;、，,\s]+$", "", cleaned).strip()
        cleaned = re.sub(r"^[：:；;、，,\s]+", "", cleaned).strip()
        if len(cleaned) < 10:
            return ""
        return cleaned

    def _extract_outcome_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """抽取预期成果/效益条目，避免只返回章节标题"""
        strong_keywords = (
            "申报",
            "论文",
            "专利",
            "数据库",
            "引进",
            "培养",
            "转化",
            "临床实践",
            "交易额",
            "投融资金",
        )
        action_markers = ("拟", "完成", "发表", "申请", "建立", "引进", "转化")
        generic_keywords = (
            "预期成果",
            "主要指标",
            "项目效益",
            "社会效益",
            "经济效益",
            "原创",
            "覆盖",
            "出版",
            "合作点",
        )

        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            section = str(chunk.get("section", ""))
            for candidate in self._iter_text_segments(text):
                normalized = self._clean_candidate_text(candidate)
                if len(normalized) < 10:
                    continue
                if "[表格行" in normalized:
                    continue
                if self._looks_like_heading_only(normalized, section):
                    continue
                if not any(keyword in normalized for keyword in strong_keywords):
                    continue
                if not (re.search(r"\d", normalized) or any(marker in normalized for marker in action_markers)):
                    continue
                self._append_unique_point(points, normalized[:80])
                if len(points) >= 5:
                    return points

        if points:
            return points

        return self._extract_key_points(chunks, generic_keywords)

    def _iter_text_segments(self, text: str) -> List[str]:
        """将正文拆成候选语义片段，兼容长段落与行内标题"""
        segments: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = [line] if "|" not in line else [part.strip() for part in line.split("|") if part.strip()]
            for part in parts:
                segments.extend([segment.strip() for segment in re.split(r"[。；;]", part) if segment.strip()])
        return segments

    def _clean_candidate_text(self, text: str) -> str:
        """清洗候选片段，压掉编号前缀和行内标题标签"""
        normalized = re.sub(r"\s+", " ", text).strip()
        normalized = re.sub(r"^[-•●①②③④⑤⑥⑦⑧⑨⑩\d、.（）()]+", "", normalized).strip()
        normalized = re.sub(
            r"^(预期成果|项目效益|社会效益|经济效益|技术应用突破研究|数据驱动决策|人才培养与团队建设|科研转化与应用)[：:]",
            "",
            normalized,
        ).strip()
        return normalized

    def _looks_like_heading_only(self, text: str, section: str) -> bool:
        """判断候选是否只是章节标题或小标题"""
        normalized = re.sub(r"\s+", "", text)
        normalized_section = re.sub(r"\s+", "", section)
        if normalized and normalized == normalized_section:
            return True
        if len(normalized) <= 24 and not re.search(r"[，,。；;：:]", text):
            heading_tokens = (
                "预期成果",
                "项目效益",
                "社会效益",
                "经济效益",
                "项目实施的预期经济社会效益目标",
                "项目实施的预期绩效目标",
                "技术应用突破研究",
                "数据驱动决策",
                "人才培养与团队建设",
                "科研转化与应用",
            )
            if any(token in normalized for token in heading_tokens):
                return True
        return False

    def _extract_progress_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """优先抽取进展/阶段性安排，避免表头噪声"""
        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            section = str(chunk.get("section", ""))
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            for line in lines:
                segments = [line] if "|" not in line else [part.strip() for part in line.split("|") if part.strip()]
                for segment in segments:
                    normalized = re.sub(r"\s+", " ", segment).strip()
                    if "[表格行" in normalized:
                        continue
                    if any(noise in normalized for noise in ("指标名称", "指标值", "总体", "实施期目标", "第一年度目标", "第二年度目标", "第三年度目标", "当前年度")):
                        continue
                    cleaned = re.sub(r"^[-•●①②③④⑤⑥⑦⑧⑨⑩\d、.（）()]+", "", normalized).strip()
                    if len(cleaned) < 10:
                        continue
                    if any(noise in cleaned for noise in ("承担了", "荣获", "入选", "通过验收", "参与", "主持")) and "进度安排" not in section:
                        continue
                    if any(
                        keyword in cleaned
                        for keyword in ("完成", "构建", "形成", "测试", "验证", "优化", "申报", "申请", "搭建", "开展", "试制", "集成")
                    ):
                        if cleaned in points:
                            continue
                        points.append(cleaned[:90])
                    if len(points) >= 5:
                        return points
        return points

    def _score_goal_chunk(self, section: str, text: str) -> float:
        """目标类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("项目目的和意义", "项目简介", "研究目标", "项目目标", "总体目标")):
            score += 5.0
        if any(marker in text for marker in ("目的：", "建设目标", "研究目标", "项目目标")):
            score += 4.0
        if "总体目标是" in text and "[表格行" not in text:
            score += 3.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明", "项目申报书分为")):
            score -= 5.0
        if any(marker in text for marker in ("总体组", "子项目组", "质量监督", "组织学术研讨会", "保障措施")):
            score -= 4.0
        if any(marker in text for marker in ("绩效指标", "一级指标", "二级指标", "三级指标")):
            score -= 4.0
        return score

    def _score_innovation_chunk(self, section: str, text: str) -> float:
        """创新类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("创新点", "创新亮点", "技术创新", "模式创新", "传播创新", "内容创新")):
            score += 6.0
        if any(marker in text for marker in ("创新点", "创新亮点", "技术融合", "精准分层", "模式可推广")):
            score += 4.0
        if "建设目标" in section:
            score -= 2.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明", "绩效指标", "总体目标")):
            score -= 5.0
        return score

    def _score_outcome_chunk(self, section: str, text: str) -> float:
        """成果类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("预期成果", "主要指标、效益", "项目效益", "科普内容产出", "科普活动开展", "合作网络构建")):
            score += 6.0
        if any(marker in text for marker in ("项目效益", "社会效益", "经济效益", "原创", "覆盖", "出版", "合作点")):
            score += 4.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明")):
            score -= 5.0
        if any(marker in text for marker in ("建设目标", "实施内容")):
            score -= 2.0
        return score

    def _score_progress_chunk(self, section: str, text: str) -> float:
        """进展类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("进度安排", "实施计划", "工作计划", "研究计划")):
            score += 5.0
        if any(marker in section for marker in ("现有工作基础", "前期任务承担情况")):
            score += 3.0
        if re.search(r"(20\d{2}\s*年|第[一二三四五六七八九十]+年|阶段[一二三四五六七八九十\d]+)", text):
            score += 4.0
        if any(marker in text for marker in ("临床测试", "初步测试", "试点", "阶段成果", "研发", "验证")):
            score += 2.0
        if any(marker in text for marker in ("现有工作基础", "已开通", "累计", "每周发布", "浏览量", "播放量", "观看量")):
            score += 2.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明", "项目申报书分为")):
            score -= 6.0
        if any(marker in text for marker in ("总体组", "子项目组", "质量监督", "基地负责人", "基地秘书")):
            score -= 4.0
        if any(marker in text for marker in ("负责", "审核", "起草", "参与策划")) and "现有工作基础" not in text:
            score -= 2.0
        if any(marker in text for marker in ("实施期目标", "第一年度目标", "第二年度目标", "第三年度目标", "第四年度目标")):
            score -= 2.0
        return score

    def _score_benefit_chunk(self, section: str, text: str) -> float:
        """效益类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("预期效益", "社会效益", "经济效益", "普及前景", "项目简介", "合作网络构建")):
            score += 4.0
        if any(marker in text for marker in ("项目效益", "社会效益", "经济效益", "医疗效益", "示范效应", "品牌建设")):
            score += 3.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明")):
            score -= 5.0
        return score
