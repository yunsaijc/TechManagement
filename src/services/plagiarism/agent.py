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
import asyncio
import json
import re
import resource
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.common.file_handler import get_parser
from src.services.plagiarism.aggregator import ResultAggregator, PlagiarismResult
from src.services.plagiarism.multi_source_aggregator import MultiSourceAggregator
from src.services.plagiarism.engine import ComparisonEngine
from src.services.plagiarism.report_builder import PlagiarismHtmlReportBuilder
from src.services.plagiarism.mammoth_report_builder import MammothPlagiarismReportBuilder
from src.services.plagiarism.retrieval import SourceRetriever
from src.services.plagiarism.corpus import CorpusManager
from src.services.plagiarism.section_extractor import SectionExtractor
from src.services.plagiarism.text_repairs import repair_extracted_text_artifacts
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
        self.primary_scope_info = None

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
        self.source_retriever = SourceRetriever()
        # Winnowing 参数优化：减少碎片化
        self.comparison_engine = ComparisonEngine(
            min_continuous_match=5,
            ngram_size=8,
            winnowing_window=8,
            min_match_length=30,
        )
        self.result_aggregator = ResultAggregator(section_extractor=self.section_extractor)
        self.multi_source_aggregator = MultiSourceAggregator()
        self.corpus_manager = CorpusManager()

    async def check(
        self,
        files: List[Tuple[str, bytes]],  # [(doc_id, file_data)]
        file_paths: Optional[Dict[str, str]] = None,  # {doc_id: file_path} 用于mammoth报告
        use_corpus: bool = True,
    ) -> PlagiarismResult:
        """
        执行查重

        Args:
            files: 文件列表 [(id, data), ...]
            file_paths: 文件路径字典 {doc_id: file_path}，用于生成mammoth格式报告（保留表格等格式）
            use_corpus: 是否查比对库，默认 True

        Returns:
            查重结果
        """
        start_time = time.time()
        self._file_paths = file_paths or {}

        # 1. 提取所有上传文件的文本
        texts = {}  # {doc_id: full_text}
        uploaded_doc_ids = [doc_id for doc_id, _ in files]
        primary_doc_id = uploaded_doc_ids[0] if uploaded_doc_ids else None

        for idx, (doc_id, file_data) in enumerate(files):
            try:
                # 检测文件类型
                file_type = self._detect_type_from_bytes(file_data)
                parser = get_parser(file_type)
                result = await parser.parse(file_data)

                # 提取全部文本
                full_text = repair_extracted_text_artifacts(result.content.to_text())
                texts[doc_id] = full_text

                print(f"[Plagiarism] 提取上传文本 {doc_id}: {len(full_text)} chars")

                # Debug: 保存解析结果
                if self.debug:
                    self._save_debug(doc_id, result, full_text)

            except Exception as e:
                print(f"[Plagiarism] 提取文本失败 {doc_id}: {e}")
                texts[doc_id] = ""

        if not texts:
            return PlagiarismResult(
                id=f"plagiarism_{int(time.time() * 1000)}",
                total_pairs=0,
                high_similarity=[],
                medium_similarity=[],
                low_similarity=[],
                processing_time=time.time() - start_time,
            )

        # 2. 预处理：仅对主文档进行 section 提取
        primary_text = texts.get(primary_doc_id, "")
        if self.section_extractor:
            scope_details = self.section_extractor.extract_with_details(primary_text)
            extracted = scope_details.get("text", "")
            start_pos = int(scope_details.get("start", -1))
            end_pos = int(scope_details.get("end", -1))
            if not extracted:
                raise ValueError(
                    "primary 文档未命中配置的检测区域：请检查 section_config 的 start_pattern/end_pattern"
                )
            self.primary_scope_info = {
                "doc_id": primary_doc_id,
                "mode": scope_details.get("mode"),
                "start": start_pos,
                "end": end_pos,
                "char_count": len(extracted),
                "start_pattern": scope_details.get("start_pattern"),
                "end_pattern": scope_details.get("end_pattern"),
                "start_match_text": scope_details.get("start_match_text"),
                "end_match_text": scope_details.get("end_match_text"),
                "matched_sections": scope_details.get("matched_sections", []),
                "prefix_context": primary_text[max(0, start_pos - 120):start_pos],
                "suffix_context": primary_text[end_pos:min(len(primary_text), end_pos + 120)],
                "text_preview": extracted[:1000],
            }
            primary_text = extracted
        
        # 统一存储处理后的文本（用于比对）
        processed_texts = {primary_doc_id: primary_text}
        for doc_id in uploaded_doc_ids[1:]:
            processed_texts[doc_id] = texts.get(doc_id, "")

        # 3. 语义分句
        sentences_map = {}  # {doc_id: [Sentence]}
        for doc_id, text in processed_texts.items():
            sentences = self.tokenizer.tokenize(text)
            print(f"[Plagiarism] 分句 {doc_id}: {len(sentences)} 句子")
            sentences_map[doc_id] = sentences

        # 4. 前置模板过滤 - 标记应排除的位置区间
        excluded_ranges = {}
        for doc_id, sentences in sentences_map.items():
            ranges = self.template_prefilter.mark_excluded_ranges(sentences)
            if ranges:
                excluded_ranges[doc_id] = ranges
                print(f"[Plagiarism] 前置过滤排除 {len(ranges)} 个区间 for {doc_id}")

        # 5. 候选召回
        # 5.1 上传文件召回
        other_uploaded_ids = uploaded_doc_ids[1:]
        retrieval_result = self.source_retriever.rank_sources(
            primary_doc=primary_doc_id or "",
            primary_text=primary_text,
            source_texts={doc_id: processed_texts.get(doc_id, "") for doc_id in other_uploaded_ids},
            primary_excluded_ranges=excluded_ranges.get(primary_doc_id or "", []),
            source_excluded_ranges={doc_id: excluded_ranges.get(doc_id, []) for doc_id in other_uploaded_ids},
        )
        
        candidate_doc_ids = list(retrieval_result.selected_source_docs or [])

        # 5.2 库查重召回 (可选)
        if use_corpus:
            t_corpus_start = time.time()
            print(f"[Plagiarism] RSS before corpus retrieval: {self._rss_mb():.1f}MB")
            use_inverted_index = self.corpus_manager.has_inverted_index()
            candidate_doc_ids_from_index = []
            if use_inverted_index:
                candidate_doc_ids_from_index = self.corpus_manager.retrieve_candidate_doc_ids(
                    primary_text=primary_text,
                    primary_excluded_ranges=excluded_ranges.get(primary_doc_id or "", []),
                    top_k=max(self.source_retriever.top_k_docs * 4, 24),
                )
                print(f"[Plagiarism] RSS after coarse retrieval: {self._rss_mb():.1f}MB")
            corpus_retrieval_docs = (
                self.corpus_manager.get_retrieval_documents(candidate_doc_ids_from_index)
                if use_inverted_index
                else self.corpus_manager.get_retrieval_documents()
            )
            print(f"[Plagiarism] RSS after feature load: {self._rss_mb():.1f}MB")
            corpus_retrieval = self.source_retriever.search_in_corpus(
                primary_doc=primary_doc_id or "",
                primary_text=primary_text,
                corpus_documents=corpus_retrieval_docs,
                primary_excluded_ranges=excluded_ranges.get(primary_doc_id or "", []),
            )
            print(f"[Plagiarism] RSS after corpus ranking: {self._rss_mb():.1f}MB")
            print(f"[Plagiarism] 库召回耗时: {time.time() - t_corpus_start:.2f}s")
            if candidate_doc_ids_from_index:
                print(f"[Plagiarism] 倒排粗召回候选: {len(candidate_doc_ids_from_index)} 个")

            # 打印召回详情
            if corpus_retrieval.candidates:
                print(f"[Plagiarism] 召回详情（前5个）:")
                for i, cand in enumerate(corpus_retrieval.candidates[:5]):
                    doc_info = self.corpus_manager.index.documents.get(cand.doc_id)
                    char_count = doc_info.char_count if doc_info else 0
                    print(f"  [{i+1}] {cand.doc_id}: score={cand.document_suspiciousness:.4f}, chars={char_count:,}")

            # 并行延迟加载库文档原文并进行预处理
            t_load_start = time.time()
            
            async def load_and_preprocess(cand_id: str) -> Optional[str]:
                if cand_id in processed_texts:
                    return cand_id
                
                t_doc_start = time.time()
                print(f"[Plagiarism] 从库中延迟加载: {cand_id}")
                corpus_text = await self.corpus_manager.get_document_text(cand_id)
                print(f"[Plagiarism]   - 文档加载耗时: {time.time() - t_doc_start:.2f}s")
                
                if corpus_text:
                    t_preprocess = time.time()
                    processed_texts[cand_id] = corpus_text
                    # 补全分句与过滤
                    sentences = self.tokenizer.tokenize(corpus_text)
                    sentences_map[cand_id] = sentences
                    ranges = self.template_prefilter.mark_excluded_ranges(sentences)
                    if ranges:
                        excluded_ranges[cand_id] = ranges
                    print(f"[Plagiarism]   - 预处理耗时: {time.time() - t_preprocess:.2f}s")
                    return cand_id
                else:
                    print(f"[Plagiarism]   - 跳过：文档加载失败 {cand_id}")
                    return None

            # 仅对尚未加载的文档启动任务
            load_tasks = [load_and_preprocess(cid) for cid in corpus_retrieval.selected_source_docs]
            load_results = await asyncio.gather(*load_tasks)
            
            # 更新 candidate_doc_ids，保持顺序并去重
            loaded_ids = [rid for rid in load_results if rid]
            for lid in loaded_ids:
                if lid not in candidate_doc_ids:
                    candidate_doc_ids.append(lid)
            
            loaded_count = len(loaded_ids)
            failed_count = len(corpus_retrieval.selected_source_docs) - loaded_count
            
            print(f"[Plagiarism] 库文档加载总耗时: {time.time() - t_load_start:.2f}s, 成功: {loaded_count}, 失败: {failed_count}")

            # 合并上传召回与库召回，并重新全局排序
            retrieval_result = self._merge_retrieval_results(retrieval_result, corpus_retrieval)
            candidate_doc_ids = list(retrieval_result.selected_source_docs or [])

            # 重新构建引导窗口信息
            doc_windows = {cand.doc_id: cand.matched_windows for cand in retrieval_result.candidates}

        print(f"[Plagiarism] 最终比对候选: {len(candidate_doc_ids)} 个来源文档")

        # 6. 仅对 primary 与召回候选 source 做精比对
        t_compare_start = time.time()
        similarities = []
        doc_windows = doc_windows if use_corpus else {}

        async def compare_pair(idx: int, source_doc_id: str) -> List[Any]:
            t_pair_start = time.time()
            source_sentences = sentences_map.get(source_doc_id, [])
            primary_sentences = sentences_map.get(primary_doc_id, [])
            
            source_len = len(processed_texts.get(source_doc_id, ""))
            primary_len = len(processed_texts.get(primary_doc_id, ""))
            print(f"[Plagiarism] 开始比对 [{idx+1}/{len(candidate_doc_ids)}]: {primary_doc_id} vs {source_doc_id} ({source_len:,} chars)")

            pair_sentences = {
                primary_doc_id: primary_sentences,
                source_doc_id: source_sentences,
            }
            pair_excluded_ranges = {
                primary_doc_id: excluded_ranges.get(primary_doc_id, []),
                source_doc_id: excluded_ranges.get(source_doc_id, []),
            }
            pair_texts = {
                primary_doc_id: processed_texts.get(primary_doc_id, ""),
                source_doc_id: processed_texts.get(source_doc_id, ""),
            }
            
            # 使用 run_in_executor 将 CPU 密集型的 compare 放到线程池执行，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            pair_similarities = await loop.run_in_executor(
                None, 
                self.comparison_engine.compare,
                pair_sentences,
                pair_excluded_ranges,
                self.threshold_high,
                self.threshold_medium,
                pair_texts,
                {source_doc_id: doc_windows.get(source_doc_id, [])} if use_corpus else None
            )
            
            elapsed = time.time() - t_pair_start
            print(f"[Plagiarism] 完成比对 [{idx+1}/{len(candidate_doc_ids)}]: {source_doc_id}, 耗时: {elapsed:.2f}s")
            return pair_similarities

        # 并行执行所有比对任务
        compare_tasks = [compare_pair(idx, sid) for idx, sid in enumerate(candidate_doc_ids)]
        compare_results = await asyncio.gather(*compare_tasks)
        
        # 合并结果
        for pair_res in compare_results:
            similarities.extend(pair_res)

        print(f"[Plagiarism] 全部比对完成: {len(similarities)} 对, 总耗时: {time.time() - t_compare_start:.2f}s")

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
        
        # 7. 多源聚合（以 primary 为中心）
        if primary_doc_id:
            # 获取 Pairwise 调试输出（包含所有初步匹配片段）
            pairwise_debug = self.result_aggregator.format_debug_output(
                similarities,
                processed_texts,
                primary_doc_id,
                template_filter=self.template_filter,
            )
            
            # 使用 MultiSourceAggregator 进行归并
            primary_chars = self.primary_scope_info.get("char_count", 0) if self.primary_scope_info else len(processed_texts.get(primary_doc_id, ""))
            multi_summary = self.multi_source_aggregator.build_summary(
                pairwise_debug,
                primary_chars
            )
            
            # 更新结果
            result.effective_duplicate_rate = multi_summary.get("effective_duplicate_rate", 0.0)
            result.effective_duplicate_chars = multi_summary.get("effective_duplicate_chars", 0)
            result.primary_scope_chars = multi_summary.get("primary_scope_chars", 0)
            result.source_rankings = multi_summary.get("source_rankings", [])
            result.match_groups = multi_summary.get("match_groups", [])

        result.processing_time = time.time() - start_time

        print(f"[Plagiarism] 查重完成: {result.total_pairs} 对, 高相似度 {len(result.high_similarity)} 对")

        # 6. 保存 debug 信息
        if self.debug and primary_doc_id:
            # 合并上传的 doc_ids 和召回的 doc_ids 用于保存
            all_involved_doc_ids = list(uploaded_doc_ids)
            for cid in candidate_doc_ids:
                if cid not in all_involved_doc_ids:
                    all_involved_doc_ids.append(cid)

            self._save_plagiarism_debug(
                all_involved_doc_ids,
                processed_texts,
                primary_doc_id,
                similarities,
                excluded_ranges,  # 传入排除区间
                primary_scope_info=self.primary_scope_info,
                retrieval_result=retrieval_result,
                multi_summary=multi_summary if primary_doc_id else None,
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

    def _merge_retrieval_results(self, uploaded_result, corpus_result):
        """合并多个召回结果并重新排序去重。"""
        merged_candidates = {}
        for candidate in list(uploaded_result.candidates or []) + list(corpus_result.candidates or []):
            existing = merged_candidates.get(candidate.doc_id)
            if existing is None:
                merged_candidates[candidate.doc_id] = candidate
                continue
            if (
                candidate.document_suspiciousness,
                candidate.max_window_score,
                candidate.hit_window_count,
            ) > (
                existing.document_suspiciousness,
                existing.max_window_score,
                existing.hit_window_count,
            ):
                merged_candidates[candidate.doc_id] = candidate

        merged_list = sorted(
            merged_candidates.values(),
            key=lambda item: (
                -item.document_suspiciousness,
                -item.max_window_score,
                -item.hit_window_count,
                item.doc_id,
            ),
        )

        uploaded_result.candidates = merged_list
        uploaded_result.selected_source_docs = [
            candidate.doc_id for candidate in merged_list[: self.source_retriever.top_k_docs]
        ]
        uploaded_result.total_source_docs = (
            int(uploaded_result.total_source_docs or 0) + int(corpus_result.total_source_docs or 0)
        )
        return uploaded_result

    def _rss_mb(self) -> float:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024
        except OSError:
            pass
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss_kb > 10_000_000:
            return rss_kb / (1024 * 1024)
        return rss_kb / 1024

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
        primary_scope_info: Optional[Dict] = None,
        retrieval_result=None,
        multi_summary: Optional[Dict] = None,
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
        for doc_id, text in processed_texts.items():
            safe_name = doc_id.replace("/", "_")
            (debug_dir / f"{safe_name}.processed.txt").write_text(text, encoding="utf-8")
        if primary_scope_info:
            output["primary_scope"] = primary_scope_info
            extracted_text = processed_texts.get(primary_doc_id, "")
            (debug_dir / "primary_scope_extracted.txt").write_text(extracted_text, encoding="utf-8")
            (debug_dir / "primary_scope_debug.json").write_text(
                json.dumps(primary_scope_info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        
        # 添加排除区间信息
        if excluded_ranges:
            output["excluded_ranges"] = {
                doc_id: [{"start": r.start, "end": r.end, "reason": r.reason} for r in ranges]
                for doc_id, ranges in excluded_ranges.items()
            }

        if multi_summary:
            output["match_groups"] = multi_summary.get("match_groups", [])
            output["source_rankings"] = multi_summary.get("source_rankings", [])
            output["summary"].update({
                "primary_scope_chars": multi_summary.get("primary_scope_chars", 0),
                "effective_duplicate_chars": multi_summary.get("effective_duplicate_chars", 0),
                "effective_duplicate_rate": multi_summary.get("effective_duplicate_rate", 0.0),
                "group_count": multi_summary.get("group_count", 0),
                "source_count": multi_summary.get("source_count", 0),
            })

        if retrieval_result:
            selected_source_docs = list(retrieval_result.selected_source_docs or [])
            compared_source_docs = [similarity.doc_b for similarity in similarities if similarity.doc_a == primary_doc_id]
            top_source_doc_id = selected_source_docs[0] if selected_source_docs else (compared_source_docs[0] if compared_source_docs else None)
            retrieval_output = {
                "primary_doc": retrieval_result.primary_doc,
                "total_source_docs": retrieval_result.total_source_docs,
                "selected_source_docs": selected_source_docs,
                "compared_source_docs": compared_source_docs,
                "top_source_doc": top_source_doc_id,
                "selection_mode": "retrieval_top_k" if selected_source_docs else "fallback_all_sources",
                "candidates": [
                    {
                        "doc_id": candidate.doc_id,
                        "document_suspiciousness": candidate.document_suspiciousness,
                        "max_window_score": candidate.max_window_score,
                        "hit_window_count": candidate.hit_window_count,
                        "matched_windows": [
                            {
                                "primary_start": window.primary_start,
                                "primary_end": window.primary_end,
                                "score": window.score,
                                "char_count": window.char_count,
                                "overlap_char2": window.overlap_char2,
                                "overlap_char4": window.overlap_char4,
                                "overlap_char8": window.overlap_char8,
                            }
                            for window in candidate.matched_windows
                        ],
                    }
                    for candidate in retrieval_result.candidates
                ],
            }
            output["retrieval"] = retrieval_output
            if top_source_doc_id:
                output["report_source_doc"] = top_source_doc_id
            (debug_dir / "retrieval_candidates.json").write_text(
                json.dumps(retrieval_output, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        filename = debug_dir / "plagiarism_debug.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # 生成 mammoth 版报告（保留Word格式，包括表格）
        mammoth_html_filename = debug_dir / "plagiarism_report_mammoth.html"
        def _is_docx(doc_id: str) -> bool:
            return doc_id.lower().endswith(".docx")

        primary_path = None
        if hasattr(self, "_file_paths") and _is_docx(primary_doc_id):
            primary_path = self._file_paths.get(primary_doc_id)
        selected_source_docs = list(getattr(retrieval_result, "selected_source_docs", []) or [])
        top_source_doc_id = selected_source_docs[0] if selected_source_docs else None
        if not top_source_doc_id:
            for doc_id in doc_ids:
                if doc_id != primary_doc_id:
                    top_source_doc_id = doc_id
                    break
        source_path = None
        if top_source_doc_id and _is_docx(top_source_doc_id):
            source_path = (self._file_paths or {}).get(top_source_doc_id)
        
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
