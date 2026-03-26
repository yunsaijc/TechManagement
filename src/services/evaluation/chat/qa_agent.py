"""聊天问答代理"""
from typing import Any, Dict, List

from src.common.models.evaluation import ChatCitation, EvaluationChatAskResponse

from .indexer import ChatIndexer


class EvaluationQAAgent:
    """基于评审索引回答问题"""

    def __init__(self, llm: Any = None, indexer: ChatIndexer | None = None):
        self.llm = llm
        self.indexer = indexer or ChatIndexer()

    async def ask(self, question: str, index_payload: Dict[str, Any]) -> EvaluationChatAskResponse:
        """回答专家问题并返回引用"""
        chunks = self.indexer.search(index_payload, question, top_k=5)
        citations = [
            ChatCitation(
                file=str(chunk.get("file", "")),
                page=int(chunk.get("page", 0) or 0),
                snippet=str(chunk.get("text", ""))[:180],
            )
            for chunk in chunks[:3]
        ]

        if not chunks:
            return EvaluationChatAskResponse(
                answer="当前未检索到可支撑该问题的正文证据，请补充材料或换一个更具体的问题。",
                citations=[],
            )

        answer = await self._generate_answer(question, chunks)
        return EvaluationChatAskResponse(answer=answer, citations=citations)

    async def _generate_answer(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        """基于证据生成回答"""
        if not self.llm:
            return self._build_fallback_answer(chunks)

        evidence_text = "\n\n".join(
            [
                f"[页码{chunk.get('page', 0)}] {str(chunk.get('text', ''))[:300]}"
                for chunk in chunks[:4]
            ]
        )

        prompt = (
            "你是科技项目评审助手。"
            "请仅根据给定证据回答问题，不要编造。"
            "若证据不足请明确说明。\n\n"
            f"问题：{question}\n\n"
            f"证据：\n{evidence_text}\n\n"
            "请输出80~180字中文回答。"
        )

        response = await self.llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        return text.strip() or self._build_fallback_answer(chunks)

    def _build_fallback_answer(self, chunks: List[Dict[str, Any]]) -> str:
        """无模型时的回退回答"""
        first = chunks[0]
        section = str(first.get("section", "相关章节"))
        return (
            f"根据{section}相关内容，文档给出了与问题相关的信息，"
            "建议结合引用页码进一步核验关键数据与可量产性结论。"
        )
