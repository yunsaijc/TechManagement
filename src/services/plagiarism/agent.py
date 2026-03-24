"""查重服务 Agent

基于句子级比对 + 位置追溯的查重方案。
对齐业界最佳实践（知网、Turnitin）。

核心流程:
1. 文本提取 (PDF/DOCX → 结构化文本)
2. 语义分句 (按标点分句，而非按行)
3. 模板过滤 (白名单 + 标题检测 + 短句过滤)
4. N-gram 切分 (滑动窗口)
5. 指纹索引 + 连续匹配检测
6. 结果聚合 (位置追溯、片段合并)
"""
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.common.file_handler import get_parser
from src.services.plagiarism.aggregator import ResultAggregator, PlagiarismResult
from src.services.plagiarism.engine import ComparisonEngine
from src.services.plagiarism.report_builder import PlagiarismHtmlReportBuilder
from src.services.plagiarism.mammoth_report_builder import MammothPlagiarismReportBuilder
from src.services.plagiarism.section_extractor import SectionExtractor
from src.services.plagiarism.template_filter import TemplateFilter
from src.services.plagiarism.template_prefilter import TemplatePreFilter
from src.services.plagiarism.tokenizer import SentenceTokenizer


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
        """
        初始化查重 Agent

        Args:
            threshold: 基础阈值
            threshold_high: 高相似度阈值
            threshold_medium: 中相似度阈值
            section_config: Section 配置
            debug: 是否保存 debug 信息
        """
        self.threshold = threshold
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.debug = debug

        # 初始化 Section 提取器
        if section_config and SectionExtractor.validate_config(section_config):
            self.section_extractor = SectionExtractor(section_config)
        else:
            self.section_extractor = None

        # 初始化 Layer 5 组件
        self.tokenizer = SentenceTokenizer()
        self.template_filter = TemplateFilter()
        self.template_prefilter = TemplatePreFilter(template_filter=self.template_filter)
        self.report_builder = PlagiarismHtmlReportBuilder()
        self.mammoth_report_builder = MammothPlagiarismReportBuilder()
        # Winnowing 参数优化：减少碎片化
        self.comparison_engine = ComparisonEngine(
            min_continuous_match=5,
            ngram_size=8,
            winnowing_window=8,
            min_match_length=30,
        )
        self.result_aggregator = ResultAggregator(section_extractor=self.section_extractor)

    async def check(
        self,
        files: List[Tuple[str, bytes]],  # [(doc_id, file_data)]
        file_paths: Optional[Dict[str, str]] = None,  # {doc_id: file_path} 用于mammoth报告
    ) -> PlagiarismResult:
        """
        执行查重

        Args:
            files: 文件列表 [(id, data), ...]
            file_paths: 文件路径字典 {doc_id: file_path}，用于生成mammoth格式报告（保留表格等格式）

        Returns:
            查重结果
        """
        start_time = time.time()
        self._file_paths = file_paths or {}

        # 1. 提取所有文本
        texts = {}  # {doc_id: full_text}
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
                texts[doc_id] = full_text

                print(f"[Plagiarism] 提取文本 {doc_id}: {len(full_text)} chars")

                # Debug: 保存解析结果
                if self.debug:
                    self._save_debug(doc_id, result, full_text)

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

        # 2. 预处理：只对主文档进行 section 提取
        extracted_texts = {}

        for idx, doc_id in enumerate(doc_ids):
            text = texts[doc_id]

            if idx == 0 and self.section_extractor:
                # 主文档：先提取 section 区域
                text = self.section_extractor.extract(text)

            extracted_texts[doc_id] = text
            print(f"[Plagiarism] Section提取 {doc_id}: {len(text)} chars")

        # 3. 语义分句（不过滤，保持原始位置对齐）
        sentences_map = {}  # {doc_id: [Sentence]}

        for idx, doc_id in enumerate(doc_ids):
            text = extracted_texts[doc_id]

            # 分句（不过滤，用于比对）
            sentences = self.tokenizer.tokenize(text)
            print(f"[Plagiarism] 分句 {doc_id}: {len(sentences)} 句子")

            sentences_map[doc_id] = sentences

        # 4. 构建用于比对的文本（保留标点）
        processed_texts = {}
        for doc_id, sentences in sentences_map.items():
            # 保留原始句子，用换行分隔（供后续追溯用）
            processed_texts[doc_id] = '\n'.join(s.text for s in sentences)

        # 5. 前置模板过滤 - 标记应排除的位置区间
        excluded_ranges = {}
        for doc_id, sentences in sentences_map.items():
            ranges = self.template_prefilter.mark_excluded_ranges(sentences)
            if ranges:
                excluded_ranges[doc_id] = ranges
                print(f"[Plagiarism] 前置过滤排除 {len(ranges)} 个区间 for {doc_id}")
        
        # 6. N-gram 比对（传入排除区间）
        similarities = self.comparison_engine.compare(
            sentences_map,
            excluded_ranges,
            self.threshold_high,
            self.threshold_medium,
        )
        print(f"[Plagiarism] 比对完成: {len(similarities)} 对")

        for r in similarities:
            print(f"  - {r.doc_a} vs {r.doc_b}: similarity={r.similarity:.4f}, type={r.type}")

        # 6. 结果聚合（后置过滤）
        result = self.result_aggregator.aggregate(
            similarities,
            self.threshold_high,
            self.threshold_medium,
            doc_texts=processed_texts,
            template_filter=self.template_filter,  # 传入模板过滤器用于后置过滤
        )
        result.processing_time = time.time() - start_time

        print(f"[Plagiarism] 查重完成: {result.total_pairs} 对, 高相似度 {len(result.high_similarity)} 对")

        # 6. 保存 debug 信息
        if self.debug and primary_doc_id:
            self._save_plagiarism_debug(
                doc_ids,
                processed_texts,
                primary_doc_id,
                similarities,
                excluded_ranges,  # 传入排除区间
            )

        return result

    async def check_with_paths(
        self,
        files: List[Tuple[str, bytes]],
        file_paths: Dict[str, str],
    ) -> PlagiarismResult:
        """执行查重并传入文件路径（用于生成mammoth格式报告）
        
        Args:
            files: 文件列表 [(id, data), ...]
            file_paths: 文件路径字典 {doc_id: file_path}
            
        Returns:
            查重结果
        """
        return await self.check(files, file_paths)

    def _detect_type_from_bytes(self, file_data: bytes) -> str:
        """根据文件数据检测类型"""
        if file_data[:4] == b'%PDF':
            return 'pdf'
        elif file_data[:4] == b'PK\x03\x04':  # docx 是 zip 格式
            return 'docx'
        else:
            return 'unknown'

    def _save_debug(self, doc_id: str, result, full_text: str = ""):
        """
        保存 debug 结果

        Args:
            doc_id: 文档 ID
            result: 解析结果
            full_text: 完整文本
        """
        debug_dir = Path("debug_plagiarism")
        debug_dir.mkdir(exist_ok=True)

        output = {
            "doc_id": doc_id,
            "is_primary": False,
            "metadata": result.metadata,
        }

        # 保存全文预览
        if full_text:
            output["full_text_preview"] = full_text[:3000]

        filename = debug_dir / f"{doc_id}_parse.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"[Plagiarism] Debug: 保存解析结果到 {filename}")

    def _save_plagiarism_debug(
        self,
        doc_ids: List[str],
        processed_texts: Dict[str, str],
        primary_doc_id: str,
        similarities,
        excluded_ranges: Dict[str, list] = None,  # 添加排除区间参数
    ):
        """保存查重详细debug信息"""
        debug_dir = Path("debug_plagiarism")
        debug_dir.mkdir(exist_ok=True)

        # 格式化 debug 输出（应用后置过滤）
        output = self.result_aggregator.format_debug_output(
            similarities,
            processed_texts,
            primary_doc_id,
            template_filter=self.template_filter,
        )
        output["documents"] = processed_texts
        
        # 添加排除区间信息
        if excluded_ranges:
            output["excluded_ranges"] = {
                doc_id: [{"start": r.start, "end": r.end, "reason": r.reason} for r in ranges]
                for doc_id, ranges in excluded_ranges.items()
            }

        filename = debug_dir / "plagiarism_debug.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # 生成普通文本版报告
        html_filename = debug_dir / "plagiarism_report.html"
        self.report_builder.build_from_debug_file(filename, html_filename)

        # 生成 mammoth 版报告（保留Word格式，包括表格）
        mammoth_html_filename = debug_dir / "plagiarism_report_mammoth.html"
        primary_path = self._file_paths.get(primary_doc_id) if hasattr(self, '_file_paths') else None
        source_path = None
        for doc_id in doc_ids:
            if doc_id != primary_doc_id and doc_id in (self._file_paths or {}):
                source_path = self._file_paths[doc_id]
                break
        
        try:
            self.mammoth_report_builder.build_from_debug_file(
                filename,
                mammoth_html_filename,
                primary_docx_path=primary_path,
                source_docx_path=source_path,
            )
            print(f"[Plagiarism] Debug: 保存Mammoth格式报告到 {mammoth_html_filename}")
        except Exception as e:
            print(f"[Plagiarism] Debug: Mammoth报告生成失败: {e}")

        print(f"[Plagiarism] Debug: 保存查重详情到 {filename}")
        print(f"[Plagiarism] Debug: 保存HTML报告到 {html_filename}")
