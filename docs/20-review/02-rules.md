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
┌─────────────────────────────────────────────────────────────┐
│                      ReviewAgent                            │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                  RuleRegistry                         │ │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │ │
│  │  │签名检查 │ │盖章检查 │ │前置条件 │ │一致性  │ ...  │ │
│  │  └────────┘ └────────┘ └────────┘ └────────┘      │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

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
        from src.common.vision import SignatureDetector
        
        # 检测签名区域
        detector = SignatureDetector()
        regions = await detector.detect(
            context.file_data,
            confidence=self.min_confidence
        )
        
        if len(regions) >= self.min_regions:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"检测到 {len(regions)} 个签字区域",
                evidence={
                    "region_count": len(regions),
                    "regions": [
                        {"bbox": r.bbox.model_dump(), "confidence": r.confidence}
                        for r in regions
                    ]
                }
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未检测到签字",
                evidence={"region_count": 0}
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
        from src.common.vision import StampDetector
        
        detector = StampDetector()
        regions = await detector.detect(context.file_data, confidence=0.7)
        
        if regions:
            return CheckResult(
                item=self.name,
                status=CheckStatus.PASSED,
                message=f"检测到 {len(regions)} 个印章",
                evidence={"region_count": len(regions)}
            )
        else:
            return CheckResult(
                item=self.name,
                status=CheckStatus.FAILED,
                message="未检测到印章",
                evidence={"region_count": 0}
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
