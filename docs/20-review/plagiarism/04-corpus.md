# 比对库管理 (Corpus Management)

## 概述

比对库是查重服务的核心资源，包含了历史申报书、学术论文等参考文档。为了支持大规模查重并解决远程附件访问性能问题，系统采用了“本地特征索引 + 远程原文挂载”的设计。

## 架构设计

### 1. 远程挂载 (Remote Mounting)

库文件（PDF/DOCX 附件）物理上存储在另一台服务器。
- **方案**：使用 NFS 或 Samba 将远程目录挂载到查重服务器的 `/mnt/remote_corpus/`。
- **优点**：代码层面无需感知网络传输，直接读取本地路径。

### 2. 预索引机制 (Pre-indexing)

查重时实时解析数万份文档是不可接受的，因此必须进行预索引。

- **扫描器 (Scanner)**：定期遍历挂载目录，监控文件变更。
- **特征提取**：
    - 调用 `src/common/file_handler` 解析文档正文。
    - 使用 `src/services/plagiarism/retrieval.py` 中的算法提取 N-gram 指纹。
- **本地持久化**：将提取的特征、文档元数据（路径、哈希、字符数）存储在本地索引文件 `data/corpus_index.json` 或本地数据库中。

### 3. 延迟加载 (Lazy Loading)

- **召回阶段**：仅使用内存中的 N-gram 特征索引进行快速匹配，不读取文件原文。
- **比对阶段**：仅针对召回出的 Top-K 候选文档，通过挂载路径实时读取并解析文件原文，进入 `ComparisonEngine`。

## 核心组件 (src/services/plagiarism/corpus.py)

### `CorpusManager` 类

负责管理整个库的生命周期。

| 方法 | 说明 |
|------|------|
| `scan_and_update(limit)` | 扫描挂载目录并增量更新索引（合并扫描与构建） |
| `save_index()` | 将索引持久化到本地磁盘 |
| `load_index()` | 启动时加载索引到内存 |
| `get_document_text(doc_id)` | 根据 ID 延迟加载远程文件正文 |

### 索引数据结构 (Example)

```json
{
  "documents": {
    "doc_001": {
      "path": "/mnt/remote_corpus/2024/report_01.docx",
      "hash": "a1b2c3d4",
      "char_count": 15600,
      "features": {
        "char4": ["f1", "f2", "..."],
        "char8": ["h1", "h2", "..."]
      }
    }
  }
}
```

## 维护流程

1. **库初始化**：
   ```bash
   python scripts/manage_corpus.py --action build --path /mnt/remote_corpus/
   ```

2. **查看状态**：
   ```bash
   python scripts/manage_corpus.py --action status
   ```
   或通过 API：`GET /api/v1/plagiarism/corpus/status`

3. **增量更新**：
   ```bash
   python scripts/manage_corpus.py --action refresh --limit 100
   ```
   或通过 API：`POST /api/v1/plagiarism/corpus/refresh`

## 性能表现

- **召回耗时**：针对 5 万份文档的 N-gram 特征检索，耗时 < 200ms。
- **存储开销**：索引文件大小约为库文档总字数的 5%-10%。
