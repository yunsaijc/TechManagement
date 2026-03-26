# 文档解析方案（PerfCheckParser）

## 设计思路

解析层遵循“章节硬约束优先、LLM补充其次、规则纠偏兜底”的策略：

1. 先按标题定位核心章节，缩小抽取范围。
2. 再由 LLM 提取结构化字段。
3. 最后用规则补齐和去重，保证可比对性。

## 设计原则

解析策略为“章节硬约束 + 表格规则 + LLM补充 + 后处理纠偏”。

关键目标：

1. 核心章节必须稳定命中
2. 表格字段优先于自由文本
3. 结果可用于 detector 的可比对结构

## 当前抽取对象

- project_name
- research_contents
- performance_targets
- budget
- basic_info（undertaking_unit/partner_units/team_members）
- units_budget

## 章节硬约束

### 绩效目标章节

- 申报书：项目实施的预期绩效目标（第五部分）
- 任务书：项目实施的绩效目标（第七部分）

### 研究内容章节

- 申报书：项目实施内容及目标
- 任务书：项目实施的主要内容任务

### 成员分工章节

- 申报书：项目组主要成员（兼容第四/第六部分标题）
- 任务书：六、参加人员及分工

## 绩效目标后处理

1. 先标准化 LLM 返回指标（避免 type 泛化）。
2. 补齐顺序固定：
   - 先绩效指标（三级指标+指标值）与满意度
   - 再补总体目标-实施期目标缺失项
3. 去重键为“指标名+单位”，同名优先保留绩效指标来源。
4. 剔除年度/阶段中间项。

## 成员抽取规则

- 支持“姓名/旧值:新值；分工/旧值:新值”的压缩表格行。
- 记录时优先取冒号右侧当前值。
- 与 LLM 基本信息结果做去重合并。

## 预算抽取规则

- 优先项目预算表与单位预算明细表。
- 支持规则兜底回填预算明细。
- 保留预算总额与科目明细，供 detector 做金额与占比比较。

## 长文档处理说明

- 不再做全局头尾截断。
- 原因：长文档中段常包含绩效表和成员表，截断会导致核心信息漏抽。
- 当前做法是保留全文，再对各主题窗口按 max_chars 控制长度。

## 核心代码结构

```python
async def extract_schema_from_text(self, text: str, source_file_type: Optional[str] = None) -> DocumentSchema:
   raw = self._strip_filling_instructions(text)
   doc_kind = self._detect_doc_kind(raw)

   required_metrics_text = self._extract_required_metrics_sections(raw=raw, doc_kind=doc_kind)
   required_members_text = self._extract_required_team_members_sections(raw=raw, doc_kind=doc_kind)

   # LLM抽取 + 规则补齐
   performance_targets = self._normalize_performance_targets(metrics_data.get("performance_targets") or [])
   performance_targets = self._supplement_performance_targets(performance_targets, required_metrics_text)
   performance_targets = self._keep_overall_targets_only(performance_targets, required_metrics_text)
   ...
```

## 使用示例

```python
parser = PerfCheckParser()
schema = await parser.extract_schema_from_text(raw_text, source_file_type="docx")
print(schema.project_name)
print(len(schema.performance_targets), len(schema.basic_info.team_members if schema.basic_info else []))
```