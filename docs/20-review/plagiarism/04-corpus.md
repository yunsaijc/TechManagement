# 比对库管理 (Corpus Management)

## 概述

比对库的职责，不是“保存所有原文然后每次全库遍历”，而是：

1. 预先为库中文档建立稳定的检索索引
2. 在查重请求到来时，先快速缩小候选范围
3. 只对少量候选文档读取原文并进入精比对

这也是搜索系统与主流查重系统的通用做法：先检索，再重排，最后精比对。

当前项目仍然沿用现有 `ComparisonEngine` 作为细粒度查重内核；本页只讨论 Corpus 层如何对齐业界最佳实践，并明确当前 refresh 架构的风险边界。

## 设计目标

### 1. 在线查重与离线建库解耦

在线查重只做：

- 读取 SQLite 检索索引
- 执行粗召回、轻量重排、精比对
- 输出 Mammoth HTML 报告

离线建库才做：

- 扫描挂载目录
- 解析 `docx`
- 生成特征
- 写入 SQLite

### 2. Primary-only 配置

- Primary 文档必须根据配置提取待检测区
- Source / Corpus 文档不做 section 裁切
- 库召回与精比对都围绕 Primary 的检测区展开

### 3. 最小化危险 I/O 任务

后续实现必须优先避免：

- 长时间扫描远程挂载目录
- 长生命周期后台建库进程
- 一个任务同时做扫描、解析、建特征、写索引
- 不可恢复的全量 refresh

## 当前索引结构

### 1. 元数据清单

文件：`data/plagiarism/corpus_index.json`

保存轻量元数据：

- `doc_id`
- `path`
- `file_hash`
- `file_size`
- `file_mtime`
- `char_count`
- `shard_id`

### 2. SQLite 主索引

文件：`data/plagiarism/corpus_index.db`

在线查询优先走 SQLite：

- `docs`
- `doc_features`
- `postings_char4`
- `gram_stats_char4`

SQLite 是当前在线召回的主路径。

其中：

- `doc_features` 保存完整特征
- `postings_char4` 只保存代表性粗召回特征
- `gram_stats_char4` 只统计代表性粗召回特征的 df

### 3. JSON 分片

目录：

- `data/plagiarism/corpus_index_shards/`
- `data/plagiarism/corpus_char4_inverted/`

说明：

- JSON 分片只保留为兼容/调试产物
- 默认 refresh 不应再实时双写这些 JSON 分片
- 在线查询不应再依赖这些 JSON 分片

## 风险结论

现有“一次 API 调用触发全量 refresh”的模式已被证明不适合当前环境。

根因不是单点代码 bug，而是这条链路把下面几类高成本操作耦合到了一个长生命周期后台进程里：

- 扫描远程挂载目录
- 读取大量 `docx`
- 解析正文并生成特征
- 写入本地 SQLite 索引

在当前机器与挂载条件下，这类任务可能进入不可中断的底层 I/O 等待，表现为：

- 进程长时间不退出
- `kill -9` 无法立即杀掉
- `STAT=D`

因此，后续实现必须以“避免长时 I/O 任务”为第一原则，而不是继续修补全量 refresh。

## 新架构

### 1. API 只读，不再承担危险建库任务

在线 API 的职责收敛为：

- 读取当前 SQLite 索引状态
- 执行在线查重
- 返回 manifest / checkpoint / build 状态

在线 API 不再直接启动“扫描 + 解析 + 建索引”的长后台任务。

### 2. Scan Manifest

新增一个轻量扫描阶段，只负责生成待处理清单。

输入：

- 挂载目录

输出：

- `manifest` 文件

每条记录只包含轻量字段：

- `doc_id`
- `path`
- `file_size`
- `file_mtime`
- `action`

这里的 `action` 只描述：

- `new`
- `update`
- `fix_path`
- `unchanged`

要求：

- 不解析文档正文
- 不构建特征
- 不写 `postings_char4`
- 不做长事务

### 3. Build Batch

新增离线小批构建阶段。

输入：

- `manifest`
- `checkpoint`
- `limit`

输出：

- 更新后的 `docs`
- 更新后的 `doc_features`
- 更新后的 `checkpoint`

约束：

- 一次只处理很小一批文档
- 每批完成后立即退出
- 下次从 `checkpoint` 自动续跑
- 不允许单进程长时间跑完全库
- 解析可以小并发，但 SQLite 写入必须保持单写者
- `build batch` 不负责增量维护全局粗召回倒排
- 离线构建产物必须写入独立工作目录，不能与在线服务共享同一组索引文件

### 4. Rebuild Coarse Index

新增独立的粗召回索引重建阶段。

输入：

- `doc_features`
- 当前 corpus 文档元数据

输出：

- `postings_char4`
- `gram_stats_char4`
- 更新后的 `doc_features.coarse_char4_json`

约束：

- 这是独立离线阶段，不与 `build batch` 混跑
- 允许全量批量构建，不做逐文档增量 upsert
- 优先使用 bulk build，而不是 row-by-row 更新
- rebuild 失败时不得污染在线稳定索引

### 5. 自动断点续跑

系统需要维护独立 checkpoint，例如：

- `next_cursor`
- `has_more`
- `updated_at`
- `last_task_id`

无论是 API 触发还是离线命令触发，都应默认自动读取 checkpoint 续跑，而不是要求用户手动传 cursor。

## 当前实现要求

后续代码必须遵守下面边界：

1. 禁止恢复原来的危险全量 refresh 设计
2. `refresh` API 默认只能触发轻量短任务，或直接退化为 `scan-only`
3. 文档 ingest 与 coarse index rebuild 必须解耦
4. 真正的解析建库必须按小批次离线执行
5. 每批必须天然可恢复，不依赖长时间存活的后台进程
6. 短任务模式下，未完成全量扫描时禁止执行“缺失文档删除”
7. 本地离线 ingest 必须写入独立目录 `data/plagiarism/local_ingest/`
8. 独立目录内至少包括：

- `corpus_index.json`
- `corpus_index.db`
- `corpus_manifest.json`
- `corpus_refresh_checkpoint.json`

这样做的目的很明确：

- 避免与旧 refresh 进程或在线索引抢同一个 SQLite 文件
- 避免 manifest / checkpoint 被旧流程污染
- 保证本地镜像建库是可重置、可重跑、可定位问题的一条独立链路

## 维护流程

### 1. 查看库状态

```bash
curl 'http://127.0.0.1:8888/api/v1/plagiarism/corpus/status'
```

### 2. 使用统一脚本执行离线维护

```bash
scripts/corpus_safe.sh scan 2000
scripts/corpus_safe.sh ingest-docs 20 4
scripts/corpus_safe.sh rebuild-coarse
```

常用组合：

```bash
scripts/corpus_safe.sh step 2000 20 4
scripts/corpus_safe.sh loop 10 2000 20 4
scripts/corpus_safe.sh status
scripts/corpus_safe.sh reset
```

推荐直接使用单入口：

```bash
scripts/corpus_safe.sh run-all 2000 20 4
```

约束：

- 该命令只操作 `data/plagiarism/local_ingest/` 下的离线产物
- 默认读取本地镜像目录，而不是远端挂载目录
- 允许解析阶段并发，但不允许多进程同时写同一个 SQLite
- `run-all` 应先完成 docs/doc_features ingest，再单独 rebuild coarse index

### 3. 最终目标

最终目标不是继续保留 API 式全量 refresh，而是：

- API 只读
- `scan manifest` 独立
- `build batch` 独立
- 小步可恢复

## 后续优化方向

按优先级排序：

1. 废弃危险全量 refresh，切到 `scan manifest + build batch`
2. 把解析建库彻底移出 API 进程
3. 继续压缩 SQLite 批写入放大
4. 把多对多任务调度与在线单篇查重彻底解耦
5. 在召回层加入更稳的高频 gram 控制与查询预算

当前推荐的粗召回写入策略：

- `build batch` 只写完整特征到 `doc_features`
- `rebuild coarse index` 再统一生成 `postings_char4`
- `postings_char4` 只写“代表性粗召回特征”
- 代表性特征必须是确定性选择，而不是每次随机抽样

代表性特征选择规则：

- 优先保留已有统计中低 `df` 的 gram
- 保证全文分段覆盖，避免全部集中在局部
- 对高频模板 gram 做自然抑制
- 首次全量构建时，允许先按覆盖稳定选取，再由后续 rebuild 持续校正
- 最终仍受每篇文档的粗召回预算约束

原因：

- 在每个 ingest batch 内增量维护全局倒排，会导致 SQLite 写放大严重且随库规模恶化
- 粗召回本来就不需要保存每篇文档的全部 gram
- 业界通常会把“倒排召回特征”和“重排特征”分层存储

## 参考

- Lucene Index / Postings / Stored Fields
  https://lucene.apache.org/core/9_5_0/core/org/apache/lucene/index/package-summary.html
  https://lucene.apache.org/core/9_9_1/core/org/apache/lucene/index/StoredFields.html
- Elasticsearch `_source` / Stored Retrieval
  https://www.elastic.co/guide/en/elasticsearch/reference/current/mapping-source-field.html
- Vespa Phased Ranking
  https://docs.vespa.ai/en/phased-ranking.html
