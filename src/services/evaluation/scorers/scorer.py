"""
评审评分器

综合各维度评分，计算总分、等级和生成综合意见。
"""
from typing import Dict, List, Optional

from src.common.models.evaluation import (
    DimensionScore,
    EvaluationResult,
    CheckResult,
    GRADE_THRESHOLDS,
    DEFAULT_WEIGHTS,
)


class EvaluationScorer:
    """评审评分器
    
    负责：
    1. 综合各维度评分
    2. 计算加权总分
    3. 判定等级
    4. 生成综合意见和修改建议
    """
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """初始化评分器
        
        Args:
            weights: 自定义权重，默认使用 DEFAULT_WEIGHTS
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
    
    def calculate_overall_score(
        self, 
        dimension_scores: List[DimensionScore]
    ) -> float:
        """计算加权总分
        
        Args:
            dimension_scores: 各维度评分列表
            
        Returns:
            float: 加权总分
        """
        if not dimension_scores:
            return 0.0
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for dim_score in dimension_scores:
            weight = dim_score.weight
            total_weight += weight
            weighted_sum += dim_score.score * weight
        
        if total_weight == 0:
            return 0.0
        
        return round(weighted_sum / total_weight, 2)
    
    def determine_grade(self, score: float) -> str:
        """根据分数判定等级
        
        Args:
            score: 总分
            
        Returns:
            str: 等级（A/B/C/D/E）
        """
        for grade, threshold in GRADE_THRESHOLDS.items():
            if score >= threshold:
                return grade
        return "E"
    
    def convert_check_result_to_dimension_score(
        self,
        check_result: CheckResult,
        weight: Optional[float] = None
    ) -> DimensionScore:
        """将检查结果转换为维度评分
        
        Args:
            check_result: 检查结果
            weight: 权重，如未指定则从配置获取
            
        Returns:
            DimensionScore: 维度评分
        """
        if weight is None:
            weight = self.weights.get(check_result.dimension, 0.1)
        
        weighted_score = round(check_result.score * weight, 3)
        
        return DimensionScore(
            dimension=check_result.dimension,
            dimension_name=check_result.dimension_name,
            score=check_result.score,
            weight=weight,
            weighted_score=weighted_score,
            confidence=check_result.confidence,
            opinion=check_result.opinion,
            issues=check_result.issues,
            highlights=check_result.highlights,
            items=check_result.items,
        )
    
    def generate_summary(
        self,
        dimension_scores: List[DimensionScore],
        overall_score: float,
        grade: str
    ) -> str:
        """生成综合意见
        
        Args:
            dimension_scores: 各维度评分
            overall_score: 总分
            grade: 等级
            
        Returns:
            str: 综合意见
        """
        # 统计各维度表现
        high_scores = []
        medium_scores = []
        low_scores = []
        
        for dim in dimension_scores:
            if dim.score >= 8:
                high_scores.append(dim.dimension_name)
            elif dim.score >= 6:
                medium_scores.append(dim.dimension_name)
            else:
                low_scores.append(dim.dimension_name)
        
        # 构建综合意见
        parts = []
        
        # 等级说明
        grade_desc = {
            "A": "优秀",
            "B": "良好",
            "C": "中等",
            "D": "较差",
            "E": "不合格"
        }
        parts.append(f"本项目综合评分{overall_score}分，等级评定为{grade}级（{grade_desc.get(grade, '')}）。")
        
        # 优势维度
        if high_scores:
            parts.append(f"项目在{chr(12289).join(high_scores)}等方面表现突出。")
        
        # 中等维度
        if medium_scores:
            parts.append(f"在{chr(12289).join(medium_scores)}等方面表现一般，有改进空间。")
        
        # 不足维度
        if low_scores:
            parts.append(f"在{chr(12289).join(low_scores)}等方面存在明显不足，需要重点关注。")
        
        return "".join(parts)
    
    def generate_recommendations(
        self,
        dimension_scores: List[DimensionScore]
    ) -> List[str]:
        """生成修改建议
        
        Args:
            dimension_scores: 各维度评分
            
        Returns:
            List[str]: 修改建议列表
        """
        recommendations = []
        
        for dim in dimension_scores:
            # 对于分数低于6分的维度，给出具体建议
            if dim.score < 6:
                issues_str = "；".join(dim.issues[:3]) if dim.issues else "需要进一步改进"
                recommendations.append(f"【{dim.dimension_name}】{issues_str}")
        
        # 如果没有明显问题，给出整体建议
        if not recommendations:
            recommendations.append("项目整体表现良好，建议进一步完善细节，提高各项指标的先进性。")
        
        return recommendations
    
    def build_result(
        self,
        project_id: str,
        project_name: Optional[str],
        check_results: List[CheckResult],
        weights: Optional[Dict[str, float]] = None
    ) -> EvaluationResult:
        """构建评审结果
        
        Args:
            project_id: 项目ID
            project_name: 项目名称
            check_results: 检查结果列表
            weights: 权重配置
            
        Returns:
            EvaluationResult: 评审结果
        """
        # 使用传入的权重或默认权重
        use_weights = weights or self.weights
        
        # 转换检查结果为维度评分
        dimension_scores = []
        for check in check_results:
            weight = use_weights.get(check.dimension, 0.1)
            dim_score = self.convert_check_result_to_dimension_score(check, weight)
            dimension_scores.append(dim_score)
        
        # 计算总分
        overall_score = self.calculate_overall_score(dimension_scores)
        
        # 判定等级
        grade = self.determine_grade(overall_score)
        
        # 生成综合意见
        summary = self.generate_summary(dimension_scores, overall_score, grade)
        
        # 生成建议
        recommendations = self.generate_recommendations(dimension_scores)
        
        return EvaluationResult(
            project_id=project_id,
            project_name=project_name,
            overall_score=overall_score,
            grade=grade,
            dimension_scores=dimension_scores,
            summary=summary,
            recommendations=recommendations,
        )