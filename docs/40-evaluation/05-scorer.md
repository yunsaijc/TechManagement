# 📈 评分器设计

## 评分流程

```
┌─────────────────────────────────────────────────────────────┐
│                       评分流程                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  检查结果 ──→ 维度评分 ──→ 权重计算 ──→ 总分 ──→ 等级      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 维度评分器 (DimensionScorer)

负责将各维度的检查结果转换为标准化的评分对象，并计算加权得分。

### 2. 权重计算器 (WeightCalculator)

负责管理和计算各维度的权重，支持预设模板和自定义权重。

### 3. 等级判定器 (GradeDeterminer)

根据总分判定项目等级。

---

## 维度评分器

### 职责

1. 构建维度评分对象
2. 计算加权得分
3. 判定等级
4. 生成综合评审意见

### 实现

```python
# src/services/evaluation/scorers/dimension_scorer.py

from typing import Dict, List, Optional
from pydantic import BaseModel

from src.common.models.evaluation import (
    EvaluationDimension,
    DimensionScore,
    DEFAULT_WEIGHTS,
)


class DimensionScorer:
    """维度评分器"""
    
    # 等级阈值
    GRADE_THRESHOLDS = {
        "A": 9.0,   # 优秀：≥9.0
        "B": 8.0,   # 良好：≥8.0
        "C": 6.0,   # 中等：≥6.0
        "D": 4.0,   # 较差：≥4.0
        "E": 0.0,   # 不合格：<4.0
    }
    
    # 等级描述
    GRADE_DESCRIPTIONS = {
        "A": "优秀",
        "B": "良好",
        "C": "中等",
        "D": "较差",
        "E": "不合格",
    }
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        初始化评分器
        
        Args:
            weights: 权重配置，默认使用 DEFAULT_WEIGHTS
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self._validate_weights()
    
    def _validate_weights(self) -> None:
        """验证权重总和为 1"""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"权重总和必须为 1，当前为 {total}")
    
    def calculate_weighted_score(
        self, 
        dimension_scores: Dict[str, float]
    ) -> float:
        """
        计算加权总分
        
        Args:
            dimension_scores: 各维度原始得分 {dimension: score}
        
        Returns:
            float: 加权总分（1-10分）
        """
        total = 0.0
        for dim, score in dimension_scores.items():
            weight = self.weights.get(dim, 0.0)
            total += score * weight
        return round(total, 2)
    
    def build_dimension_score(
        self,
        dimension: str,
        score: float,
        opinion: str,
        issues: List[str] = None,
        highlights: List[str] = None,
        confidence: float = 0.8,
    ) -> DimensionScore:
        """
        构建维度评分对象
        
        Args:
            dimension: 维度代码
            score: 原始得分（1-10分）
            opinion: 评审意见
            issues: 问题列表
            highlights: 亮点列表
            confidence: 置信度
        
        Returns:
            DimensionScore: 维度评分对象
        """
        weight = self.weights.get(dimension, 0.0)
        weighted_score = round(score * weight, 3)
        
        return DimensionScore(
            dimension=dimension,
            score=score,
            weight=weight,
            weighted_score=weighted_score,
            confidence=confidence,
            opinion=opinion,
            issues=issues or [],
            highlights=highlights or [],
        )
    
    def determine_grade(self, total_score: float) -> str:
        """
        判定等级
        
        Args:
            total_score: 总分
        
        Returns:
            str: 等级（A/B/C/D/E）
        """
        for grade, threshold in self.GRADE_THRESHOLDS.items():
            if total_score >= threshold:
                return grade
        return "E"
    
    def get_grade_description(self, grade: str) -> str:
        """获取等级描述"""
        return self.GRADE_DESCRIPTIONS.get(grade, "未知")
    
    def generate_summary(
        self,
        dimension_scores: List[DimensionScore],
        grade: str
    ) -> str:
        """
        生成综合评审意见
        
        Args:
            dimension_scores: 各维度评分列表
            grade: 等级
        
        Returns:
            str: 综合评审意见
        """
        grade_desc = self.GRADE_DESCRIPTIONS.get(grade, "未知")
        
        # 按分数排序
        sorted_scores = sorted(
            dimension_scores, 
            key=lambda x: x.score, 
            reverse=True
        )
        
        # 找出高分维度（≥8分）
        top_dims = [d for d in sorted_scores if d.score >= 8.0][:3]
        
        # 找出低分维度（<6分）
        low_dims = [d for d in sorted_scores if d.score < 6.0]
        
        # 构建意见
        parts = [f"本项目综合评审等级为{grade_desc}（{grade}级）。"]
        
        if top_dims:
            dim_names = "、".join([self._get_dim_name(d.dimension) for d in top_dims])
            parts.append(f"优势维度包括：{dim_names}。")
        
        if low_dims:
            dim_names = "、".join([self._get_dim_name(d.dimension) for d in low_dims])
            parts.append(f"需要改进的维度：{dim_names}。")
        
        return "".join(parts)
    
    def _get_dim_name(self, dimension: str) -> str:
        """获取维度中文名称"""
        DIMENSION_NAMES = {
            "feasibility": "技术可行性",
            "innovation": "创新性",
            "team": "团队能力",
            "outcome": "预期成果",
            "social_benefit": "社会效益",
            "economic_benefit": "经济效益",
            "risk_control": "风险控制",
            "schedule": "进度合理性",
            "compliance": "合规性",
        }
        return DIMENSION_NAMES.get(dimension, dimension)
```

---

## 权重计算器

### 职责

1. 管理权重模板
2. 支持自定义权重
3. 权重归一化

### 实现

```python
# src/services/evaluation/scorers/weight_calculator.py

from typing import Dict, List, Optional
from pydantic import BaseModel


class WeightTemplate(BaseModel):
    """权重模板"""
    name: str                           # 模板名称
    description: str                    # 模板描述
    weights: Dict[str, float]           # 权重配置


class WeightCalculator:
    """权重计算器"""
    
    # 预设权重模板
    WEIGHT_TEMPLATES: Dict[str, WeightTemplate] = {
        "default": WeightTemplate(
            name="默认权重",
            description="适用于一般项目的均衡权重配置",
            weights={
                "feasibility": 0.15,
                "innovation": 0.15,
                "team": 0.10,
                "outcome": 0.12,
                "social_benefit": 0.10,
                "economic_benefit": 0.10,
                "risk_control": 0.08,
                "schedule": 0.10,
                "compliance": 0.10,
            }
        ),
        "innovation_focused": WeightTemplate(
            name="创新导向",
            description="适用于创新类项目，提高创新性权重",
            weights={
                "feasibility": 0.10,
                "innovation": 0.25,
                "team": 0.10,
                "outcome": 0.15,
                "social_benefit": 0.10,
                "economic_benefit": 0.10,
                "risk_control": 0.05,
                "schedule": 0.05,
                "compliance": 0.10,
            }
        ),
        "application_focused": WeightTemplate(
            name="应用导向",
            description="适用于应用类项目，提高可行性和经济效益权重",
            weights={
                "feasibility": 0.20,
                "innovation": 0.10,
                "team": 0.10,
                "outcome": 0.15,
                "social_benefit": 0.10,
                "economic_benefit": 0.15,
                "risk_control": 0.10,
                "schedule": 0.05,
                "compliance": 0.05,
            }
        ),
        "team_focused": WeightTemplate(
            name="团队导向",
            description="适用于人才类项目，提高团队能力权重",
            weights={
                "feasibility": 0.10,
                "innovation": 0.15,
                "team": 0.25,
                "outcome": 0.15,
                "social_benefit": 0.05,
                "economic_benefit": 0.05,
                "risk_control": 0.05,
                "schedule": 0.10,
                "compliance": 0.10,
            }
        ),
    }
    
    @classmethod
    def get_weights(
        cls, 
        template: str = "default",
        custom_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        获取权重配置
        
        Args:
            template: 预设模板名称
            custom_weights: 自定义权重（会覆盖模板）
        
        Returns:
            Dict[str, float]: 最终权重配置
        """
        # 获取模板权重
        template_obj = cls.WEIGHT_TEMPLATES.get(template)
        if not template_obj:
            template_obj = cls.WEIGHT_TEMPLATES["default"]
        
        weights = template_obj.weights.copy()
        
        # 应用自定义权重
        if custom_weights:
            weights.update(custom_weights)
            
            # 归一化
            total = sum(weights.values())
            if total > 0:
                weights = {k: round(v / total, 4) for k, v in weights.items()}
        
        return weights
    
    @classmethod
    def list_templates(cls) -> Dict[str, WeightTemplate]:
        """列出所有权重模板"""
        return cls.WEIGHT_TEMPLATES.copy()
    
    @classmethod
    def get_template(cls, name: str) -> Optional[WeightTemplate]:
        """获取指定模板"""
        return cls.WEIGHT_TEMPLATES.get(name)
    
    @classmethod
    def validate_weights(cls, weights: Dict[str, float]) -> bool:
        """
        验证权重配置
        
        Args:
            weights: 权重配置
        
        Returns:
            bool: 是否有效
        """
        # 检查是否为空
        if not weights:
            return False
        
        # 检查所有值是否为正数
        for v in weights.values():
            if v < 0:
                return False
        
        # 检查总和是否接近 1
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            return False
        
        return True
```

---

## 评分报告生成器

### 职责

1. 聚合各维度评分
2. 生成完整评审报告
3. 生成修改建议

### 实现

```python
# src/services/evaluation/scorers/report_generator.py

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel

from src.common.models.evaluation import (
    EvaluationResult,
    DimensionScore,
)


class ReportGenerator:
    """评分报告生成器"""
    
    def generate(
        self,
        project_id: str,
        project_name: str,
        dimension_scores: List[DimensionScore],
        overall_score: float,
        grade: str,
        summary: str,
    ) -> EvaluationResult:
        """
        生成评审报告
        
        Args:
            project_id: 项目ID
            project_name: 项目名称
            dimension_scores: 各维度评分
            overall_score: 总分
            grade: 等级
            summary: 综合意见
        
        Returns:
            EvaluationResult: 完整评审结果
        """
        # 生成修改建议
        recommendations = self._generate_recommendations(dimension_scores, grade)
        
        return EvaluationResult(
            project_id=project_id,
            project_name=project_name,
            overall_score=overall_score,
            grade=grade,
            dimension_scores=dimension_scores,
            summary=summary,
            recommendations=recommendations,
            created_at=datetime.now(),
        )
    
    def _generate_recommendations(
        self,
        dimension_scores: List[DimensionScore],
        grade: str,
    ) -> List[str]:
        """
        生成修改建议
        
        Args:
            dimension_scores: 各维度评分
            grade: 等级
        
        Returns:
            List[str]: 建议列表
        """

### 调试输出约定

- 评审完成后，`EvaluationAgent` 应调用 `ReportGenerator` 生成 HTML 调试报告
- 调试产物统一写入 `debug_eval/`
- 文件命名建议：
  - `{evaluation_id}.json`
  - `{evaluation_id}.html`
  - `index.html`
        recommendations = []
        
        # 根据等级添加总体建议
        if grade == "E":
            recommendations.append("建议对项目申报书进行全面修订后重新提交。")
        elif grade == "D":
            recommendations.append("建议针对主要问题进行修改完善后重新提交。")
        
        # 针对低分维度添加具体建议
        dim_names = {
            "feasibility": "技术可行性",
            "innovation": "创新性",
            "team": "团队能力",
            "outcome": "预期成果",
            "social_benefit": "社会效益",
            "economic_benefit": "经济效益",
            "risk_control": "风险控制",
            "schedule": "进度合理性",
            "compliance": "合规性",
        }
        
        for score in dimension_scores:
            if score.score < 6.0:
                dim_name = dim_names.get(score.dimension, score.dimension)
                for issue in score.issues[:2]:  # 最多取2个问题
                    recommendations.append(f"【{dim_name}】{issue}")
        
        # 限制建议数量
        return recommendations[:10]
```

---

## 评分流程示例

### 输入

```python
# 各维度原始得分
dimension_scores = {
    "feasibility": 8.5,
    "innovation": 9.0,
    "team": 7.5,
    "outcome": 8.0,
    "social_benefit": 7.0,
    "economic_benefit": 6.5,
    "risk_control": 8.0,
    "schedule": 7.5,
    "compliance": 9.0,
}

# 权重配置
weights = {
    "feasibility": 0.15,
    "innovation": 0.15,
    "team": 0.10,
    "outcome": 0.12,
    "social_benefit": 0.10,
    "economic_benefit": 0.10,
    "risk_control": 0.08,
    "schedule": 0.10,
    "compliance": 0.10,
}
```

### 计算过程

```
维度            得分    权重    加权得分
───────────────────────────────────────
技术可行性      8.5    0.15     1.275
创新性          9.0    0.15     1.350
团队能力        7.5    0.10     0.750
预期成果        8.0    0.12     0.960
社会效益        7.0    0.10     0.700
经济效益        6.5    0.10     0.650
风险控制        8.0    0.08     0.640
进度合理性      7.5    0.10     0.750
合规性          9.0    0.10     0.900
───────────────────────────────────────
总分                              7.975 ≈ 8.0

等级判定：B (良好)
```

### 输出

```python
EvaluationResult(
    project_id="202520014",
    project_name="基于深度学习的智能诊断系统研究",
    overall_score=8.0,
    grade="B",
    dimension_scores=[...],
    summary="本项目综合评审等级为良好（B级）。优势维度包括：创新性、合规性、技术可行性。需要改进的维度：经济效益。",
    recommendations=[
        "【经济效益】建议进一步量化经济回报预期，明确市场分析数据来源"
    ],
    created_at=datetime(2026, 3, 25, 10, 30, 0),
)
```

---

## 相关文档

- [← 检查器设计](04-checkers.md)
- [Agent 设计 →](06-agent.md)
