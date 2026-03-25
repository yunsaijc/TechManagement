# 🔧 检查器设计

## 概述

检查器（Checker）是正文评审服务的核心组件，每个检查器负责一个特定维度的评审检查。检查器采用**规则 + LLM 混合检查**模式，确保检查结果的准确性和可解释性。

## 检查器架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         检查器架构                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      BaseChecker (抽象基类)                    │  │
│  │                                                              │  │
│  │  属性:                                                       │  │
│  │  - dimension: str          # 维度代码                        │  │
│  │  - dimension_name: str     # 维度名称                        │  │
│  │  - default_weight: float   # 默认权重                        │  │
│  │                                                              │  │
│  │  方法:                                                       │  │
│  │  + check() -> CheckResult   # 执行检查 (抽象方法)            │  │
│  │  + get_prompt() -> str      # 生成 LLM Prompt                │  │
│  │  + _parse_response()        # 解析 LLM 响应                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│         ┌────────────────────┼────────────────────┐                │
│         │                    │                    │                │
│         ▼                    ▼                    ▼                │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │
│  │ Feasibility │     │ Innovation  │     │    Team     │   ...    │
│  │  Checker    │     │   Checker   │     │   Checker   │          │
│  └─────────────┘     └─────────────┘     └─────────────┘          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 检查器列表

| 检查器 | 类名 | 维度代码 | 源文件 |
|--------|------|----------|--------|
| 技术可行性检查器 | `FeasibilityChecker` | `feasibility` | `feasibility.py` |
| 创新性检查器 | `InnovationChecker` | `innovation` | `innovation.py` |
| 团队能力检查器 | `TeamChecker` | `team` | `team.py` |
| 预期成果检查器 | `OutcomeChecker` | `outcome` | `outcome.py` |
| 社会效益检查器 | `SocialBenefitChecker` | `social_benefit` | `social_benefit.py` |
| 经济效益检查器 | `EconomicBenefitChecker` | `economic_benefit` | `economic_benefit.py` |
| 风险控制检查器 | `RiskControlChecker` | `risk_control` | `risk_control.py` |
| 进度合理性检查器 | `ScheduleChecker` | `schedule` | `schedule.py` |
| 合规性检查器 | `ComplianceChecker` | `compliance` | `compliance.py` |

---

## 基类设计

### 数据模型

```python
# src/services/evaluation/checkers/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CheckItem(BaseModel):
    """检查项结果"""
    name: str = Field(..., description="检查项名称")
    score: float = Field(..., ge=1, le=10, description="得分 (1-10)")
    comment: str = Field(..., description="评价说明")


class CheckResult(BaseModel):
    """检查结果"""
    dimension: str = Field(..., description="维度代码")
    score: float = Field(..., ge=1, le=10, description="总得分 (1-10)")
    confidence: float = Field(..., ge=0, le=1, description="置信度 (0-1)")
    opinion: str = Field(..., description="评审意见")
    issues: List[str] = Field(default_factory=list, description="问题列表")
    highlights: List[str] = Field(default_factory=list, description="亮点列表")
    details: Dict[str, Any] = Field(default_factory=dict, description="详细信息")


class BaseChecker(ABC):
    """检查器基类"""
    
    # 子类必须定义
    dimension: str = ""                    # 维度代码
    dimension_name: str = ""               # 维度名称
    default_weight: float = 0.1            # 默认权重
    
    # 检查项配置（子类可覆盖）
    CHECK_ITEMS: List[Dict[str, Any]] = []
    
    def __init__(self, llm: Any = None):
        """
        初始化检查器
        
        Args:
            llm: LLM 客户端实例
        """
        self.llm = llm
    
    @abstractmethod
    async def check(
        self,
        project_info: Dict[str, Any],      # 项目基本信息
        sections: Dict[str, str],           # 章节内容 {section_id: content}
        **kwargs
    ) -> CheckResult:
        """
        执行检查
        
        Args:
            project_info: 项目基本信息字典
            sections: 章节内容字典
            **kwargs: 其他参数
        
        Returns:
            CheckResult: 检查结果
        """
        pass
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成 LLM Prompt
        
        Args:
            context: 上下文信息
        
        Returns:
            str: Prompt 字符串
        """
        raise NotImplementedError("子类必须实现此方法")
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 响应
        
        Args:
            response: LLM 响应字符串
        
        Returns:
            Dict: 解析后的结果
        """
        import json
        import re
        
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        # 返回默认结构
        return {
            "score": 5.0,
            "opinion": response,
            "issues": [],
            "highlights": [],
            "confidence": 0.5
        }
    
    def _extract_section_content(
        self,
        sections: Dict[str, str],
        section_ids: List[str],
        max_length: int = 2000
    ) -> str:
        """
        提取章节内容
        
        Args:
            sections: 章节内容字典
            section_ids: 章节ID列表
            max_length: 最大长度
        
        Returns:
            str: 合并后的内容
        """
        contents = []
        for sid in section_ids:
            content = sections.get(sid, "")
            if content:
                contents.append(content)
        
        merged = "\n\n".join(contents)
        if len(merged) > max_length:
            merged = merged[:max_length] + "..."
        
        return merged
```

---

## 检查器实现

### 1. 技术可行性检查器

```python
# src/services/evaluation/checkers/feasibility.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class FeasibilityChecker(BaseChecker):
    """技术可行性检查器"""
    
    dimension = "feasibility"
    dimension_name = "技术可行性"
    default_weight = 0.15
    
    # 检查项配置
    CHECK_ITEMS = [
        {"name": "技术路线清晰度", "weight": 0.30, "description": "技术路线图是否清晰、步骤是否明确"},
        {"name": "技术成熟度", "weight": 0.30, "description": "核心技术是否成熟、是否有验证"},
        {"name": "实施条件完备性", "weight": 0.20, "description": "设备、人员、资金是否到位"},
        {"name": "技术风险控制", "weight": 0.20, "description": "是否识别技术风险、有应对方案"},
    ]
    
    # 依赖的章节
    REQUIRED_SECTIONS = ["tech_solution", "implementation"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行技术可行性检查"""
        
        # 1. 提取相关章节
        tech_content = self._extract_section_content(
            sections, 
            ["tech_solution", "implementation"],
            max_length=3000
        )
        
        # 2. 构造上下文
        context = {
            "project_name": project_info.get("xmmc", ""),
            "keywords": project_info.get("gjc", ""),
            "tech_content": tech_content,
        }
        
        # 3. 生成 Prompt
        prompt = self.get_prompt(context)
        
        # 4. 调用 LLM
        response = await self.llm.ainvoke(prompt)
        
        # 5. 解析结果
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        # 6. 构建返回结果
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={
                "items": result.get("items", []),
                "check_items": self.CHECK_ITEMS,
            }
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        """生成 LLM Prompt"""
        return f"""你是一个科技项目评审专家。请评估以下项目的技术可行性。

## 项目信息

**项目名称**：{context['project_name']}
**关键词**：{context['keywords']}

## 技术方案内容

{context['tech_content']}

## 评审要求

请从以下 4 个方面进行评分（每项 1-10 分）：

1. **技术路线清晰度**（权重30%）：技术路线图是否清晰、步骤是否明确、逻辑是否连贯
2. **技术成熟度**（权重30%）：核心技术是否成熟、是否有前期验证、技术来源是否可靠
3. **实施条件完备性**（权重20%）：设备条件、人员配置、资金保障是否到位
4. **技术风险控制**（权重20%）：是否识别技术风险、应对措施是否具体可行

## 输出格式

请严格按照以下 JSON 格式输出，不要添加任何额外文字：

```json
{{
  "score": <总评分1-10，加权平均>,
  "items": [
    {{"name": "技术路线清晰度", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "技术成熟度", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "实施条件完备性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "技术风险控制", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见，100-200字，总结技术可行性的整体评价>",
  "issues": ["<发现的问题1>", "<发现的问题2>", "..."],
  "highlights": ["<亮点1>", "<亮点2>", "..."],
  "confidence": <置信度0-1，表示对评审结果的把握程度>
}}
```"""
```

### 2. 创新性检查器

```python
# src/services/evaluation/checkers/innovation.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class InnovationChecker(BaseChecker):
    """创新性检查器"""
    
    dimension = "innovation"
    dimension_name = "创新性"
    default_weight = 0.15
    
    CHECK_ITEMS = [
        {"name": "创新点数量与质量", "weight": 0.40, "description": "是否有实质性创新、创新程度"},
        {"name": "技术水平先进性", "weight": 0.30, "description": "国内/国际领先/先进水平"},
        {"name": "创新可行性", "weight": 0.30, "description": "创新点是否有支撑、是否可实现"},
    ]
    
    REQUIRED_SECTIONS = ["innovation_points", "tech_solution"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行创新性检查"""
        
        # 提取创新点和技术方案章节
        innovation_content = self._extract_section_content(
            sections,
            ["innovation_points", "tech_solution"],
            max_length=2500
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "keywords": project_info.get("gjc", ""),
            "innovation_content": innovation_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的创新性。

## 项目信息

**项目名称**：{context['project_name']}
**关键词**：{context['keywords']}

## 创新点与技术方案

{context['innovation_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **创新点数量与质量**（权重40%）：是否有实质性创新、创新点的科学价值和技术含量
2. **技术水平先进性**（权重30%）：与国内外同类技术比较，处于何种水平
3. **创新可行性**（权重30%）：创新点是否有理论/技术支撑、是否具备实现条件

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "创新点数量与质量", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "技术水平先进性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "创新可行性", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>", "<问题2>"],
  "highlights": ["<创新亮点1>", "<创新亮点2>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 3. 团队能力检查器

```python
# src/services/evaluation/checkers/team.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class TeamChecker(BaseChecker):
    """团队能力检查器"""
    
    dimension = "team"
    dimension_name = "团队能力"
    default_weight = 0.10
    
    CHECK_ITEMS = [
        {"name": "负责人资质", "weight": 0.40, "description": "学术背景、职称、相关项目经验"},
        {"name": "团队结构", "weight": 0.30, "description": "人员配置是否合理、专业覆盖"},
        {"name": "研究基础", "weight": 0.30, "description": "前期成果、相关经验、研究条件"},
    ]
    
    REQUIRED_SECTIONS = ["team_intro", "leader_resume"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行团队能力检查"""
        
        # 提取团队介绍章节
        team_content = self._extract_section_content(
            sections,
            ["team_intro", "leader_resume", "research_basis"],
            max_length=2000
        )
        
        # 从项目信息中提取负责人信息
        leader_name = project_info.get("xmFzr", "")
        organization = project_info.get("cddw_mc", "")
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "leader_name": leader_name,
            "organization": organization,
            "team_content": team_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目团队的能力。

## 项目信息

**项目名称**：{context['project_name']}
**负责人**：{context['leader_name']}
**承担单位**：{context['organization']}

## 团队介绍

{context['team_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **负责人资质**（权重40%）：学术背景、职称、相关项目经验、学术影响力
2. **团队结构**（权重30%）：人员配置是否合理、专业覆盖是否全面、梯队建设
3. **研究基础**（权重30%）：前期成果、相关经验、研究条件

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "负责人资质", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "团队结构", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "研究基础", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 4. 预期成果检查器

```python
# src/services/evaluation/checkers/outcome.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class OutcomeChecker(BaseChecker):
    """预期成果检查器"""
    
    dimension = "outcome"
    dimension_name = "预期成果"
    default_weight = 0.12
    
    CHECK_ITEMS = [
        {"name": "成果形式明确性", "weight": 0.30, "description": "论文、专利、产品等是否明确"},
        {"name": "指标量化程度", "weight": 0.40, "description": "指标是否可量化、可考核"},
        {"name": "成果转化潜力", "weight": 0.30, "description": "是否有转化路径、应用前景"},
    ]
    
    REQUIRED_SECTIONS = ["expected_outcome", "assessment_indicators"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行预期成果检查"""
        
        outcome_content = self._extract_section_content(
            sections,
            ["expected_outcome", "assessment_indicators"],
            max_length=2000
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "outcome_content": outcome_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的预期成果。

## 项目信息

**项目名称**：{context['project_name']}

## 预期成果与考核指标

{context['outcome_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **成果形式明确性**（权重30%）：论文、专利、产品、标准等成果形式是否明确具体
2. **指标量化程度**（权重40%）：考核指标是否可量化、可考核、可验证
3. **成果转化潜力**（权重30%）：是否有转化路径、产业化前景如何

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "成果形式明确性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "指标量化程度", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "成果转化潜力", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 5. 社会效益检查器

```python
# src/services/evaluation/checkers/social_benefit.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class SocialBenefitChecker(BaseChecker):
    """社会效益检查器"""
    
    dimension = "social_benefit"
    dimension_name = "社会效益"
    default_weight = 0.10
    
    CHECK_ITEMS = [
        {"name": "社会影响范围", "weight": 0.35, "description": "受益人群、影响区域范围"},
        {"name": "推广应用价值", "weight": 0.35, "description": "是否可复制推广、推广前景"},
        {"name": "公益性贡献", "weight": 0.30, "description": "对社会的公益性贡献"},
    ]
    
    REQUIRED_SECTIONS = ["social_benefit", "benefit_analysis"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行社会效益检查"""
        
        benefit_content = self._extract_section_content(
            sections,
            ["social_benefit", "benefit_analysis"],
            max_length=2000
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "benefit_content": benefit_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的社会效益。

## 项目信息

**项目名称**：{context['project_name']}

## 社会效益分析

{context['benefit_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **社会影响范围**（权重35%）：受益人群数量、影响区域范围、社会关注度
2. **推广应用价值**（权重35%）：是否可复制推广、推广前景、示范效应
3. **公益性贡献**（权重30%）：对社会的公益性贡献、社会价值

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "社会影响范围", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "推广应用价值", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "公益性贡献", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 6. 经济效益检查器

```python
# src/services/evaluation/checkers/economic_benefit.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class EconomicBenefitChecker(BaseChecker):
    """经济效益检查器"""
    
    dimension = "economic_benefit"
    dimension_name = "经济效益"
    default_weight = 0.10
    
    CHECK_ITEMS = [
        {"name": "经济回报预期", "weight": 0.35, "description": "投入产出比是否合理"},
        {"name": "市场前景", "weight": 0.35, "description": "市场需求、竞争态势"},
        {"name": "产业化潜力", "weight": 0.30, "description": "是否具备产业化条件"},
    ]
    
    REQUIRED_SECTIONS = ["economic_benefit", "benefit_analysis", "budget"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行经济效益检查"""
        
        benefit_content = self._extract_section_content(
            sections,
            ["economic_benefit", "benefit_analysis", "budget"],
            max_length=2500
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "benefit_content": benefit_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的经济效益。

## 项目信息

**项目名称**：{context['project_name']}

## 经济效益分析

{context['benefit_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **经济回报预期**（权重35%）：投入产出比是否合理、经济效益是否可观
2. **市场前景**（权重35%）：市场需求、竞争态势、市场空间
3. **产业化潜力**（权重30%）：是否具备产业化条件、产业化路径是否清晰

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "经济回报预期", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "市场前景", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "产业化潜力", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 7. 风险控制检查器

```python
# src/services/evaluation/checkers/risk_control.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class RiskControlChecker(BaseChecker):
    """风险控制检查器"""
    
    dimension = "risk_control"
    dimension_name = "风险控制"
    default_weight = 0.08
    
    CHECK_ITEMS = [
        {"name": "风险识别完整性", "weight": 0.35, "description": "是否全面识别各类风险"},
        {"name": "应对措施有效性", "weight": 0.40, "description": "措施是否具体可行"},
        {"name": "预案可行性", "weight": 0.25, "description": "是否有备选方案"},
    ]
    
    REQUIRED_SECTIONS = ["risk_analysis", "risk_control"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行风险控制检查"""
        
        risk_content = self._extract_section_content(
            sections,
            ["risk_analysis", "risk_control"],
            max_length=2000
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "risk_content": risk_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的风险控制。

## 项目信息

**项目名称**：{context['project_name']}

## 风险分析与控制

{context['risk_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **风险识别完整性**（权重35%）：是否全面识别技术、管理、市场、政策等风险
2. **应对措施有效性**（权重40%：措施是否具体、可行、有针对性
3. **预案可行性**（权重25%）：是否有备选方案、应急预案

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "风险识别完整性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "应对措施有效性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "预案可行性", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 8. 进度合理性检查器

```python
# src/services/evaluation/checkers/schedule.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class ScheduleChecker(BaseChecker):
    """进度合理性检查器"""
    
    dimension = "schedule"
    dimension_name = "进度合理性"
    default_weight = 0.10
    
    CHECK_ITEMS = [
        {"name": "时间安排合理性", "weight": 0.35, "description": "各阶段时间是否合理"},
        {"name": "里程碑清晰度", "weight": 0.35, "description": "是否有明确的里程碑"},
        {"name": "进度可控性", "weight": 0.30, "description": "是否有进度监控机制"},
    ]
    
    REQUIRED_SECTIONS = ["schedule", "implementation_plan"]
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行进度合理性检查"""
        
        schedule_content = self._extract_section_content(
            sections,
            ["schedule", "implementation_plan"],
            max_length=2000
        )
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "schedule_content": schedule_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目的进度安排合理性。

## 项目信息

**项目名称**：{context['project_name']}

## 进度安排

{context['schedule_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **时间安排合理性**（权重35%）：各阶段时间是否合理、是否留有余地
2. **里程碑清晰度**（权重35%）：是否有明确的里程碑和阶段性成果
3. **进度可控性**（权重30%）：是否有进度监控机制、调整机制

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "时间安排合理性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "里程碑清晰度", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "进度可控性", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

### 9. 合规性检查器

```python
# src/services/evaluation/checkers/compliance.py

from typing import Any, Dict
from .base import BaseChecker, CheckResult


class ComplianceChecker(BaseChecker):
    """合规性检查器"""
    
    dimension = "compliance"
    dimension_name = "合规性"
    default_weight = 0.10
    
    CHECK_ITEMS = [
        {"name": "内容完整性", "weight": 0.40, "description": "必填章节是否完整"},
        {"name": "格式规范性", "weight": 0.30, "description": "格式是否符合要求"},
        {"name": "政策符合性", "weight": 0.30, "description": "是否符合申报政策"},
    ]
    
    REQUIRED_SECTIONS = []  # 合规性检查需要全部章节
    
    async def check(
        self,
        project_info: Dict[str, Any],
        sections: Dict[str, str],
        **kwargs
    ) -> CheckResult:
        """执行合规性检查"""
        
        # 合规性检查需要查看所有章节
        all_content = "\n\n".join([f"【{k}】\n{v}" for k, v in sections.items()])
        if len(all_content) > 5000:
            all_content = all_content[:5000] + "..."
        
        context = {
            "project_name": project_info.get("xmmc", ""),
            "all_content": all_content,
        }
        
        prompt = self.get_prompt(context)
        response = await self.llm.ainvoke(prompt)
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response))
        
        return CheckResult(
            dimension=self.dimension,
            score=result.get("score", 5.0),
            confidence=result.get("confidence", 0.8),
            opinion=result.get("opinion", ""),
            issues=result.get("issues", []),
            highlights=result.get("highlights", []),
            details={"items": result.get("items", [])}
        )
    
    def get_prompt(self, context: Dict[str, Any]) -> str:
        return f"""你是一个科技项目评审专家。请评估以下项目申报材料的合规性。

## 项目信息

**项目名称**：{context['project_name']}

## 申报材料内容

{context['all_content']}

## 评审要求

请从以下 3 个方面进行评分（每项 1-10 分）：

1. **内容完整性**（权重40%）：必填章节是否完整、内容是否充实
2. **格式规范性**（权重30%）：格式是否符合要求、表述是否规范
3. **政策符合性**（权重30%）：是否符合申报政策、研究方向是否匹配

## 输出格式

```json
{{
  "score": <总评分1-10>,
  "items": [
    {{"name": "内容完整性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "格式规范性", "score": <1-10>, "comment": "<评价>"}},
    {{"name": "政策符合性", "score": <1-10>, "comment": "<评价>"}}
  ],
  "opinion": "<综合评审意见>",
  "issues": ["<问题1>"],
  "highlights": ["<亮点1>"],
  "confidence": <置信度0-1>
}}
```"""
```

---

## 检查器注册

```python
# src/services/evaluation/checkers/__init__.py

from typing import Any, Dict, Type

from .base import BaseChecker, CheckResult, CheckItem
from .feasibility import FeasibilityChecker
from .innovation import InnovationChecker
from .team import TeamChecker
from .outcome import OutcomeChecker
from .social_benefit import SocialBenefitChecker
from .economic_benefit import EconomicBenefitChecker
from .risk_control import RiskControlChecker
from .schedule import ScheduleChecker
from .compliance import ComplianceChecker


# 检查器注册表
CHECKER_REGISTRY: Dict[str, Type[BaseChecker]] = {
    "feasibility": FeasibilityChecker,
    "innovation": InnovationChecker,
    "team": TeamChecker,
    "outcome": OutcomeChecker,
    "social_benefit": SocialBenefitChecker,
    "economic_benefit": EconomicBenefitChecker,
    "risk_control": RiskControlChecker,
    "schedule": ScheduleChecker,
    "compliance": ComplianceChecker,
}


def get_checker(dimension: str, llm: Any = None) -> BaseChecker:
    """
    获取检查器实例
    
    Args:
        dimension: 维度代码
        llm: LLM 客户端实例
    
    Returns:
        BaseChecker: 检查器实例
    
    Raises:
        ValueError: 未知的维度代码
    """
    checker_class = CHECKER_REGISTRY.get(dimension)
    if not checker_class:
        raise ValueError(f"Unknown dimension: {dimension}")
    return checker_class(llm=llm)


def get_all_dimensions() -> list:
    """获取所有维度代码列表"""
    return list(CHECKER_REGISTRY.keys())


__all__ = [
    "BaseChecker",
    "CheckResult",
    "CheckItem",
    "CHECKER_REGISTRY",
    "get_checker",
    "get_all_dimensions",
    "FeasibilityChecker",
    "InnovationChecker",
    "TeamChecker",
    "OutcomeChecker",
    "SocialBenefitChecker",
    "EconomicBenefitChecker",
    "RiskControlChecker",
    "ScheduleChecker",
    "ComplianceChecker",
]
```

---

## 相关文档

- [← 评审维度详解](03-dimensions.md)
- [评分器设计 →](05-scorer.md)