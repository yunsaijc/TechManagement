# LogicOn Agent 设计

## Agent 职责

LogicOnAgent 负责将“整份文档”作为整体进行处理，输出结构化冲突结果：

- 组织解析与抽取的执行顺序
- 构建文档内部知识图谱（用于跨章节关联）
- 执行规则集与可选的语义判定
- 聚合冲突并生成报告载荷

## 处理步骤

1. 输入归一化

- 支持 PDF/DOCX 文件或纯文本
- 统一得到 `raw_text` 与 `chunks`（带章节/页码/片段定位信息）

2. 分段与章节识别

- 识别“基本信息/执行期”“进度安排”“预算表/预算明细”“绩效目标/考核指标”等关键章节
- 输出 `sections[]`，每个 section 具备可定位的 `DocSpan`

3. 实体抽取与归一化

- 时间：执行期起止/年限、里程碑日期、年度集合
- 财务：总额、科目明细、单位预算明细、资金来源
- 指标：指标名、目标值、单位、约束
- 人员/组织：承担单位、合作单位、成员与分工

抽取策略：

- 数值/日期：优先规则抽取（正则/表格行解析/单位换算）
- 语义字段：必要时使用 LLM 辅助抽取（可开关）

4. 图谱构建

- 将实体与其证据片段（DocSpan）建立 `appears_in` 关联
- 将同义实体聚合为“事实节点”（如“执行期=24个月”）

5. 冲突检测

- 先执行确定性规则（预算求和、执行期跨度）
- 可选执行语义冲突规则（同义指标聚类、口径冲突）

6. 输出与报告

- 输出 `ConflictItem[]`（包含 severity/category/evidence）
- 可选返回 `DocumentGraph` 以便前端展示或调试

## 与现有模块复用点

### 1) 复用文件解析

- `src/common/file_handler` 已支持 PDF/DOCX → `DocumentContent`
- 复用其输出的文本/页码信息，作为 `DocSpan` 的定位来源

### 2) 复用 perfcheck 的结构化抽取

perfcheck 已覆盖预算与指标抽取（并包含表格行纠偏逻辑），可作为 LogicOn 的一个抽取子模块：

- 预算：总额与科目明细
- 单位预算：承担单位/合作单位预算明细
- 指标：绩效目标表中的量化指标

LogicOn 需要补充：

- 执行期抽取与归一化
- 进度安排（里程碑/年份集合）抽取
- “同一指标多处出现”的同义归并与冲突判定

## 可配置项

- `enable_llm`: 是否启用 LLM 辅助抽取/语义冲突判定
- `return_graph`: 是否返回 `DocumentGraph`
- `amount_tolerance` / `date_tolerance_days` / `metric_tolerance_ratio`

## 输出对齐

API 输出结构与 perfcheck 的风格保持一致：

- 同步接口直接返回 `LogicOnResult`
- 异步接口返回 `task_id`，任务状态结构复用现有 `PerfCheckTask` 形态
