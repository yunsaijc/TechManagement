# 🤖 Agent 设计

## 概述

ReviewAgent 是形式审查的核心智能组件，协调规则引擎和多模态 LLM，实现文档的智能审查。

## 设计思路

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ReviewAgent (Layer 6)                        │
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐        │
│  │  文档分类器   │ -> │  内容提取器   │ -> │  规则执行器   │        │
│  │(LLM多模态)    │    │(OCR+文字解析) │    │(规则引擎)    │        │
│  └──────────────┘    └──────────────┘    └──────┬───────┘        │
│         │                   │                    │                 │
│         │                   │         ┌──────────▼──────────┐      │
│         │                   │         │   Checkers (Layer 5)│      │
│         │                   │         │  ┌────────┐ ┌─────┐ │      │
│         │                   │         │  │Signature│ │Stamp│ │      │
│         │                   │         │  │Checker │ │Check│ │      │
│         │                   │         │  └───┬────┘ └──┬──┘ │      │
│         │                   │         └──────│──────────│───┘      │
│         │                   │                │          │          │
│         │                   │      ┌─────────▼──────────▼────┐    │
│         │                   │      │ Extractors (Layer 4)    │    │
│         │                   │      │Signature/Stamp/FieldExtractor │    │
│         │                   │      └─────────┬───────────────┘    │
│         │                   │                │                     │
│         │                   │      ┌─────────▼───────────────┐    │
│         │                   │      │ Vision (Layer 3)       │    │
│         │                   │      │YOLODetector/ Multimodal │    │
│         │                   │      └─────────────────────────┘    │
│         │                   │                                       │
│         └───────────────────┼──────────────────────────────────────┘
│                             │
│                    ┌────────▼────────┐
│                    │   结果聚合器     │
│                    │  (总结+建议)    │
│                    └─────────────────┘
└─────────────────────────────────────────────────────────────────────┘
```

## Agent 职责

| 组件 | 职责 |
|------|------|
| 文档分类器 | 使用 LLM 识别文档类型 |
| 内容提取器 | OCR 提取文字 + 结构化解析 |
| 规则执行器 | 加载并执行检查规则 |
| 结果聚合器 | 汇总结果，生成总结和建议 |

## 注意事项

- **Agent 不直接调用 Extractor**：Agent 只负责流程编排
- **提取逻辑下沉**：签字/盖章/字段提取由 Checker 调用 Extractor 完成
- **LLM 补充**：复杂场景由 Agent 调用 LLM 做补充分析

## Agent 核心实现

```python
# src/services/review/agent.py
from typing import List, Dict, Any, Optional
from langchain_core.runnables import Runnable, RunnableSequence
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.common.llm import BaseLLM
from src.common.models import ReviewResult, CheckResult, CheckStatus
from src.services.review.rules.base import ReviewContext
from src.services.review.rules.registry import RuleRegistry

class ReviewAgent:
    """形式审查 Agent"""
    
    def __init__(
        self,
        llm: BaseLLM,
        document_parser: "DocumentParser",
        rule_registry: type[RuleRegistry] = RuleRegistry
    ):
        self.llm = llm
        self.parser = document_parser
        self.rule_registry = rule_registry
    
    async def process(
        self,
        file_data: bytes,
        file_type: str,
        document_type: str = None,
        check_items: List[str] = None,
        **kwargs
    ) -> ReviewResult:
        """执行审查
        
        Args:
            file_data: 文件数据
            file_type: 文件类型
            document_type: 文档类型（可选，自动识别）
            check_items: 检查项列表（可选）
            
        Returns:
            ReviewResult: 审查结果
        """
        import time
        start_time = time.time()
        
        # 1. 文档分类
        if not document_type:
            document_type = await self._classify_document(file_data)
        
        # 2. 内容提取
        context = await self._extract_content(
            file_data, file_type, document_type
        )
        
        # 3. 规则检查
        rule_results = await self._run_rules(context, check_items)
        
        # 4. LLM 补充
        llm_results = await self._llm_check(context, check_items)
        
        # 5. 结果聚合
        all_results = rule_results + llm_results
        summary = self._generate_summary(all_results)
        suggestions = self._generate_suggestions(all_results)
        
        return ReviewResult(
            id=f"review_{int(time.time() * 1000)}",
            document_type=document_type,
            results=all_results,
            summary=summary,
            suggestions=suggestions,
            processing_time=time.time() - start_time
        )
    
    async def _classify_document(self, file_data: bytes) -> str:
        """文档分类"""
        from src.common.vision import MultimodalLLM
        
        multi_llm = MultimodalLLM(self.llm)
        
        prompt = """请识别这个文档的类型：
- 专利证书
- 专利申请
- 验收报告
- 行政许可
- 检索报告
- 奖励证书
- 合同
- 其他

直接返回文档类型，不要其他内容。"""
        
        result = await multi_llm.analyze_image(file_data, prompt)
        
        # 简单解析
        type_mapping = {
            "专利证书": "patent_certificate",
            "专利申请": "patent_application",
            "验收报告": "acceptance_report",
            "行政许可": "license",
            "检索报告": "retrieval_report",
            "奖励证书": "award_certificate",
            "合同": "contract",
        }
        
        for key, value in type_mapping.items():
            if key in result:
                return value
        
        return "other"
    
    async def _extract_content(
        self,
        file_data: bytes,
        file_type: str,
        document_type: str
    ) -> ReviewContext:
        """提取内容"""
        # 解析文档
        parse_result = await self.parser.parse(file_data, file_type)
        
        # 目标检测
        from src.common.vision import SignatureDetector, StampDetector
        
        sig_detector = SignatureDetector()
        stamp_detector = StampDetector()
        
        signatures = await sig_detector.detect(file_data)
        stamps = await stamp_detector.detect(file_data)
        
        # 构建上下文
        context = ReviewContext(
            file_data=file_data,
            file_type=file_type,
            document_type=document_type,
            content=parse_result.content,
            metadata={
                "signatures": signatures,
                "stamps": stamps
            }
        )
        
        return context
    
    async def _run_rules(
        self,
        context: ReviewContext,
        check_items: List[str] = None
    ) -> List[CheckResult]:
        """运行规则"""
        rules = self.rule_registry.create_chain(context.document_type)
        
        # 过滤检查项
        if check_items:
            rules = [r for r in rules if r.name in check_items]
        
        results = []
        for rule in rules:
            if await rule.should_run(context):
                result = await rule.check(context)
                results.append(result)
        
        return results
    
    async def _llm_check(
        self,
        context: ReviewContext,
        check_items: List[str] = None
    ) -> List[CheckResult]:
        """LLM 补充检查"""
        from src.common.vision import MultimodalLLM
        
        multi_llm = MultimodalLLM(self.llm)
        
        # 需要 LLM 检查的项目
        llm_items = ["consistency", "completeness"]
        if check_items:
            llm_items = [i for i in llm_items if i in check_items]
        
        results = []
        
        if "consistency" in llm_items:
            result = await self._check_consistency(context, multi_llm)
            if result:
                results.append(result)
        
        return results
    
    async def _check_consistency(
        self,
        context: ReviewContext,
        multi_llm: "MultimodalLLM"
    ) -> Optional[CheckResult]:
        """一致性检查"""
        form_data = context.metadata.get("form_data", {})
        if not form_data:
            return None
        
        prompt = f"""请检查文档中的信息与以下表单数据是否一致：
        
表单数据：
{form_data}

请分析并给出结果。"""
        
        result = await multi_llm.analyze_image(context.file_data, prompt)
        
        return CheckResult(
            item="consistency",
            status=CheckStatus.PASSED if "一致" in result else CheckStatus.FAILED,
            message="一致性检查完成",
            evidence={"llm_analysis": result}
        )
    
    def _generate_summary(self, results: List[CheckResult]) -> str:
        """生成总结"""
        passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
        failed = sum(1 for r in results if r.status == CheckStatus.FAILED)
        
        return f"审查完成：通过 {passed} 项，失败 {failed} 项"
    
    def _generate_suggestions(self, results: List[CheckResult]) -> List[str]:
        """生成建议"""
        suggestions = []
        
        for result in results:
            if result.status == CheckStatus.FAILED:
                suggestions.append(f"请检查：{result.item} - {result.message}")
        
        return suggestions
```

## 与 LangChain 集成

```python
# 使用 LCEL 构建链
from langchain_core.runnables import RunnableSequence
from langchain_core.prompts import ChatPromptTemplate

class ReviewChain:
    """审查链 - LCEL 实现"""
    
    def __init__(self, llm, parser):
        self.llm = llm
        self.parser = parser
        
        # 构建 LCEL 链
        self.chain = RunnableSequence([
            self._classify,
            self._extract,
            self._check,
            self._aggregate
        ])
    
    async def _classify(self, input: Dict) -> Dict:
        """分类"""
        # ...
        return input
    
    async def _extract(self, input: Dict) -> Dict:
        """提取"""
        # ...
        return input
    
    async def _check(self, input: Dict) -> Dict:
        """检查"""
        # ...
        return input
    
    async def _aggregate(self, input: Dict) -> ReviewResult:
        """聚合"""
        # ...
        return ReviewResult(...)
    
    def invoke(self, input: Dict) -> ReviewResult:
        """调用链"""
        return self.chain.invoke(input)
```

## 扩展 Agent

### 新增检查逻辑

```python
class CustomReviewAgent(ReviewAgent):
    """自定义审查 Agent"""
    
    async def _llm_check(self, context, check_items) -> List[CheckResult]:
        # 添加自定义 LLM 检查
        results = await super()._llm_check(context, check_items)
        
        # 新增检查
        if "custom_check" in (check_items or []):
            result = await self._custom_check(context)
            results.append(result)
        
        return results
```

### 新增 Agent

```python
# 新建服务目录
src/services/project/
├── agent.py       # 项目评审 Agent
├── rules/         # 项目评审规则
└── service.py     # 服务入口
```
