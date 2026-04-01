# 比对库管理 (Corpus Management)

## 概述

比对库的职责，不是“保存所有原文然后每次全库遍历”，而是：

1. 预先为库中文档建立稳定的检索索引
2. 在查重请求到来时，先快速缩小候选范围
3. 只对少量候选文档读取原文并进入精比对

这也是搜索系统与主流查重系统的通用做法：先检索，再重排，最后精比对。

当前项目仍然沿用现有 `ComparisonEngine` 作为细粒度查重内核；本页只讨论 **Corpus 层如何对齐业界最佳实践**，避免“库一大就卡死”。

## 设计目标

### 1. 对齐最佳实践，而不是全库暴力扫描

库查重应当遵循下面的三段式流程：

1. **粗召回 (Recall)**：
   通过倒排索引快速找到“可能相关”的文档集合
2. **轻量重排 (Rerank)**：
   只对少量候选文档做窗口级打分，保留 Top-K
3. **精比对 (Compare)**：
   只对最终 Top-K 读取原文并运行 `ComparisonEngine`

如果粗召回阶段仍然要“碰到几千篇文档、读多个超大索引分片”，那就不算真正对齐最佳实践。

### 2. 远程原文与本地索引分离

- **远程挂载**：原始 DOCX/PDF 仍然位于远程目录，通过挂载访问
- **本地索引**：本地只保留检索所需的元数据与特征
- **延迟取原文**：只有最终进入精比对的文档才读取原文

### 3. Primary-only 配置，Source 无需配 section

- Primary 文档必须根据配置提取待检测区
- Source / Corpus 文档不做 section 裁切
- 库召回与精比对都围绕 Primary 的检测区展开

## 当前架构

### 1. 元数据清单

文件：`data/plagiarism/corpus_index.json`

只保存轻量元数据：

- `doc_id`
- `path`
- `file_hash`
- `file_size`
- `file_mtime`
- `char_count`
- `shard_id`

注意：**这里必须保存可回溯到真实物理文件的正确路径**。  
如果 `doc_id` 命中了，但 `path` 无法定位到挂载目录下的真实文件，那么后续原文加载会全部失败，导致精比对结果失真。

### 2. Feature 分片

目录：`data/plagiarism/corpus_index_shards/`

每个分片保存一组文档的预处理特征。当前仍保存：

- `char2`
- `char4`
- `char8`

这一步解决的是“避免每次查重时重新解析文档”，但如果分片过大、读取方式过粗，仍然会带来严重的 I/O 与内存压力。

### 3. SQLite 索引层

文件：`data/plagiarism/corpus_index.db`

为了对齐最佳实践，在线查询不再应直接依赖超大 JSON 分片，而应优先走 SQLite 索引层：

- `docs`
  - 保存 `doc_id -> path` 等元数据
- `postings_char4`
  - 保存 `char4 -> doc_id` 的倒排关系
- `gram_stats_char4`
  - 保存 `char4` 的文档频次，用于高频 gram 过滤
- `doc_features`
  - 按 `doc_id` 保存轻量重排所需特征

当前阶段的最小实现，至少要有四张表：

- `docs`
  - 保存 `doc_id -> path/file_hash/file_size/file_mtime/char_count/shard_id`
- `doc_features`
  - 保存 `doc_id -> char2/char4/char8`
- `postings_char4`
  - 保存 `char4 -> doc_id`
- `gram_stats_char4`
  - 保存 `char4 -> df`

这样在线请求就可以：

1. 按 `char4` 精确取 posting
2. 按 `doc_id` 精确取候选特征
3. 避免反复整块反序列化数百 MB 的 JSON 分片

### 4. 倒排索引分片

目录：`data/plagiarism/corpus_char4_inverted/`

当前基于 `char4` 建立倒排索引，用于粗召回。

说明：

- JSON 倒排分片仍保留，作为历史兼容与调试产物
- 在线召回的目标实现应优先走 SQLite，而不是继续把 JSON 分片当成主查询路径

概念上：

- 键：`char4`
- 值：出现该 `char4` 的 `doc_id` 列表

查重时的正确方向是：

1. 从 Primary 检测区提取 query grams
2. 通过倒排索引反查候选文档
3. 丢掉高频、泛化、噪音 gram
4. 只保留少量候选进入后续阶段

## 与最佳实践的对齐点

### 1. 倒排优先，而不是全库扫描

主流搜索系统（Lucene / Elasticsearch）和工业检索系统（如 Vespa）的共同点是：

- 先靠倒排索引拿候选集合
- 再做两阶段或多阶段排序
- 不会在在线请求里把全库原文或全库特征整批搬进内存

对应到本项目：

- `char4` 倒排索引负责粗召回
- `SourceRetriever` 负责窗口级重排
- `ComparisonEngine` 负责最终精比对

### 2. 局部读取，而不是整块大 JSON 反序列化

最佳实践不是“把大索引切成若干 JSON 分片”，而是：

- 查询一个 gram 时，只取这个 gram 的 posting
- 查询一个 doc_id 时，只取这个 doc 的特征

如果为了十几个候选文档，还要读取多个数百 MB 的大分片，那工程上仍然是不合格的。

### 3. 高成本步骤必须延后

最贵的步骤包括：

- 解析库文档原文
- 加载大特征集合
- 运行细粒度比对内核

这些步骤都必须发生在 **候选足够少之后**。

### 4. 原文读取与检索索引解耦

最佳实践里，检索索引只回答：

- “谁可能相关？”

而原文存储只负责：

- “把这几个最终候选的正文拿回来”

这要求 `doc_id -> path` 的映射始终正确，且能稳定定位到挂载目录中的文件。

## 当前已暴露的问题

下面这些是已经在真实运行中验证过的问题，不是理论风险。

### 1. 粗召回仍然会惊动过多文档

真实日志里，单篇 Primary 虽然最后只保留几十个候选，但粗召回阶段仍可能对数千篇文档打分。

这说明：

- 高频 gram 过滤还不够严格
- query grams 数量仍然过多
- 倒排分片读取粒度仍然偏粗

### 2. Feature / 倒排分片过大

当前本地分片文件非常大。  
如果为了少数几个候选就要读取多个数百 MB 的 JSON 分片，那么即使“逻辑上不是全库扫描”，工程上依然会非常慢。

### 3. 在线查询仍可能退化为整块大分片读取

如果粗召回仍然通过读取大 JSON 分片来找 posting，或候选特征仍然通过读取大 JSON 分片来取值，那么：

1. 即使最终只重排十几个候选
2. 在线请求仍然可能消耗数百秒
3. 多对多查重无法扩展

### 4. 原文路径映射可能失真

如果 `corpus_index.json` 中保存的是错误路径，或保存的只是裸文件名而不是真实相对路径，那么：

1. 粗召回可以命中
2. 但精比对阶段拿不到原文
3. 最终会出现“候选存在，但实际比对是空文本”的错误结果

### 5. 当前结构还不适合直接放大到多对多

如果单篇 Primary 对 Corpus 已经很重，那么多个 Primary 并发或多对多查重只会把问题成倍放大。

因此，多对多不是“先加并发”就能解决，而是必须先把单篇对库的召回链路做轻。

## 推荐架构

### 阶段一：粗召回

输入：

- Primary 检测区文本

输出：

- 少量候选 `doc_id`

要求：

- 只使用轻量索引结构
- 严格限制 query grams 数量
- 跳过高频 gram
- 候选上限尽量控制在几十级
- 实现上优先走 SQLite posting 查询，而不是 JSON 分片扫描
- 查询方式必须是“按 query gram 精确查 posting”，而不是“整片加载后再在 Python 里遍历”

### 阶段二：轻量重排

输入：

- 粗召回得到的候选 `doc_id`

输出：

- 最终进入精比对的 Top-K

要求：

- 只加载候选所需的最小特征集合
- 不要再次把大分片长期常驻内存
- 窗口级打分逻辑复用现有 `SourceRetriever`
- 实现上优先按 `doc_id` 从 SQLite 取特征，而不是从大 JSON shard 整块读
- 只允许读取本次候选 `doc_id` 的特征，不能为了十几个候选去反序列化整片大文件

### 阶段三：精比对

输入：

- 最终 Top-K 候选

输出：

- 细粒度命中片段
- 多源归并结果

要求：

- 只在此阶段读取原文
- 只对少量候选运行 `ComparisonEngine`

## 当前约束

为了稳住已有效果，下面这些边界不变：

- 不推翻 `ComparisonEngine`
- 最终结果展示仍以 `mammoth` HTML 为准
- Primary 使用 section 配置
- Source / Corpus 不做 section 裁切

## 当前实现要求

当前代码必须按下面方式落地，而不是只停留在设计描述：

1. `scan_and_update` 以 SQLite 作为主索引写入目标
2. JSON 分片改为调试产物：
   - 默认 refresh 不再实时双写 JSON feature shard / inverted shard
   - 只有显式开启调试模式时才维护 JSON 分片
3. 同步维护 SQLite：
   - 文档新增/更新时，同时更新 `docs`、`doc_features`、`postings_char4`、`gram_stats_char4`
   - 文档删除时，同步删除对应 SQLite 记录
4. 在线查重时：
   - `retrieve_candidate_doc_ids` 优先走 SQLite
   - `get_retrieval_documents(doc_ids)` 优先按 `doc_id` 从 SQLite 取特征
   - 只有 SQLite 不可用时才退回 JSON 分片
5. 历史 JSON 索引已存在、但 SQLite 缺失时，应支持基于现有 JSON 分片重建 SQLite，而不是重新解析全部原始文档

## 维护流程

### 1. 查看库状态

```bash
curl 'http://127.0.0.1:8888/api/v1/plagiarism/corpus/status'
```

### 2. 后台刷新库

```bash
curl -X POST 'http://127.0.0.1:8888/api/v1/plagiarism/corpus/refresh' \
  -F 'batch_size=50' \
  -F 'max_concurrency=1' \
  -F 'save_every_batches=10'
```

### 3. 查看 refresh 进度

```bash
curl 'http://127.0.0.1:8888/api/v1/plagiarism/corpus/refresh/status'
```

### 4. 观察首建阶段

如果倒排索引不存在，refresh 会先执行倒排首建。此时状态字段中会出现：

- `stage = rebuild_inverted_index`
- `processed`
- `total`
- `feature_shard_id`

## 后续优化方向

按优先级排序：

1. 继续压缩粗召回命中文档数量
2. 进一步降低 SQLite 首建与增量刷新期间的写放大
3. 把多对多任务调度与在线单篇查重彻底解耦
4. 在召回层加入更稳的高频 gram 控制与查询预算

## 参考

- Lucene Index / Postings / Stored Fields  
  https://lucene.apache.org/core/9_5_0/core/org/apache/lucene/index/package-summary.html  
  https://lucene.apache.org/core/9_9_1/core/org/apache/lucene/index/StoredFields.html
- Elasticsearch `_source` / Stored Retrieval  
  https://www.elastic.co/guide/en/elasticsearch/reference/current/mapping-source-field.html
- Vespa Phased Ranking  
  https://docs.vespa.ai/en/phased-ranking.html
