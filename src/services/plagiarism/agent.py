"""查重服务 Agent

基于句子级比对 + 位置追溯的查重方案。
"""
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.common.file_handler import get_parser
from src.services.plagiarism.section_extractor import SectionExtractor


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
        section_config: Optional[Dict] = None,
        debug: bool = False,
    ):
        self.threshold = threshold
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.debug = debug
        
        # 初始化 Section 提取器
        if section_config and SectionExtractor.validate_config(section_config):
            self.section_extractor = SectionExtractor(section_config)
        else:
            self.section_extractor = None
        
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
        # section_config 只对第一个文档（主动查询的文档）生效
        # 其他文档（全量比对库）使用全文
        texts = {}
        
        doc_ids = [doc_id for doc_id, _ in files]
        primary_doc_id = doc_ids[0] if doc_ids else None
        
        for idx, (doc_id, file_data) in enumerate(files):
            try:
                # 检测文件类型
                file_type = self._detect_type_from_bytes(file_data)
                parser = get_parser(file_type)
                result = await parser.parse(file_data)
                
                # 提取全部文本
                full_text = result.content.to_text()
                
                # 只有第一个文档使用 section 提取配置
                if idx == 0 and self.section_extractor:
                    # 提取 section 区域
                    text = self.section_extractor.extract(full_text)
                    # 过滤模板内容
                    text = self.section_extractor.filter_template_content(text)
                else:
                    # 其他文档使用全文
                    text = full_text
                
                texts[doc_id] = text
                print(f"[Plagiarism] 提取文本 {doc_id}: {len(text)} chars")
                
                # Debug: 保存解析结果
                if self.debug:
                    is_primary = (doc_id == primary_doc_id)
                    self._save_debug(doc_id, result, full_text, text if is_primary else None, is_primary)
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
        
        # 记录主文档文本用于定位 section
        primary_text = texts.get(primary_doc_id, "") if primary_doc_id else ""
        
        # 3. 过滤并分类
        high_sim = []
        medium_sim = []
        low_sim = []
        
        for r in results:
            print(f"[Plagiarism] 检查: similarity={r.similarity}, threshold={self.threshold}")
            if r.similarity >= self.threshold:
                # 为每个重复片段添加详细信息
                enhanced_segments = []
                for seg in r.duplicate_segments[:20]:
                    # 获取原文该行的内容
                    primary_line_content = ""
                    if primary_doc_id and primary_doc_id in texts:
                        primary_lines = texts[primary_doc_id].split('\n')
                        if 0 < seg.line_number <= len(primary_lines):
                            primary_line_content = primary_lines[seg.line_number - 1]
                    
                    # 获取来源文档该行的内容
                    source_contents = []
                    for src_doc, src_line in zip(seg.source_docs, seg.source_lines):
                        if src_doc in texts:
                            src_lines = texts[src_doc].split('\n')
                            if 0 < src_line <= len(src_lines):
                                source_contents.append({
                                    "doc": src_doc,
                                    "line": src_line,
                                    "text": src_lines[src_line - 1]
                                })
                    
                    enhanced_segments.append({
                        "primary_line": seg.line_number,
                        "primary_text": primary_line_content,
                        "sources": source_contents,
                    })
                
                result_dict = {
                    "doc_a": r.doc_a,
                    "doc_b": r.doc_b,
                    "similarity": round(r.similarity, 4),
                    "type": r.type,
                    "total_chars": r.total_chars,
                    "duplicate_chars": r.duplicate_chars,
                    "duplicate_segments": enhanced_segments,
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
        
        # 保存 debug 信息
        if self.debug and primary_doc_id:
            self._save_plagiarism_debug(doc_ids, texts, primary_doc_id, results)
            
        
        return result
    
    def _detect_type_from_bytes(self, file_data: bytes) -> str:
        """根据文件数据检测类型"""
        if file_data[:4] == b'%PDF':
            return 'pdf'
        elif file_data[:4] == b'PK\x03\x04':  # docx 是 zip 格式
            return 'docx'
        else:
            return 'unknown'
    
    def _save_debug(self, doc_id: str, result, full_text: str = "", extracted_text: str = "", is_primary: bool = False):
        """保存 debug 结果
        
        Args:
            doc_id: 文档 ID
            result: 解析结果
            full_text: 完整文本
            extracted_text: 提取后的文本（仅主文档有）
            is_primary: 是否是主文档（第一个上传的文档）
        """
        import json
        from pathlib import Path
        
        debug_dir = Path("debug_plagiarism")
        debug_dir.mkdir(exist_ok=True)
        
        output = {
            "doc_id": doc_id,
            "is_primary": is_primary,
            "metadata": result.metadata,
        }
        
        # 保存全文预览
        if full_text:
            output["full_text_preview"] = full_text[:3000]
        
        # 只对主文档保存 section 提取结果
        if is_primary and extracted_text and self.section_extractor:
            sections = self.section_extractor.sections
            output["sections"] = []
            
            current_pos = 0
            for i, section in enumerate(sections):
                start_pattern = section.get("start_pattern", "")
                end_pattern = section.get("end_pattern")
                
                start_regex = re.compile(start_pattern)
                start_match = start_regex.search(extracted_text)
                
                if start_match:
                    start_pos = start_match.start()
                    
                    if end_pattern:
                        end_regex = re.compile(end_pattern)
                        end_match = end_regex.search(extracted_text[start_pos + 1:])
                        if end_match:
                            end_pos = start_pos + 1 + end_match.start()
                        else:
                            end_pos = len(extracted_text)
                    else:
                        end_pos = len(extracted_text)
                    
                    section_text = extracted_text[start_pos:end_pos].strip()
                    
                    output["sections"].append({
                        "name": section.get("name", f"section_{i}"),
                        "char_count": len(section_text),
                        "text": section_text,
                    })
        
        filename = debug_dir / f"{doc_id}_parse.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        print(f"[Plagiarism] Debug: 保存解析结果到 {filename}")
    
    def _save_plagiarism_debug(self, doc_ids: List[str], texts: Dict[str, str], primary_doc_id: str, results: List):
        """保存查重详细debug信息"""
        import json
        from pathlib import Path
        
        debug_dir = Path("debug_plagiarism")
        debug_dir.mkdir(exist_ok=True)
        
        # 获取主文档文本和section信息
        primary_text = texts.get(primary_doc_id, "")
        
        output = {
            "primary_doc": primary_doc_id,
            "total_docs": len(doc_ids),
            "text_lengths": {doc_id: len(text) for doc_id, text in texts.items()},
        }
        
        # 如果有 section 配置，保存每个 section 的范围
        if self.section_extractor:
            sections_info = []
            for section in self.section_extractor.sections:
                start_pattern = section.get("start_pattern", "")
                end_pattern = section.get("end_pattern")
                
                start_regex = re.compile(start_pattern)
                start_match = start_regex.search(primary_text)
                
                if start_match:
                    start_pos = start_match.start()
                    if end_pattern:
                        end_regex = re.compile(end_pattern)
                        end_match = end_regex.search(primary_text[start_pos + 1:])
                        if end_match:
                            end_pos = start_pos + 1 + end_match.start()
                        else:
                            end_pos = len(primary_text)
                    else:
                        end_pos = len(primary_text)
                    
                    # 计算行号范围
                    section_text = primary_text[start_pos:end_pos]
                    lines = section_text.split('\n')
                    start_line = primary_text[:start_pos].count('\n') + 1
                    end_line = start_line + len(lines) - 1
                    
                    sections_info.append({
                        "name": section.get("name", ""),
                        "start_line": start_line,
                        "end_line": end_line,
                        "char_count": len(section_text),
                    })
            
            output["sections_info"] = sections_info
        
        # 保存重复片段详情
        duplicate_segments = []
        for r in results:
            for seg in r.duplicate_segments[:20]:
                # 获取原文该行的内容
                primary_line_content = ""
                primary_lines = primary_text.split('\n')
                if 0 < seg.line_number <= len(primary_lines):
                    primary_line_content = primary_lines[seg.line_number - 1]
                
                # 获取来源文档该行的内容
                source_contents = []
                for src_doc, src_line in zip(seg.source_docs, seg.source_lines):
                    if src_doc in texts:
                        src_lines = texts[src_doc].split('\n')
                        if 0 < src_line <= len(src_lines):
                            source_contents.append({
                                "doc": src_doc,
                                "line": src_line,
                                "text": src_lines[src_line - 1]
                            })
                
                duplicate_segments.append({
                    "primary_line": seg.line_number,
                    "primary_text": primary_line_content,
                    "sources": source_contents,
                    "similarity_pair": f"{r.doc_a} vs {r.doc_b}"
                })
        
        output["duplicate_segments"] = duplicate_segments
        
        filename = debug_dir / "plagiarism_debug.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        print(f"[Plagiarism] Debug: 保存查重详情到 {filename}")
    
    def _find_section_for_line(self, line_number: int, text: str) -> str:
        """根据行号查找对应的 section 名称
        
        Args:
            line_number: 行号
            text: 完整文本
            
        Returns:
            section 名称
        """
        if not self.section_extractor:
            return "全文"
        
        # 按行统计位置
        lines = text.split('\n')
        current_pos = 0
        line_start_pos = 0
        
        for i, line in enumerate(lines[:line_number]):
            # 找到目标行的起始位置
            if i == line_number - 1:
                line_start_pos = current_pos
                break
            current_pos += len(line) + 1  # +1 for newline
        
        # 查找该位置属于哪个 section
        sections = self.section_extractor.sections
        for section in sections:
            start_pattern = section.get("start_pattern", "")
            if not start_pattern:
                continue
            
            start_regex = re.compile(start_pattern)
            start_match = start_regex.search(text)
            
            if not start_match:
                continue
            
            start_pos = start_match.start()
            end_pattern = section.get("end_pattern")
            
            if end_pattern:
                end_regex = re.compile(end_pattern)
                end_match = end_regex.search(text[start_pos + 1:])
                if end_match:
                    end_pos = start_pos + 1 + end_match.start()
                else:
                    end_pos = len(text)
            else:
                end_pos = len(text)
            
            # 检查 line_start_pos 是否在该 section 范围内
            if start_pos <= line_start_pos < end_pos:
                return section.get("name", "未知")
        
        return "未知"