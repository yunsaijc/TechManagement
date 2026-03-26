# 绩效核验规则设计

## 设计思路

规则层目标是把“抽取结果”稳定转换为“可审查结论”，核心原则：

1. 章节先约束，再比较，避免跨章节污染。
2. 金额/数值类规则优先于描述类规则。
3. 所有结果收敛到 GREEN/YELLOW/RED，便于下游展示与统计。

## 风险等级

当前实现统一使用三档风险：

- GREEN：一致或可接受差异
- YELLOW：存在提示性差异
- RED：存在明确不一致或高风险差异

## 指标规则（metrics_risks）

### 范围约束

- 仅比较申报书“五、项目实施的预期绩效目标”与任务书“七、项目实施的绩效目标”。
- 年度/阶段/里程碑类中间指标默认不进入最终对齐。

### 对齐规则

1. 指标名标准化后先做规则直匹配。
2. 直匹配失败时走相似度+LLM精排确认。
3. 指标去重按“指标名+单位”，重复来源优先级：绩效指标/考核指标 > 总体目标补齐。

### 风险判定

- 任务书指标缺失：RED
- 数值下降：RED
- 指标等级降级：RED
- 约束变模糊且无法证明同等严格：YELLOW
- 其余情况：GREEN

## 研究内容规则（content_risks）

- 以申报书条目为基准，判断任务书覆盖情况。
- 规范化后完全一致时直接 coverage_score=1.0。
- 全部覆盖：GREEN
- 部分覆盖：YELLOW
- 全部不覆盖或任务书无内容：RED

## 预算规则（budget_risks）

### 总额规则

- 预算总额不一致：RED
- 预算总额一致：GREEN

### 科目规则

- 金额不一致优先判 RED。
- 在金额一致前提下，占比变化超过阈值 budget_shift_threshold（默认 0.10）判 YELLOW；极大变化判 RED。

### 特殊规则

- 如果已存在“预算总额”，预算科目中的“合计/总计”行不再输出，避免重复和误报。

## 核心代码结构

```python
def _check_budget(self, apply_budget, task_budget, threshold):
	risks = []
	total_a = float(getattr(apply_budget, "total", 0.0) or 0.0)
	total_t = float(getattr(task_budget, "total", 0.0) or 0.0)

	# 1) 先比较预算总额
	if total_a > 0 or total_t > 0:
		...

	# 2) 再比较科目明细；存在预算总额时过滤“合计/总计”
	apply_seq = [(item.type, float(item.amount or 0.0)) for item in getattr(apply_budget, "items", []) or []]
	task_seq = [(item.type, float(item.amount or 0.0)) for item in getattr(task_budget, "items", []) or []]
	if total_a > 0 or total_t > 0:
		apply_seq = [(t, a) for t, a in apply_seq if t.replace(" ", "") not in {"合计", "总计"}]
		task_seq = [(t, a) for t, a in task_seq if t.replace(" ", "") not in {"合计", "总计"}]
	...
```

## 使用示例

```python
detector = PerfCheckDetector()
risks = detector._check_budget(apply_budget, task_budget, threshold=0.10)
for r in risks:
	print(r.type, r.risk_level, r.reason)
```

## 其他信息规则（other_risks）

- 比较项目名称、承担单位、合作单位、项目组成员及分工。
- 项目组成员判定采用“成员缺失 + 分工覆盖”规则。

## 单位预算规则（unit_budget_risks）

- 按单位聚合金额，比较“合计”差异。
- 金额不一致：RED；一致：GREEN。

## 可配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| budget_shift_threshold | 0.10 | 预算占比变动阈值 |
| strict_mode | true | 预留参数，当前主流程保持兼容 |
| enable_llm_enhancement | false | 预留开关 |
| enable_llm_entailment | true | LLM语义校验开关 |