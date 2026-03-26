# 📄 正文解析器设计

## 设计目标

解析器不仅服务九维评审，还要为“划重点、问答、证据追溯”提供统一输入。  
因此输出要同时包含：

1. 章节化文本（供 checker/摘要模块）  
2. 页码级切片（供问答与证据定位）

## 输入与输出

### 输入

- 文件路径（`pdf/docx/doc`）
- 或由项目仓库解析出的主文档路径

### 输出（统一结构）

- `sections: Dict[str, str]`：章节内容
- `page_chunks: List[Chunk]`：页码切片（含 `page/text/section`）
- `meta`：文件名、解析时间、解析器版本

## 解析流程

```
文件读取 -> 文本抽取 -> 清洗归一化 -> 章节识别 -> 页码切片 -> 输出结构化结果
```

## 章节识别策略

1. 标题规则匹配（技术路线、创新点、团队、成果等）  
2. 别名归一（同义标题映射到统一章节名）  
3. 模糊回退（无法精确命中时按相似度归类）

## 页码切片策略

- PDF：优先保留原始页码  
- DOCX：按分页符/段落长度生成近似页块，并在 `meta` 标记 `page_estimated=true`  
- 每个 chunk 保存最小可引用片段，便于回答时给出证据

## 与聊天能力的关系

`/chat/ask` 不直接读整篇文档，而是检索 `page_chunks` 索引。  
回答必须返回引用：

- `file`
- `page`
- `snippet`

## 与评审能力的关系

- 九维 checker 读取 `sections`
- 划重点模块优先读取 `sections`，缺失时回退 `page_chunks`
- 指南贴合和技术摸底在生成结论时回填证据引用

## 异常处理

- 空文档/乱码：返回 `PARSE_ERROR`
- 部分页解析失败：保留成功页并标记 `partial_parse=true`
- 不支持格式：返回可读错误并建议转为 PDF/DOCX

## 代码锚点

- 解析器实现：`src/services/evaluation/parsers/document_parser.py`
- 文件处理：`src/common/file_handler/`
- 后续问答索引：`src/services/evaluation/chat/indexer.py`（规划中）
