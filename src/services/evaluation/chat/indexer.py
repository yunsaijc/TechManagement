"""聊天索引器"""
import re
from typing import Any, Dict, List


class ChatIndexer:
    """基于页码切片构建可检索索引"""

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
        keywords = self._tokenize(query)
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

            scored.append({"score": overlap, "chunk": chunk})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return [item["chunk"] for item in scored[:top_k]]

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
