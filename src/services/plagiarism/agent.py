"""查重服务 Agent

基于句子级比对 + 位置追溯的查重方案。
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from src.common.file_handler import get_parser


@dataclass
class DuplicateSegment:
    """重复片段"""
    text: str
    line_number: int
    source_docs: List[str] = field(default_factory=list)
    source_lines: List[int] = field(default_factory=list)


@dataclass
class DocumentSimilarity:
    """文档相似度"""
    doc_a: str
    doc_b: str
    similarity: float
    type: str  # "high", "medium", "low"
    total_chars: int
    duplicate_chars: int
    duplicate_segments: List[DuplicateSegment] = field(default_factory=list)


@dataclass
class PlagiarismResult:
    """查重结果"""
    id: str
    total_pairs: int
    high_similarity: List[dict]
    medium_similarity: List[dict]
    low_similarity: List[dict]
    processing_time: float


class TextComparator:
    """文本比对器 - 句子级精确匹配"""
    
    def __init__(
        self,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
    ):
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
    
    def compare(self, texts: Dict[str, str]) -> List[DocumentSimilarity]:
        """执行句子级比对
        
        步骤:
        1. 句子切分: 每个文档按换行切分
        2. 构建句子库: {句子: {doc_id: [line_numbers]}}
        3. 查找重复: 跨文档的相同句子
        4. 计算相似度: 重复字数 / 总字数
        """
        # Step 1: 句子切分
        sentence_map = {}  # {doc_id: [(line_no, text), ...]}
        for doc_id, text in texts.items():
            sentences = self._split_sentences(text)
            sentence_map[doc_id] = sentences
        
        # Step 2: 构建句子库
        # {text: {doc_id: [line_numbers]}}
        text_sources: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
        for doc_id, sentences in sentence_map.items():
            for line_no, text in sentences:
                text_sources[text][doc_id].append(line_no)
        
        # Step 3: 查找重复
        results = []
        doc_ids = list(texts.keys())
        
        for i, doc_a in enumerate(doc_ids):
            for doc_b in doc_ids[i+1:]:
                dup_segments = self._find_duplicates(
                    sentence_map[doc_a],
                    sentence_map[doc_b],
                    text_sources,
                    doc_b
                )
                
                # 计算相似度
                total_chars = len(texts[doc_a])
                dup_chars = sum(len(seg.text) for seg in dup_segments)
                similarity = dup_chars / total_chars if total_chars > 0 else 0
                
                results.append(DocumentSimilarity(
                    doc_a=doc_a,
                    doc_b=doc_b,
                    similarity=similarity,
                    type=self._classify(similarity),
                    total_chars=total_chars,
                    duplicate_chars=dup_chars,
                    duplicate_segments=dup_segments,
                ))
        
        return results
    
    def _split_sentences(self, text: str) -> List[Tuple[int, str]]:
        """按换行符切分成句子，返回 (行号, 文本)"""
        lines = text.split('\n')
        return [(i+1, line.strip()) for i, line in enumerate(lines) if line.strip()]
    
    def _find_duplicates(
        self,
        sentences_a: List[Tuple[int, str]],
        sentences_b: List[Tuple[int, str]],
        text_sources: Dict,
        doc_b: str,
    ) -> List[DuplicateSegment]:
        """查找两个文档间的重复句子"""
        duplicates = []
        texts_b = {text: line_no for line_no, text in sentences_b}
        
        for line_no_a, text_a in sentences_a:
            if text_a in texts_b:
                line_no_b = texts_b[text_a]
                duplicates.append(DuplicateSegment(
                    text=text_a,
                    line_number=line_no_a,
                    source_docs=[doc_b],
                    source_lines=[line_no_b],
                ))
        
        return duplicates
    
    def _classify(self, score: float) -> str:
        """根据相似度分类"""
        if score >= self.threshold_high:
            return "high"
        elif score >= self.threshold_medium:
            return "medium"
        return "low"


class PlagiarismAgent:
    """查重 Agent"""
    
    def __init__(
        self,
        threshold: float = 0.5,
        threshold_high: float = 0.8,
        threshold_medium: float = 0.5,
        skip_pages: int = 2,
        debug: bool = False,
    ):
        self.threshold = threshold
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.skip_pages = skip_pages
        self.debug = debug
        
        self.comparator = TextComparator(threshold_high, threshold_medium)
    
    async def check(
        self,
        files: List[tuple[str, bytes]],  # [(doc_id, file_data)]
    ) -> PlagiarismResult:
        """执行查重
        
        Args:
            files: 文件列表 [(id, data), ...]
            
        Returns:
            查重结果
        """
        start_time = time.time()
        
        # 1. 提取所有文本
        texts = {}
        for doc_id, file_data in files:
            try:
                # 检测文件类型
                file_type = self._detect_type_from_bytes(file_data)
                parser = get_parser(file_type)
                result = await parser.parse(file_data)
                
                # 跳过前 N 页
                if self.skip_pages > 0:
                    # 过滤掉前 skip_pages 页的内容
                    filtered_blocks = [
                        block for block in result.content.text_blocks
                        if block.page >= self.skip_pages
                    ]
                    # 重新构建文本
                    text = "\n".join(block.text for block in filtered_blocks)
                else:
                    text = result.content.to_text()
                
                texts[doc_id] = text
                print(f"[Plagiarism] 提取文本 {doc_id}: {len(text)} chars (跳过前{self.skip_pages}页)")
                
                # Debug: 保存解析结果
                if self.debug:
                    self._save_debug(doc_id, result, filtered_blocks if self.skip_pages > 0 else None)
            except Exception as e:
                print(f"[Plagiarism] 提取文本失败 {doc_id}: {e}")
                texts[doc_id] = ""
        
        if len(texts) < 2:
            return PlagiarismResult(
                id=f"plagiarism_{int(time.time() * 1000)}",
                total_pairs=0,
                high_similarity=[],
                medium_similarity=[],
                low_similarity=[],
                processing_time=time.time() - start_time,
            )
        
        # 2. 句子级比对
        results = self.comparator.compare(texts)
        print(f"[Plagiarism] 比对完成: {len(results)} 对")
        for r in results:
            print(f"  - {r.doc_a} vs {r.doc_b}: similarity={r.similarity:.4f}, type={r.type}")
        
        # 3. 过滤并分类
        high_sim = []
        medium_sim = []
        low_sim = []
        
        for r in results:
            print(f"[Plagiarism] 检查: similarity={r.similarity}, threshold={self.threshold}")
            if r.similarity >= self.threshold:
                result_dict = {
                    "doc_a": r.doc_a,
                    "doc_b": r.doc_b,
                    "similarity": round(r.similarity, 4),
                    "type": r.type,
                    "total_chars": r.total_chars,
                    "duplicate_chars": r.duplicate_chars,
                    "duplicate_segments": [
                        {
                            "text": seg.text,
                            "line_number": seg.line_number,
                            "source_docs": seg.source_docs,
                            "source_lines": seg.source_lines,
                        }
                        for seg in r.duplicate_segments[:10]  # 限制返回数量
                    ],
                }
                
                if r.type == "high":
                    high_sim.append(result_dict)
                elif r.type == "medium":
                    medium_sim.append(result_dict)
                else:
                    low_sim.append(result_dict)
        
        result = PlagiarismResult(
            id=f"plagiarism_{int(time.time() * 1000)}",
            total_pairs=len(results),
            high_similarity=high_sim,
            medium_similarity=medium_sim,
            low_similarity=low_sim,
            processing_time=time.time() - start_time,
        )
        
        print(f"[Plagiarism] 查重完成: {result.total_pairs} 对, 高相似度 {len(high_sim)} 对")
        
        return result
    
    def _detect_type_from_bytes(self, file_data: bytes) -> str:
        """根据文件数据检测类型"""
        if file_data[:4] == b'%PDF':
            return 'pdf'
        elif file_data[:4] == b'PK\x03\x04':  # docx 是 zip 格式
            return 'docx'
        else:
            return 'unknown'
    
    def _save_debug(self, doc_id: str, result, filtered_blocks=None):
        """保存 debug 结果"""
        import json
        import os
        from pathlib import Path
        
        debug_dir = Path("debug_plagiarism")
        debug_dir.mkdir(exist_ok=True)
        
        # 保存原始解析结果
        output = {
            "doc_id": doc_id,
            "pages": result.pages,
            "metadata": result.metadata,
            "text_blocks": [
                {"text": block.text[:200], "page": block.page}
                for block in result.content.text_blocks[:50]
            ],
        }
        
        if filtered_blocks is not None:
            output["filtered_blocks"] = [
                {"text": block.text[:200], "page": block.page}
                for block in filtered_blocks[:50]
            ]
        
        filename = debug_dir / f"{doc_id}_parse.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        print(f"[Plagiarism] Debug: 保存解析结果到 {filename}")
