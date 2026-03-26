# 🤖 Agent 设计

## 概述

`PlagiarismAgent` 负责统一编排查重流程。设计原则是：在现有架构上增量优化，不拆服务、不换入口、不推翻主算法。

- 入口保持：`PlagiarismAgent.check(...)`
- 主链路保持：分句 -> 过滤 -> Winnowing 比对 -> 聚合
- 展示保持：仅输出 `mammoth` 报告

## Agent 职责

1. 文件与文本准备
- 调用提取器读取 PDF/DOCX
- 组织 `doc_id -> text` 与位置映射

2. 预处理与过滤
- 分句（保留 `start/end`）
- 前置模板过滤（标题、表格、低信息句）

3. 比对与补强
- `exact`：沿用 N-gram + Winnowing 连续区间
- `paraphrase`：在 `exact` 窗口内补做句级相似对齐

4. 聚合与输出
- 合并片段、去重、分类（有效/模板）
- 生成 debug JSON
- 生成最终 `plagiarism_report_mammoth.html`

## 架构分层

```text
Layer 6: Agent/API
  PlagiarismAgent + api.py

Layer 5: Detection/Aggregation
  tokenizer.py
  template_prefilter.py
  template_filter.py
  ngram.py
  engine.py
  aggregator.py
  mammoth_report_builder.py

Layer 4: Parser
  pdf_parser.py / docx_parser.py
```

## 执行流程（增量版）

```text
check(files)
  -> extract_text
  -> section_extract
  -> sentence_tokenize
  -> template_prefilter
  -> exact_detect (engine)
  -> paraphrase_expand (engine, 邻域句级补全)
  -> aggregate (aggregator)
  -> debug_dump
  -> mammoth_render
```

## 核心模块协作

### `engine.py`

- 保留现有 `compare()` 主行为
- 增量新增：
- `exact` 片段邻域句级补全
- `match_type` 与 `confidence` 计算
- 相邻改写句合并为连续段

### `aggregator.py`

- 保持原输出骨架不变
- 片段增量字段：
- `match_type`: `exact` / `paraphrase`
- `confidence`: 0~1
- `parent_match_id`: 改写片段关联的 exact 片段

### `mammoth_report_builder.py`

- 仅做展示，不改检测结论
- 双层高亮：
- 深色：`exact`
- 浅色：`paraphrase`
- 导航筛选：全部 / exact / paraphrase
- 定位状态：完整 / 核心 / 未定位

## 结果模型（兼容扩展）

示例（片段级）：

```json
{
  "match_id": "m001",
  "match_type": "exact",
  "confidence": 0.98,
  "parent_match_id": null,
  "primary_start": 51,
  "primary_end": 132,
  "sources": [
    {
      "doc": "相似组2-B.docx",
      "start": 2237,
      "end": 2315
    }
  ]
}
```

## 约束与边界

- 不新增微服务，不改路由协议
- 不替换 Winnowing 主链路，只做旁路补强
- 最终可视化只交付 `mammoth` HTML

## 验收标准

1. 长段改写召回
- 从“单句命中”提升到“句群命中”

2. 边界质量
- 片段首尾尽量对齐句边界

3. 展示一致性
- Word 原样保留
- 高亮长度与检测片段一致，可解释

4. 可回归
- debug JSON 能区分 `exact` / `paraphrase`
- 参数变更前后可对比统计差异

## 相关文档

- [概述](01-overview.md)
- [API 接口](03-api.md)
