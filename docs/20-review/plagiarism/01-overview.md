# 🔍 查重服务概述

## 服务定位

查重服务用于识别申报材料中的重复、改写重复和模板化内容，输出可解释、可复核的比对结果。最终展示以 `mammoth` HTML 为准。

## 设计目标

- **召回有效重复**：覆盖字面重复与改写重复
- **控制误报**：抑制模板句、表格结构、短碎片噪声
- **边界可用**：重复片段的起止位置尽量贴近人工判断
- **展示可信**：Word 原貌保留，且高亮与检测结果一致
- **检测区域可控**：仅对 `primary` 的业务正文区域查重

## 当前架构（基于现有代码）

### 核心能力

1. **文本提取**
- PDF：`common/file_handler/pdf_parser.py`
- DOCX：`common/file_handler/docx_parser.py`

2. **Primary 检测区截取（配置驱动）**
- 仅对 `primary docx` 执行 Section 截取
- `source` 文档默认全文参与比对，不做区域裁剪
- 截取器：`section_extractor.py`

3. **分句与预过滤**
- 语义分句：`tokenizer.py`
- 前置模板过滤：`template_prefilter.py`
- 模板判定：`template_filter.py`

4. **查重主链路**
- N-gram 切分：`ngram.py`
- 指纹比对 + 连续区间：`engine.py`（Winnowing）
- 结果聚合：`aggregator.py`

5. **报告输出**
- 最终报告：`mammoth_report_builder.py`
- 最终交付文件：`debug_plagiarism/plagiarism_report_mammoth.html`

### 现存问题（已验证）

- 对“长段改写型相似”召回不足，常退化为短句命中
- 检测边界偏短会直接限制 HTML 高亮范围
- 局部片段可命中，但整段连续性不足，影响人工观感

## 业界实践对齐（知网/Turnitin 类）

主流方案不是单一算法，而是分层流程：

1. **候选召回**：优先保召回（能找到可疑段）
2. **细粒度对齐**：做边界校准（字符/句子级）
3. **结果过滤**：排除模板、引用、小片段噪声
4. **报告解释**：区分命中类型并支持人工复核

## 本项目增量改造路线（不推翻现有实现）

### 阶段 A：检测层补强（`engine.py`）

- 保留现有 `exact`（字面重复）主链路
- 在 `exact` 命中窗口内补做句级相似对齐，产出 `paraphrase`
- 合并邻接句，改善长段边界

### 阶段 B：聚合层扩展（`aggregator.py`）

- 保持 `duplicate_segments` 主结构
- 增加字段：`match_type`、`confidence`、`parent_match_id`
- 兼容现有 API/debug，不改路由协议

### 阶段 C：展示层增强（`mammoth_report_builder.py`）

- 仅维护 `mammoth` 报告
- 双层高亮：`exact` 深色、`paraphrase` 浅色
- 导航筛选：全部 / 仅 exact / 仅 paraphrase
- 保持 Word 原貌，仅叠加高亮

### 阶段 D：过滤微调（`template_filter.py` / `template_prefilter.py`）

- 调整正文语句与模板语句的判定阈值
- 降低“本应保留却被预过滤”的漏检

## 统一流程（改造后）

```text
上传文件
  -> 文本提取（PDF/DOCX）
  -> Primary Section 提取（仅 primary）
  -> 分句与位置映射
  -> 前置过滤（模板/表格/短句）
  -> Exact 检测（N-gram + Winnowing）
  -> Paraphrase 补全（句级相似）
  -> 片段合并与去重
  -> 后置过滤与打分
  -> 结果聚合
  -> Mammoth HTML 渲染（最终交付）
```

## Section 配置约定（Primary Only）

- `primary`：必须配置待检区域（起止边界）
- `source`：不配置区域，直接全文比对
- 建议优先用“标题到标题”的边界模式，避免固定行号/固定字符位偏移

示例：

```json
{
  "primary_scope": {
    "start_pattern": "项目立项背景及意义",
    "end_pattern": "三、项目实施方案"
  }
}
```

说明：
- 实际运行时仅从 `primary` 提取 `start_pattern` 到 `end_pattern` 之间文本进入检测。
- `source` 仍保留全文，以最大化召回。

## 调参原则

- 先稳边界，再扩召回
- 参数调整与展示逻辑分离验证
- 统一以样本集比较改造前后结果

| 参数 | 方向 | 目标 |
|------|------|------|
| `min_continuous_match` | 适度下调或保持 | 保证连续命中稳定性 |
| `min_match_length` | 分层阈值（exact/paraphrase） | 降低短碎片噪声 |
| `max_fingerprint_frequency` | 结合样本微调 | 抑制高频模板误连 |
| 句级相似阈值（新增） | 从严到松迭代 | 控制改写误报 |

## 模块结构

```text
src/services/plagiarism/
├── api.py
├── agent.py
├── config.py
├── tokenizer.py
├── template_prefilter.py
├── template_filter.py
├── ngram.py
├── engine.py
├── aggregator.py
└── mammoth_report_builder.py
```

## 下游文档

- [Agent 设计](02-agent.md)
- [API 接口文档](03-api.md)
