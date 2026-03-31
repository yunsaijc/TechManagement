"""聊天问答代理"""
import re
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
        chunks = self._rerank_chunks_for_question(question, chunks)
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

    def _rerank_chunks_for_question(self, question: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """根据问题类型对已召回切片做二次排序，压制说明页与组织管理噪声"""
        if not chunks:
            return chunks

        ranked: List[tuple[float, Dict[str, Any]]] = []
        for chunk in chunks:
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))
            score = 0.0

            if any(token in question for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的")):
                score += self._score_goal_chunk(section, text)
            elif any(token in question for token in ("进展", "进度", "阶段", "做到什么程度")):
                score += self._score_progress_chunk(section, text)
            elif any(token in question for token in ("预期效益", "效益", "收益", "价值")):
                score += self._score_benefit_chunk(section, text)

            ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in ranked]

    async def _generate_answer(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        """基于证据生成回答"""
        if not self.llm:
            return self._build_fallback_answer(question, chunks)

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

        try:
            response = await self.llm.ainvoke(prompt)
        except Exception:
            return self._build_fallback_answer(question, chunks)

        text = response.content if hasattr(response, "content") else str(response)
        return text.strip() or self._build_fallback_answer(question, chunks)

    def _build_fallback_answer(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        """无模型时的回退回答"""
        first = chunks[0]
        section = str(first.get("section", "相关章节"))
        snippet = str(first.get("text", "")).replace("\n", " ").strip()
        snippet = snippet[:120] + ("..." if len(snippet) > 120 else "")

        if any(token in question for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的")):
            points = self._extract_goal_points(chunks)
            if points:
                return f"文档中可识别的研究目标主要包括：{'；'.join(points[:3])}。建议结合引用页码进一步核验完整表述。"

        if any(token in question for token in ("预期效益", "效益", "收益", "价值")):
            points = self._extract_key_points(chunks, ("社会效益", "经济效益", "医疗效益", "效益", "前景"))
            if points:
                return f"文档披露的预期效益主要包括：{'；'.join(points[:3])}。建议结合引用页码核验原文细节。"

        if "验证" in question and "数据" in question:
            return (
                f"当前仅从{section}检索到相关正文内容，未能直接定位到明确的验证数据章节。"
                f"可先参考已命中的页码证据继续核验：{snippet}"
            )

        if any(token in question for token in ("进展", "进度", "阶段", "做到什么程度")):
            points = self._extract_progress_points(chunks)
            if points:
                return f"从当前命中的正文看，项目进展/阶段性安排主要包括：{'；'.join(points[:3])}。建议结合引用页码继续核验时间节点与完成度。"

        if any(token in question for token in ("量产", "产业化", "成果转化", "推广应用", "可推广")):
            points = self._extract_key_points(chunks, ("经济效益", "成果转化", "示范", "推广", "应用", "品牌建设"))
            if points:
                return f"从当前命中的正文看，项目更接近应用推广/示范落地方向，相关依据包括：{'；'.join(points[:3])}。是否具备严格意义上的量产条件，文档未给出直接生产制造证据，需谨慎判断。"
            return (
                f"当前仅从{section}检索到与应用推广相关的正文内容，未直接定位到明确的量产或产业化实施证据。"
                f"可先参考已命中的页码证据继续核验：{snippet}"
            )

        return (
            f"根据{section}相关内容，文档存在与该问题相关的表述。"
            f"建议结合引用页码继续核验，当前命中内容为：{snippet}"
        )

    def _extract_key_points(self, chunks: List[Dict[str, Any]], keywords: tuple[str, ...]) -> List[str]:
        """从命中的正文切片中抽取关键条目"""
        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            for line in lines:
                normalized = re.sub(r"\s+", " ", line)
                normalized = re.sub(r"^[-•●①②③④⑤⑥⑦⑧⑨⑩\d、.（）()]+", "", normalized).strip()
                if len(normalized) < 8:
                    continue
                if "[表格行" in normalized:
                    continue
                if not any(keyword in normalized for keyword in keywords):
                    continue
                if normalized in points:
                    continue
                points.append(normalized[:60])
                if len(points) >= 5:
                    return points
        return points

    def _extract_goal_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """优先抽取目标/目的类条目，避免混入实施内容"""
        points: List[str] = []
        capture = False

        for chunk in chunks:
            text = str(chunk.get("text", ""))
            lines = [line.strip() for line in text.splitlines() if line.strip()]
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
                if cleaned in points:
                    continue
                points.append(cleaned[:60])
                if len(points) >= 5:
                    return points

        return points

    def _extract_progress_points(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """优先抽取进展/阶段性安排，避免表头噪声"""
        points: List[str] = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
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
                    if any(keyword in cleaned for keyword in ("举办", "创作", "打造", "融入", "展出", "开放", "开展")):
                        if cleaned in points:
                            continue
                        points.append(cleaned[:70])
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

    def _score_progress_chunk(self, section: str, text: str) -> float:
        """进展类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("进度安排", "实施计划", "工作计划", "研究计划")):
            score += 5.0
        if re.search(r"(20\d{2}\s*年|第[一二三四五六七八九十]+年|阶段[一二三四五六七八九十\d]+)", text):
            score += 4.0
        if any(marker in text for marker in ("临床测试", "初步测试", "试点", "阶段成果", "研发", "验证")):
            score += 2.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明", "项目申报书分为")):
            score -= 6.0
        if any(marker in text for marker in ("总体组", "子项目组", "质量监督", "基地负责人", "基地秘书")):
            score -= 4.0
        if any(marker in text for marker in ("实施期目标", "第一年度目标", "第二年度目标", "第三年度目标", "第四年度目标")):
            score -= 2.0
        return score

    def _score_benefit_chunk(self, section: str, text: str) -> float:
        """效益类问题的切片重排评分"""
        score = 0.0
        if any(marker in section for marker in ("预期效益", "社会效益", "经济效益", "普及前景", "项目简介")):
            score += 4.0
        if any(marker in text for marker in ("社会效益", "经济效益", "医疗效益", "示范效应", "品牌建设")):
            score += 3.0
        if any(marker in text for marker in ("填报说明", "填 报 说 明")):
            score -= 5.0
        return score
