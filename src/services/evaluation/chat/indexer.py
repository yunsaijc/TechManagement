"""聊天索引器"""
import re
from typing import Any, Dict, List


class ChatIndexer:
    """基于页码切片构建可检索索引"""

    NOISE_SECTION_PATTERNS = (
        "附件",
        "项目组主要成员",
        "项目基本信息",
        "合作协议",
        "国际合作",
        "填报说明",
    )
    INTENT_SECTION_AVOID = {
        "创新点": (
            "填报说明",
            "项目组主要成员",
            "项目组织实施机制",
            "项目绩效评价考核目标及指标",
        ),
        "预期成果": ("填报说明", "项目组主要成员"),
        "研究目标": (
            "填报说明",
            "项目组织实施机制",
            "组织实施",
            "保障措施",
            "风险分析",
            "项目绩效评价考核目标及指标",
            "项目研究方法",
            "技术路线",
            "负责人及项目主要骨干人员",
            "申报单位相关科研条件状况",
            "合作单位的选择原因及其优势",
            "项目组主要成员",
        ),
        "进展程度": (
            "填报说明",
            "项目组织实施机制",
            "组织实施",
            "项目组主要成员",
            "国外研究现状及趋势",
            "国内研究现状及趋势",
            "申报单位相关科研条件状况",
            "合作单位的选择原因及其优势",
            "项目简介",
            "项目目的和意义",
            "直接费用",
            "间接费用",
            "自筹资金",
        ),
        "预期效益": ("填报说明", "项目组主要成员"),
        "验证数据": ("填报说明", "项目组主要成员"),
        "量产可能性": ("填报说明", "项目组主要成员"),
    }
    INTENT_SECTION_HINTS = {
        "创新点": ("创新点", "创新亮点", "技术创新", "模式创新", "传播创新", "内容创新"),
        "预期成果": ("预期成果", "主要指标、效益", "项目效益", "科普内容产出", "科普活动开展", "合作网络构建"),
        "研究目标": ("研究目标", "项目目标", "总体目标", "建设目标", "项目目的和意义", "项目简介"),
        "预期效益": ("预期效益", "项目效益", "社会效益", "经济效益", "普及前景", "项目简介", "合作网络构建"),
        "验证数据": ("技术路线", "研究方法", "可行性", "预期成果", "绩效评价考核目标及指标", "项目绩效评价考核目标及指标"),
        "进展程度": ("进度安排", "实施计划", "工作计划", "研究计划", "现有工作基础", "前期任务承担情况"),
        "量产可能性": ("经济效益", "项目效益", "成果转化", "应用示范", "产业化", "项目简介", "普及前景"),
    }
    INTENT_SECTION_STRONG_ALLOW = {
        "创新点": ("创新点", "创新亮点", "技术创新", "模式创新", "传播创新", "内容创新"),
        "预期成果": ("预期成果", "主要指标、效益", "项目效益", "科普内容产出", "科普活动开展"),
        "研究目标": (
            "项目简介",
            "项目目的和意义",
            "研究目标",
            "项目目标",
            "总体目标",
            "项目实施的预期经济社会效益目标",
        ),
        "进展程度": (
            "进度安排",
            "实施计划",
            "工作计划",
            "研究计划",
            "现有工作基础",
            "前期任务承担情况",
        ),
    }
    INTENT_QUERY_HINTS = {
        "创新点": ("创新点", "创新", "创新亮点", "技术创新", "模式创新", "特色"),
        "预期成果": ("预期成果", "成果", "指标", "产出", "目标", "效益"),
        "研究目标": ("研究目标", "项目目标", "总体目标", "建设目标", "研究目的", "目的："),
        "预期效益": ("预期效益", "项目效益", "社会效益", "经济效益", "效益"),
        "验证数据": ("验证", "数据", "试验", "测试", "指标", "考核"),
        "进展程度": ("进展", "阶段", "计划", "进度", "实施"),
        "量产可能性": ("量产", "产业化", "推广", "应用", "转化", "示范"),
    }
    GENERIC_QUERY_STOPWORDS = {
        "这个项目的研究目标是什么？",
        "这个项目的研究目标是什么",
        "这项工作目前进展到什么程度了？",
        "这项工作目前进展到什么程度了",
        "这个项目",
        "这项工作",
        "项目",
        "工作",
        "研究",
        "什么",
        "目前",
        "程度",
        "这个",
        "这项",
    }
    CHUNK_MAX_CHARS = 220

    def build(self, evaluation_id: str, page_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建索引载荷"""
        indexed_chunks: List[Dict[str, Any]] = []
        for chunk in page_chunks:
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            sub_chunks = self._split_chunk(
                text=text,
                section=str(chunk.get("section", "")),
            )
            for sub_chunk in sub_chunks:
                indexed_chunks.append(
                    {
                        "id": len(indexed_chunks) + 1,
                        "file": str(chunk.get("file", "")),
                        "page": int(chunk.get("page", 0) or 0),
                        "section": str(chunk.get("section", "")),
                        "chunk_type": sub_chunk["chunk_type"],
                        "text": sub_chunk["text"],
                        "tokens": self._tokenize(sub_chunk["text"]),
                    }
                )

        return {
            "evaluation_id": evaluation_id,
            "chunks": indexed_chunks,
            "chunk_count": len(indexed_chunks),
        }

    def search(self, index_payload: Dict[str, Any], query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索最相关切片"""
        intent = self._detect_intent(query)
        keywords = self._expand_query_keywords(query, intent)
        if not keywords:
            return []

        chunks = index_payload.get("chunks", [])
        scored: List[Dict[str, Any]] = []

        for chunk in chunks:
            tokens = set(chunk.get("tokens", []))
            if not tokens:
                continue
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))
            chunk_type = str(chunk.get("chunk_type", "paragraph"))

            overlap = sum(1 for keyword in keywords if keyword in tokens)
            if overlap <= 0:
                overlap = sum(1 for keyword in keywords if keyword in text)
            if overlap <= 0:
                overlap = sum(1 for keyword in keywords if keyword in section)
            if overlap <= 0 and intent and self._has_direct_intent_evidence(intent, section, text):
                overlap = 1
            if overlap <= 0:
                continue

            score = float(overlap)

            if self._is_noise_chunk(section, text):
                score -= 2.5
            if chunk_type == "table":
                score -= 3.0
            if chunk_type == "header":
                score -= 1.0
            if intent and self._section_matches_intent(section, intent):
                score += 3.0
            if intent and self._section_strongly_matches_intent(section, intent):
                score += 5.0
            if intent and self._section_should_avoid(section, intent):
                score -= 3.5
            if intent and any(hint in text for hint in self.INTENT_QUERY_HINTS.get(intent, ())):
                score += 1.5
            if intent and self._has_direct_intent_evidence(intent, section, text):
                score += 3.0
            if intent and not self._has_direct_intent_evidence(intent, section, text):
                score -= 4.0
            if section and section in query:
                score += 2.0
            if intent == "研究目标" and self._looks_like_kpi_table(text):
                score -= 4.0
            if intent == "进展程度" and self._looks_like_goal_table(text):
                score -= 3.0

            if score <= 0:
                continue

            scored.append({"score": score, "chunk": chunk})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return [item["chunk"] for item in scored[:top_k]]

    def _detect_intent(self, query: str) -> str:
        """识别问题意图"""
        if any(token in query for token in ("创新点", "创新亮点", "技术创新", "模式创新", "创新性")):
            return "创新点"
        if any(token in query for token in ("预期成果", "成果产出", "成果和效益")):
            return "预期成果"
        if any(token in query for token in ("研究目标", "项目目标", "总体目标", "建设目标", "目的")):
            return "研究目标"
        if any(token in query for token in ("预期效益", "效益", "收益", "价值")):
            return "预期效益"
        if any(token in query for token in ("验证数据", "数据", "试验", "测试", "样本")):
            return "验证数据"
        if any(token in query for token in ("量产", "产业化", "成果转化", "推广应用", "可推广")):
            return "量产可能性"
        if any(token in query for token in ("进展", "进度", "阶段", "做到什么程度", "量产")):
            return "进展程度"
        return ""

    def _expand_query_keywords(self, query: str, intent: str) -> List[str]:
        """扩展问题关键词，改善召回"""
        keywords = [token for token in self._tokenize(query) if token not in self.GENERIC_QUERY_STOPWORDS]
        for hint in self.INTENT_QUERY_HINTS.get(intent, ()):
            if hint not in keywords:
                keywords.append(hint)
        return keywords

    def _is_noise_chunk(self, section: str, text: str) -> bool:
        """判断噪声切片，避免附件/表格页误召回"""
        if any(pattern in section for pattern in self.NOISE_SECTION_PATTERNS):
            return True
        noise_markers = ("[表格行", "填 报 说 明", "填报说明", "附件目录", "拟使用数量")
        return sum(1 for marker in noise_markers if marker in text) >= 2

    def _section_matches_intent(self, section: str, intent: str) -> bool:
        """判断章节是否符合问题意图"""
        return any(hint in section for hint in self.INTENT_SECTION_HINTS.get(intent, ()))

    def _section_should_avoid(self, section: str, intent: str) -> bool:
        """判断章节是否应在当前意图下降权"""
        return any(hint in section for hint in self.INTENT_SECTION_AVOID.get(intent, ()))

    def _section_strongly_matches_intent(self, section: str, intent: str) -> bool:
        """判断章节是否属于当前意图的强白名单"""
        return any(hint in section for hint in self.INTENT_SECTION_STRONG_ALLOW.get(intent, ()))

    def _looks_like_kpi_table(self, text: str) -> bool:
        """识别绩效目标/指标类表格，避免目标问答被表格切片带偏"""
        markers = ("[表格行", "绩效指标", "指标值", "一级指标", "二级指标", "三级指标", "考核目标")
        return sum(1 for marker in markers if marker in text) >= 2

    def _looks_like_goal_table(self, text: str) -> bool:
        """识别年度目标表格，避免进展问答被目标表格冒充真实进展"""
        markers = ("[表格行", "实施期目标", "第一年度目标", "第二年度目标", "第三年度目标", "第四年度目标")
        return sum(1 for marker in markers if marker in text) >= 2

    def _has_direct_intent_evidence(self, intent: str, section: str, text: str) -> bool:
        """判断切片是否具备当前意图的直接证据"""
        if intent == "创新点":
            if any(marker in section for marker in ("创新点", "创新亮点", "技术创新", "模式创新", "传播创新", "内容创新")):
                return True
            return bool(re.search(r"(创新点|创新亮点|技术创新|模式创新|传播创新|内容创新)", text))

        if intent == "预期成果":
            if any(marker in section for marker in ("预期成果", "主要指标、效益", "项目效益", "科普内容产出", "科普活动开展")):
                return True
            return bool(re.search(r"(预期成果|项目效益|社会效益|经济效益|主要指标|原创.*作品|覆盖.*人次)", text))

        if intent == "研究目标":
            if any(marker in section for marker in ("研究目标", "项目目标", "总体目标", "建设目标", "项目目的和意义")):
                return True
            return bool(re.search(r"(研究目标|项目目标|总体\s*目标|建设目标|(?:^|\n)研究目的[：:]?|目的：)", text))

        if intent == "进展程度":
            if self._section_matches_intent(section, intent):
                return True
            return bool(
                re.search(
                    r"((20\d{2}\s*年|第[一二三四五六七八九十]+年|阶段[一二三四五六七八九十\d]+).{0,24}(完成|开展|推进|测试|试点|形成|优化|建设))|(进度|节点|目前|现有|前期|已完成|累计)",
                    text,
                )
            )

        return True

    def _split_chunk(self, text: str, section: str) -> List[Dict[str, str]]:
        """将整页文本切成更细粒度的段落级索引块"""
        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_lines:
            return []

        chunks: List[Dict[str, str]] = []
        current_lines: List[str] = []
        current_type = "paragraph"

        for line in raw_lines:
            line_type = self._classify_line(line, section)
            if line_type != current_type or self._joined_len(current_lines, line) > self.CHUNK_MAX_CHARS:
                if current_lines:
                    chunks.append(
                        {
                            "chunk_type": current_type,
                            "text": "\n".join(current_lines).strip(),
                        }
                    )
                current_lines = [line]
                current_type = line_type
                continue
            current_lines.append(line)

        if current_lines:
            chunks.append(
                {
                    "chunk_type": current_type,
                    "text": "\n".join(current_lines).strip(),
                }
            )

        return [item for item in chunks if item["text"]]

    def _classify_line(self, line: str, section: str) -> str:
        """粗分类切片类型"""
        if "[表格行" in line or "[表格表头" in line or "|" in line:
            return "table"
        if any(marker in line for marker in ("填报说明", "填 报 说 明", "项目申报书分为")):
            return "instruction"
        if line == section or re.fullmatch(r"[一二三四五六七八九十0-9（）()、.．A-Za-z\s]{1,24}", line):
            return "header"
        return "paragraph"

    def _joined_len(self, current_lines: List[str], new_line: str) -> int:
        """估算追加一行后的长度"""
        if not current_lines:
            return len(new_line)
        return len("\n".join(current_lines)) + 1 + len(new_line)

    def _tokenize(self, text: str) -> List[str]:
        """简易分词"""
        raw_tokens = [part.strip() for part in re.split(r"[，,。；;：:\s\n]+", text) if part.strip()]
        tokens: List[str] = []

        for token in raw_tokens:
            if len(token) >= 2:
                tokens.append(token)
            if self._contains_chinese(token) and len(token) >= 4:
                tokens.extend(self._cjk_ngrams(token, size=2))

        deduplicated: List[str] = []
        for token in tokens:
            if token in deduplicated:
                continue
            deduplicated.append(token)

        return deduplicated[:120]

    def _contains_chinese(self, text: str) -> bool:
        """判断是否包含中文"""
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _cjk_ngrams(self, text: str, size: int) -> List[str]:
        """生成中文 n-gram"""
        compact = text.strip()
        if len(compact) < size:
            return []
        return [compact[i : i + size] for i in range(0, len(compact) - size + 1)]
