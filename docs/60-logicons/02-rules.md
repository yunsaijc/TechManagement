# 📋 逻辑一致性规则设计

## 概述

规则引擎负责对文档内部实体关系进行一致性校验，重点覆盖时间、资金、指标三类冲突，并输出可定位的证据。

## 设计思路

1. **先抽取再比对**：先形成结构化实体，再执行规则判断。
2. **数学规则优先**：金额、时间等可计算规则先判定，降低误报。
3. **语义规则补充**：对文本冲突用 LLM 辅助判定并返回解释。
4. **证据必须可追溯**：每条冲突附带章节、页码、原文片段。

---

## 规则分类

### 1. 时间一致性规则（Timeline Rules）

| 规则编码 | 规则说明 | 示例 |
|----------|----------|------|
| `T001` | 项目执行期与任务进度跨度一致 | 执行期 2025-2026，进度出现 2028 |
| `T002` | 里程碑时间必须落在项目起止时间内 | 里程碑写到结题后 |
| `T003` | 年度计划不允许缺年或跳年（可配置） | 2025 后直接到 2027 |

### 2. 资金一致性规则（Budget Rules）

| 规则编码 | 规则说明 | 示例 |
|----------|----------|------|
| `B001` | 资金申请总额 = 分项合计（容差可配） | 总额 50 万，分项合计 70 万 |
| `B002` | 年度资金合计 = 总预算 | 年度合计与总预算不一致 |
| `B003` | 资金来源拆分 = 来源总额 | 财政/自筹/配套合计超出总额 |

### 3. 指标一致性规则（Indicator Rules）

| 规则编码 | 规则说明 | 示例 |
|----------|----------|------|
| `I001` | 总体指标与分阶段指标关系一致 | 总目标 10 项，阶段合计仅 6 项 |
| `I002` | 指标单位前后一致 | 前文万元，后文元 |
| `I003` | 关键术语语义一致 | 项目名称或技术路线前后矛盾 |

---

## 规则执行流程

```
输入: 文档实体 + 临时知识图谱
  │
  ├─> 1. 确定规则集合 (按文档类型)
  ├─> 2. 执行数学类规则 (B/T)
  ├─> 3. 执行语义类规则 (I)
  ├─> 4. 冲突分级 (high/medium/low)
  └─> 5. 输出证据链与建议
```

---

## 核心代码结构

```python
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class ConflictEvidence:
    section: str
    page: int
    quote: str


@dataclass
class ConflictItem:
    rule_code: str
    severity: str
    message: str
    evidences: List[ConflictEvidence]


class BaseConsistencyRule:
    """逻辑一致性规则基类"""

    code: str = "BASE"

    def check(self, graph: Dict) -> List[ConflictItem]:
        raise NotImplementedError


class BudgetSumRule(BaseConsistencyRule):
    """B001: 总额与分项合计一致"""

    code = "B001"

    def __init__(self, tolerance: float = 0.01):
        self.tolerance = tolerance

    def check(self, graph: Dict) -> List[ConflictItem]:
        total = graph.get("budget_total", 0.0)
        details = graph.get("budget_details", [])
        detail_sum = sum(item.get("amount", 0.0) for item in details)

        if total == 0:
            return []

        diff_ratio = abs(detail_sum - total) / total
        if diff_ratio <= self.tolerance:
            return []

        return [
            ConflictItem(
                rule_code=self.code,
                severity="high",
                message=f"资金总额与分项合计不一致: 总额={total}, 合计={detail_sum}",
                evidences=[]
            )
        ]
```

---

## 使用示例

```python
from services.logicons.rules import BudgetSumRule

graph = {
    "budget_total": 500000.0,
    "budget_details": [
        {"name": "设备费", "amount": 250000.0},
        {"name": "材料费", "amount": 220000.0},
        {"name": "测试费", "amount": 180000.0},
    ]
}

rule = BudgetSumRule(tolerance=0.02)
conflicts = rule.check(graph)
print(conflicts[0].message)
```

---

## 阈值配置建议

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `budget_tolerance` | 0.01 | 预算容差比例（1%） |
| `timeline_grace_days` | 0 | 时间边界宽限天数 |
| `semantic_confidence` | 0.75 | 语义冲突最低置信度 |
