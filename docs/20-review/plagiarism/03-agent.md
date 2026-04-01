# Agent 设计 (PlagiarismAgent)

## 目标

`PlagiarismAgent` 是查重服务的流程指挥官，负责编排从 Primary 文档解析到多源归并、报告生成的完整流水线。

在“库查重”模式下，Agent 的职责从简单的“Pairwise 比对”升级为“分布式候选召回与聚合”。

## 核心职责

### 1. 文档解析与检测区提取 (Preprocessing)
- 对用户上传的 Primary 文档进行 PDF/DOCX 解析。
- 根据 `SectionExtractor` 截取待检测区域（如申报书正文）。
- 建立 `Primary 坐标系`，用于后续所有匹配片段的映射。

### 2. 库查重召回 (Corpus-based Retrieval)
- 调用 `SourceRetriever.rank_sources`。
- 优先通过 `CorpusManager` 的倒排索引做粗召回，先把候选范围缩小到几十级。
- 在线倒排与候选特征读取优先走 SQLite，而不是大 JSON 分片。
- 再对候选集合运行 `SourceRetriever` 的窗口级重排，输出最终 Top-K。
- 这一步不应退化为“全库逐文档扫描”，也不应在在线请求里把大量特征分片整批常驻内存。

### 3. 按需精比对 (Lazy Matching)
- 对于召回出的 Top-K 文档，通过 `CorpusManager` 获取挂载目录下的原文。
- 逐一运行 `ComparisonEngine.compare(primary, corpus_doc)`。
- 生成精细的匹配片段列表。

### 4. 多源归并与统计 (Aggregation)
- 调用 `MultiSourceAggregator.build_summary`。
- **归并**：如果一段话在 A 库文档和 B 库文档中都有发现，则合并为一个 Match Group。
- **统计**：计算主文档去重后的 `effective_duplicate_rate`。

## 流程编排 (Workflow)

```python
async def check(files, use_corpus=True):
    # 1. 解析 Primary
    primary_text = parser.parse(files[0])
    primary_scope = section_extractor.extract(primary_text)
    
    # 2. 库召回
    if use_corpus:
        candidate_ids = corpus_manager.retrieve_candidate_doc_ids(primary_scope)
        candidate_docs = corpus_manager.get_retrieval_documents(candidate_ids)
        candidates = source_retriever.search_in_corpus(primary_scope, candidate_docs)
    
    # 3. 精比对 (Top-K)
    all_similarities = []
    for cand in candidates:
        source_text = corpus_manager.get_document_text(cand.doc_id)
        sim = engine.compare(primary_scope, source_text)
        all_similarities.append(sim)
        
    # 4. 多源归并
    summary = multi_source_aggregator.build_summary(all_similarities, primary_scope.chars)
    
    # 5. 生成报告
    return mammoth_report_builder.build(summary)
```

## 设计原则

- **分阶段检索**：先粗召回，再重排，最后精比对。
- **IO 隔离**：只有最终 Top-K 文档才会触发远程原文读取。
- **坐标一致性**：所有的 `start/end` 坐标均以 Primary 文档提取后的正文为基准。
