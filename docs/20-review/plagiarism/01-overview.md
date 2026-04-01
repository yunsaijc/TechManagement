# 查重服务概述

## 服务定位

查重服务旨在通过对比用户上传的申报材料（Primary）与预定义的比对库（Corpus）中的历史申报文档、学术资源等，识别其中的字面重复、改写重复和模板化重复。

服务核心能力：
- **库驱动查重**：支持从大规模预索引库（Corpus）中自动召回可疑来源。
- **Primary 驱动归并**：以主文档为中心，自动合并来自多个来源的重叠命中。
- **有效重复统计**：计算主文档去重后的物理重复覆盖率，而非简单的 Pairwise 相似度。
- **Mammoth HTML 报告**：生成保留 Word 原始格式的高亮查重报告。

## 模块定位

```text
src/services/plagiarism/
├── api.py                       # 接口入口
├── agent.py                     # 流程编排（库召回 + 精比对 + 归并）
├── corpus.py                    # [New] 比对库管理（挂载扫描、预索引、延迟加载）
├── retrieval.py                 # 候选来源召回（基于 N-gram 指纹索引）
├── config.py                    # Section / 过滤配置
├── section_extractor.py         # Primary 检测区提取
├── tokenizer.py                 # 语义分句与原文位置映射
├── template_prefilter.py        # 前置排除区间标记
├── template_filter.py           # 模板/短句/标题后置过滤
├── engine.py                    # 细粒度比对内核（Winnowing + 连续区间）
├── aggregator.py                # Pairwise 片段清洗
├── multi_source_aggregator.py   # Primary-centered 多源归并与统计
└── mammoth_report_builder.py    # 多源查重 HTML 报告生成
```

## 核心业务链路

```text
上传 Primary 文档
  -> 文本提取（PDF/DOCX）
  -> 检测区提取 (Section Extraction)
  -> 库查重召回 (Corpus Retrieval)
     - 先基于倒排索引做粗召回，再做窗口级重排
  -> 候选文档按需加载 (Lazy Loading)
     - 仅对最终 Top-K 候选从远程挂载目录读取正文
  -> 细粒度比对 (Fine-grained Matching)
     - 对每个候选来源运行精比对内核
  -> 多源归并 (Multi-source Merging)
     - 以 Primary 坐标系合并所有来源的命中片段
  -> 结果统计与报告生成
     - 计算有效重复率，生成 Mammoth HTML
```

## 库管理原则 (Corpus Principles)

针对“附件位于远程服务器”的场景，遵循以下原则：
- **挂载访问**：通过 NFS/Samba 挂载远程目录，逻辑上视为本地访问。
- **特征预存**：库中文档的元数据、特征分片与倒排索引预先计算并持久化，避免查重时实时解析。
- **分阶段召回**：先缩小候选范围，再加载少量候选特征，最后才读取原文。
- **按需读取**：仅在精比对阶段读取最终 Top-K 文档原文。

## 统计口径

- **有效重复率 (Effective Duplicate Rate)**：
  主文档检测区内，去重后的重复覆盖字符数 / 主文档检测区总字符数。
- **排除项策略**：
  默认排除参考文献、引文、系统模板以及低于 15 字的细碎匹配。

- 不推翻当前细粒度内核
- 先补多源召回，再补多源归并
- 先稳统计口径，再升级报告结构
- 所有最终展示继续以 `mammoth` HTML 为准

## 相关文档

- [Agent 设计](03-agent.md)
- [比对库管理](04-corpus.md)
- [API 接口文档](05-api.md)
