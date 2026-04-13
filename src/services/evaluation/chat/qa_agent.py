"""聊天问答代理"""
import re
from typing import Any, Dict, List

from src.common.models.evaluation import ChatCitation, EvaluationChatAskResponse

from .indexer import ChatIndexer


class EvaluationQAAgent:
    """基于评审索引回答问题"""

    INNOVATION_NOISE_MARKERS = (
        "项目实施内容、技术路线及创新点",
        "项目预期的主要创新点",
        "围绕基础前沿、共性关键技术或应用试验等层面",
        "应包括该项创新的基本形态及其前沿性",
        "科学性、艺术性、先进性",
        "简述项目预期的主要创新点",
        "具体内容应包括",
    )

    def __init__(self, llm: Any = None, indexer: ChatIndexer | None = None):
        self.llm = llm
        self.indexer = indexer or ChatIndexer()

    async def ask(self, question: str, index_payload: Dict[str, Any]) -> EvaluationChatAskResponse:
        """回答专家问题并返回引用"""
        chunks = self.indexer.search(index_payload, question, top_k=5)
        chunks = self._rerank_chunks_for_question(question, chunks)
        chunks = self._filter_chunks_for_question(question, chunks)
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
            score = 0.0

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

        if any(token in question for token in ("创新点", "创新亮点", "技术创新", "模式创新", "创新性")):
            points = self._extract_innovation_points(chunks)
            if points:
                return f"文档披露的创新点主要包括：{'；'.join(points[:3])}。建议结合引用页码核验创新表述是否完整。"

        if any(token in question for token in ("预期成果", "成果产出", "成果和效益")):
            points = self._extract_outcome_points(chunks)
            if points:
                return f"文档披露的预期成果与效益主要包括：{'；'.join(points[:3])}。建议结合引用页码核验量化指标与原文细节。"

        if any(token in question for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的")):
            points = self._extract_goal_points(chunks)
            if points:
                primary = points[:1] if len(points[0]) >= 40 else points[:3]
                return f"文档中可识别的研究目标主要包括：{'；'.join(primary)}。建议结合引用页码进一步核验完整表述。"

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
