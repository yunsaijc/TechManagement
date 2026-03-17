# 📋 规则引擎设计

## 概述

规则引擎是形式审查的核心组件，负责执行预定义的检查规则。采用插件化设计，便于扩展新的检查规则。

## 设计原则

1. **单一职责**: 每个规则只负责一个检查项
2. **可插拔**: 规则可以动态注册和组合
3. **可配置**: 规则参数可配置
4. **可测试**: 规则逻辑独立，易于单元测试

## 核心架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 6: Service/Agent 层 (services/review/)                       │
│  ┌─────────────────┐  ┌─────────────────┐                          │
│  │  ReviewService  │  │  ReviewAgent    │  ← 流程编排               │
│  └────────┬────────┘  └────────┬────────┘                          │
└───────────┼───────────────────┼────────────────────────────────────┘
            │                   │
┌───────────▼───────────────────▼────────────────────────────────────┐
│  Layer 5: 规则引擎层 (services/review/rules/)                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   │
│  │  RuleRegistry   │  │  RuleEngine     │  │  BaseRule      │   │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘   │
│           │                     │                     │             │
│  ┌────────▼────────────────────▼─────────────────────▼─────────┐   │
│  │                    Rules (规则实现)                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │   │
│  │  │SignatureCheck│  │ StampCheck   │  │WorkUnitCheck │     │   │
│  │  │   (签字检查)  │  │   (盖章检查)  │  │  (一致性检查)  │     │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │   │
│  └───────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
            │ 调用 Extractor
┌───────────▼─────────────────────────────────────────────────────────┐
│  Layer 4: 提取器层 (common/extractors/)  ← 通用提取能力抽象层      │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │ SignatureExtract │  │  StampExtractor  │  │ FieldExtractor  │ │
│  │    (提取签字)    │  │  (提取印章+内容)  │  │  (提取字段值)   │ │
│  │  无签字→返回null │  │  无印章→返回null  │  │  无字段→返回null│ │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
            │ 使用底层能力
┌───────────▼─────────────────────────────────────────────────────────┐
│  Layer 3: 底层能力层 (common/vision/)                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │   YOLODetector   │  │  MultimodalLLM   │  │      OCR        │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## 设计理念：统一为 Extractor

**核心思路**：所有能力都是 **Extractor（提取器）**
- 能提取到 → 返回内容
- 提取不到 → 返回 null（相当于 detect 不到）

这样：
- "有无检查" = 调用 Extractor，返回 null 则失败
- "一致性检查" = 调用 Extractor，获取值后比对

## 各层职责定义

| 层级 | 组件 | 职责 |
|------|------|------|
| **Layer 3** | `YOLODetector`, `MultimodalLLM`, `OCR` | 纯底层能力，提供基础检测/识别功能 |
| **Layer 4** | `SignatureExtractor`, `StampExtractor`, `FieldExtractor` | 统一提取器，能提取到则返回内容，提取不到返回 null |
| **Layer 5** | `*Rule` (规则) | 调用 Extractor，根据返回内容判断 PASS/FAILED |
| **Layer 6** | `ReviewAgent`, `ReviewService` | 流程编排，不直接调用底层能力 |

## 为什么要分层

### 问题：当前架构的职责混乱

```
旧架构调用链:
ReviewAgent.process()
    │
    ├─> DocumentExtractor.extract()  ← 职责过重！
    │       ├─> OCR 提取文字
    │       ├─> _detect_stamps_with_llm()   # 业务层做检测
    │       └─> _detect_signatures_with_llm() # 业务层做检测
    │
    └─> _run_rules()
            ├─> SignatureCheckRule.check()  # 规则又调用检测器
            └─> StampCheckRule.check()      # 重复调用
```

**问题点：**
1. **重复调用**：签字/盖章检测在 Extractor 做了一次，Rule 里又做了一次
2. **层次不清**：检测能力应该在底层，不应该在业务层
3. **耦合严重**：规则与检测器直接绑定，难以复用

### 解决：清晰分层

```
新架构调用链:
ReviewAgent.process()
    │
    └─> _run_rules()
            │
            ├─> SignatureCheckRule.check()
            │       └─> SignatureExtractor.extract()  # 只做提取
            │
            └─> StampCheckRule.check()
                    └─> StampExtractor.extract()       # 只做提取
```

**优点：**
1. **职责清晰**：检测是检测，规则是规则
2. **复用性好**：新规则可以复用已有检测器
3. **方便扩展**：新增检查项只需写新的 Checker

## 规则基类

```python
# src/services/review/rules/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum

class CheckStatus(str, Enum):
    """检查状态"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"

class CheckResult(BaseModel):
    """检查结果"""
    item: str
    status: CheckStatus
    message: str
    evidence: Dict[str, Any] = {}
    confidence: float = 1.0

class ReviewContext(BaseModel):
    """审查上下文"""
    file_data: bytes
    file_type: str
    document_type: str
    content: "DocumentContent" = None  # 解析后的内容
    metadata: Dict[str, Any] = {}
    
    class Config:
        arbitrary_types_allowed = True

class BaseRule(ABC):
    """规则基类"""
    
    name: str = "base_rule"
    description: str = "基础规则"
    priority: int = 0  # 执行优先级，数字越大越先执行
    
    @abstractmethod
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行检查
        
        Args:
            context: 审查上下文
            
        Returns:
            CheckResult: 检查结果
        """
        pass
    
    async def should_run(self, context: ReviewContext) -> bool:
        """判断是否需要执行此规则
        
        Args:
            context: 审查上下文
            
        Returns:
            bool: 是否执行
        """
        return True
    
    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        return {}
```

## 规则注册表

```python
# src/services/review/rules/registry.py
from typing import Dict, List, Type
from src.services.review.rules.base import BaseRule, CheckResult, ReviewContext

class RuleRegistry:
    """规则注册表"""
    
    _rules: Dict[str, Type[BaseRule]] = {}
    
    @classmethod
    def register(cls, rule_class: Type[BaseRule]):
        """注册规则"""
        instance = rule_class()
        cls._rules[instance.name] = rule_class
        return rule_class
    
    @classmethod
    def get_rule(cls, name: str) -> Type[BaseRule]:
        """获取规则类"""
        return cls._rules.get(name)
    
    @classmethod
    def get_all_rules(cls) -> List[Type[BaseRule]]:
        """获取所有规则"""
        return list(cls._rules.values())
    
    @classmethod
    def create_chain(cls, document_type: str = None) -> List[BaseRule]:
        """创建规则链"""
        rules = []
        for rule_class in cls._rules.values():
            instance = rule_class()
            rules.append(instance)
        
        # 按优先级排序
        rules.sort(key=lambda r: r.priority, reverse=True)
        return rules
```

## 具体检查器实现

### 签字检查

```python
# src/services/review/rules/checkers/signature.py
from src.services.review.rules.base import BaseRule, CheckResult, CheckStatus, ReviewContext
from src.services.review.rules.registry import RuleRegistry

@RuleRegistry.register
class SignatureCheckRule(BaseRule):
    """签字检查规则"""
    
    name = "signature"
    description = "检查文档中是否存在签字"
    priority = 10
    
    def __init__(self):
        self.min_regions = 1  # 最少签字区域数
        self.min_confidence = 0.7  # 最低置信度
    
    async def should_run(self, context: ReviewContext) -> bool:
        """根据文档类型判断"""
        # 某些文档类型不需要签字检查
        no_signature_types = ["检索报告"]
        return context.document_type not in no_signature_types
    
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行签字检查"""
        from src.common.extractors import SignatureExtractor
        
        # 提取签字区域
        extractor = SignatureExtractor()
        result = await extractor.extract(context.file_data)
        
        if result:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"提取到签字内容",
                evidence={"content": result}
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未提取到签字",
                evidence={}
            )
```

### 盖章检查

```python
# src/services/review/rules/checkers/stamp.py
from src.services.review.rules.base import BaseRule, CheckResult, CheckStatus, ReviewContext
from src.services.review.rules.registry import RuleRegistry

@RuleRegistry.register
class StampCheckRule(BaseRule):
    """盖章检查规则"""
    
    name = "stamp"
    description = "检查文档中是否存在印章"
    priority = 10
    
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行盖章检查"""
        from src.common.extractors import StampExtractor
        
        extractor = StampExtractor()
        result = await extractor.extract(context.file_data)
        
        if result:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"提取到印章内容",
                evidence={"content": result}
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未提取到印章",
                evidence={}
            )
```

### 前置条件检查

```python
# src/services/review/rules/checkers/prerequisite.py
from src.services.review.rules.base import BaseRule, CheckResult, CheckStatus, ReviewContext
from src.services.review.rules.registry import RuleRegistry
from src.common.models.enums import DocumentType

@RuleRegistry.register
class PrerequisiteCheckRule(BaseRule):
    """前置条件检查规则"""
    
    name = "prerequisite"
    description = "检查前置条件文档是否上传"
    priority = 20
    
    # 文档类型 -> 前置条件映射
    PREREQUISITES = {
        DocumentType.PATENT_CERTIFICATE: [],
        DocumentType.ACCEPTANCE_REPORT: [
            DocumentType.LICENSE,
            DocumentType.RETRIEVAL_REPORT
        ],
    }
    
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行前置条件检查"""
        required = self.PREREQUISITES.get(
            context.document_type, 
            []
        )
        
        if not required:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message="无前置条件要求"
            )
        
        # 检查已上传的文档
        uploaded_types = context.metadata.get("uploaded_types", [])
        
        missing = [t for t in required if t not in uploaded_types]
        
        if missing:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message=f"缺少前置条件文档: {', '.join(missing)}",
                evidence={"missing_types": missing}
            )
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED,
            message="前置条件满足"
        )
```

### 一致性检查

```python
# src/services/review/rules/checkers/consistency.py
from src.services.review.rules.base import BaseRule, CheckResult, CheckStatus, ReviewContext
from src.services.review.rules.registry import RuleRegistry
from src.common.llm import get_llm_client

@RuleRegistry.register
class ConsistencyCheckRule(BaseRule):
    """一致性检查规则"""
    
    name = "consistency"
    description = "检查填写信息与证书一致性"
    priority = 5
    
    async def check(self, context: ReviewContext) -> CheckResult:
        """执行一致性检查"""
        # 获取表单数据
        form_data = context.metadata.get("form_data", {})
        if not form_data:
            return CheckResult(
                item=self.name,
                status=CheckStatus.SKIPPED,
                message="无表单数据，跳过一致性检查"
            )
        
        # 使用 LLM 验证一致性
        llm = get_llm_client()
        
        prompt = f"""请比较以下信息是否一致：
        
表单信息：
- 专利权人: {form_data.get('patentee')}
- 发明人: {form_data.get('inventor')}

请从文档中提取相关信息并进行比对，返回结果。"""
        
        result = await llm.generate(prompt)
        
        # 解析 LLM 返回
        is_consistent = "一致" in result
        
        return CheckResult(
            item=self.name,
            status=CheckStatus.PASSED if is_consistent else CheckStatus.FAILED,
            message="一致性检查完成" if is_consistent else "发现不一致",
            evidence={"llm_analysis": result}
        )
```

## 使用方式

```python
# 创建规则链
from src.services.review.rules.registry import RuleRegistry

rules = RuleRegistry.create_chain(document_type="patent_certificate")

# 执行检查
context = ReviewContext(
    file_data=file_data,
    file_type="pdf",
    document_type="patent_certificate"
)

results = []
for rule in rules:
    if await rule.should_run(context):
        result = await rule.check(context)
        results.append(result)
```

## 扩展规则

1. 在 `checkers/` 下创建新文件
2. 继承 `BaseRule`
3. 实现 `check` 方法
4. 使用 `@RuleRegistry.register` 注册
