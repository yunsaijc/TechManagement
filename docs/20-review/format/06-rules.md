# 📋 规则系统

## 概述

规则系统是形式审查的核心，负责定义和执行各种检查规则。

## 规则定义

规则以 Python 类形式存在，继承 `BaseRule`：

```python
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry

@RuleRegistry.register
class StampConsistencyRule(BaseRule):
    """盖章单位与填写单位一致性检查"""
    
    name = "stamp_consistency"
    description = "检查盖章单位与填写的工作单位是否一致"
    priority = 10
    
    async def should_run(self, context: ReviewContext) -> bool:
        """判断是否需要执行此规则"""
        return context.document_type in ["retrieval_report", "paper"]
    
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检查
        
        从预提取的内容中获取：
        - OCR 提取的文字 → 正则解析出工作单位
        - LLM 识别的印章图像 → 提取盖章单位
        然后对比一致性
        """
        # 从 OCR 文本解析的工作单位
        work_units = context.content.get("work_units", [])
        
        # 从 LLM 识别的印章单位
        stamps = context.extracted.get("stamps", [])
        stamp_units = [s.get("unit") for s in stamps if s.get("unit")]
        
        # 检查逻辑：每个盖章单位是否在工作单位列表中
        for stamp_unit in stamp_units:
            if stamp_unit not in work_units:
                return CheckResult(
                    item=self.name,
                    status=CheckStatus.FAILED,
                    message=f"盖章单位'{stamp_unit}'与填写的工作单位不一致",
                    evidence={"stamp_unit": stamp_unit, "work_units": work_units},
                )
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="盖章单位与工作单位一致",
        )
```

## 规则属性

| 属性 | 说明 |
|------|------|
| `name` | 规则唯一标识 |
| `description` | 规则描述 |
| `priority` | 执行优先级，数字越大越先执行 |

## 规则配置

不同文档类型对应不同规则：

```python
# src/services/review/rules/config.py

RULES_BY_DOCUMENT = {
    "检索报告": [
        "stamp_check",        # 盖章检查
        "signature_check",    # 签字检查
        "stamp_consistency",  # 盖章与单位一致性
        "completeness",      # 完整性检查
    ],
    "论文": [
        "title_check",       # 标题检查
        "author_check",     # 作者检查
    ],
    "验收报告": [
        "stamp_check",
        "signature_check",
        "prerequisite",     # 前置条件
    ],
}

def load_rules(document_type: str) -> List[BaseRule]:
    """根据文档类型加载对应规则"""
    rule_names = RULES_BY_DOCUMENT.get(document_type, [])
    return [RuleRegistry.get_rule(name)() for name in rule_names]
```

## 执行流程

```
Agent 流程：
1. extract() → 一次性提取内容 (ExtractedContent)
2. load_rules(document_type) → 加载该文档类型对应的规则
3. for rule in rules:
       result = await rule.check(context)
4. 聚合结果
```

### 流程图

```
┌─────────────────────────────────────────────────────┐
│                   上传 PDF                              │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  1. extract() 提取内容                             │
│     └── ExtractedContent({key: value})              │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  2. load_rules(document_type)                      │
│     → 根据文档类型加载对应规则列表                   │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  3. 遍历执行规则                                   │
│     for rule in rules:                             │
│         result = await rule.check(context)           │
│     → List[CheckResult]                            │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  4. 聚合结果 → 返回审查报告                       │
└─────────────────────────────────────────────────────┘
```

## 如何新增规则

1. **创建规则类**：在 `rules/checkers/` 下创建新规则类
2. **注册规则**：使用 `@RuleRegistry.register` 装饰器
3. **配置规则**：在 `RULES_BY_DOCUMENT` 中添加规则适用的文档类型

### 示例：新增"单位一致性检查"规则

```python
# src/services/review/rules/checkers/consistency.py

from src.common.models.review import CheckResult, CheckStatus
from src.services.review.rules.base import BaseRule, ReviewContext
from src.services.review.rules.registry import RuleRegistry

@RuleRegistry.register
class UnitConsistencyRule(BaseRule):
    """单位一致性检查"""
    
    name = "unit_consistency"
    description = "检查文档中各单位的填写是否一致"
    priority = 20
    
    async def check(self, context: ReviewContext) -> CheckResult:
        # 获取提取的内容
        units = context.content.get("units", [])
        
        # 检查逻辑：工作单位是否都在完成单位列表中
        work_units = context.content.get("work_units", [])
        
        inconsistent = [w for w in work_units if w not in units]
        
        if inconsistent:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"工作单位填写错误: {inconsistent}",
                evidence={"inconsistent_units": inconsistent},
            )
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="单位信息一致",
        )
```

然后在配置中添加：

```python
RULES_BY_DOCUMENT = {
    "检索报告": [..., "unit_consistency"],
}
```

## 现有规则

| 规则 | 说明 |
|------|------|
| `stamp_check` | 盖章检查 |
| `signature_check` | 签字检查 |
| `prerequisite` | 前置条件检查 |
| `completeness` | 完整性检查 |

## 相关文档

- [文档解析方案 →](04-document-parser.md)
- [Agent 设计 →](03-agent.md)
- [规则引擎设计 →](02-rules.md)
