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
    )
    INTENT_SECTION_HINTS = {
        "研究目标": ("研究目标", "项目目标", "总体目标", "建设目标", "项目目的和意义", "项目简介"),
        "预期效益": ("预期效益", "项目效益", "社会效益", "经济效益", "普及前景", "项目简介", "合作网络构建"),
        "验证数据": ("技术路线", "研究方法", "可行性", "预期成果", "绩效评价考核目标及指标", "项目绩效评价考核目标及指标"),
        "进展程度": ("进度安排", "实施计划", "工作计划", "项目绩效评价考核目标及指标"),
        "量产可能性": ("经济效益", "项目效益", "成果转化", "应用示范", "产业化", "项目简介", "普及前景"),
    }
    INTENT_QUERY_HINTS = {
        "研究目标": ("研究目标", "项目目标", "总体目标", "建设目标", "目的"),
        "预期效益": ("预期效益", "项目效益", "社会效益", "经济效益", "效益"),
        "验证数据": ("验证", "数据", "试验", "测试", "指标", "考核"),
        "进展程度": ("进展", "阶段", "计划", "进度", "实施"),
        "量产可能性": ("量产", "产业化", "推广", "应用", "转化", "示范"),
    }

    def build(self, evaluation_id: str, page_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构建索引载荷"""
        indexed_chunks: List[Dict[str, Any]] = []
        for chunk in page_chunks:
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            indexed_chunks.append(
                {
                    "id": int(chunk.get("id", len(indexed_chunks) + 1) or len(indexed_chunks) + 1),
                    "file": str(chunk.get("file", "")),
                    "page": int(chunk.get("page", 0) or 0),
                    "section": str(chunk.get("section", "")),
                    "text": text,
                    "tokens": self._tokenize(text),
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

            overlap = sum(1 for keyword in keywords if keyword in tokens)
            if overlap <= 0:
                text = str(chunk.get("text", ""))
                overlap = sum(1 for keyword in keywords if keyword in text)
            if overlap <= 0:
                continue

            score = float(overlap)
            section = str(chunk.get("section", ""))
            text = str(chunk.get("text", ""))

            if self._is_noise_chunk(section, text):
                score -= 2.5
            if intent and self._section_matches_intent(section, intent):
                score += 3.0
            if intent and any(hint in text for hint in self.INTENT_QUERY_HINTS.get(intent, ())):
                score += 1.5
            if section and section in query:
                score += 2.0

            if score <= 0:
                continue

            scored.append({"score": score, "chunk": chunk})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return [item["chunk"] for item in scored[:top_k]]

    def _detect_intent(self, query: str) -> str:
        """识别问题意图"""
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
        keywords = self._tokenize(query)
        for hint in self.INTENT_QUERY_HINTS.get(intent, ()):
            if hint not in keywords:
                keywords.append(hint)
        return keywords

    def _is_noise_chunk(self, section: str, text: str) -> bool:
        """判断噪声切片，避免附件/表格页误召回"""
        if any(pattern in section for pattern in self.NOISE_SECTION_PATTERNS):
            return True
        noise_markers = ("[表格行", "填 报 说 明", "附件目录", "拟使用数量")
        return sum(1 for marker in noise_markers if marker in text) >= 2

    def _section_matches_intent(self, section: str, intent: str) -> bool:
        """判断章节是否符合问题意图"""
        return any(hint in section for hint in self.INTENT_SECTION_HINTS.get(intent, ()))

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
