"""
正文评审服务 - 配置模块

定义评审服务的配置项，包括维度配置、权重、提示词模板等。
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.models.evaluation import (
    DEFAULT_WEIGHTS,
    EvaluationDimension,
    DIMENSION_CATEGORIES,
    DIMENSION_NAMES,
)


class DimensionConfig(BaseModel):
    """单个维度配置"""
    code: str = Field(..., description="维度代码")
    name: str = Field(..., description="维度名称")
    category: str = Field(..., description="维度分类")
    default_weight: float = Field(..., ge=0, le=1, description="默认权重")
    enabled: bool = Field(default=True, description="是否启用")
    description: str = Field(default="", description="维度描述")
    check_items: List[Dict[str, str]] = Field(default_factory=list, description="检查项")
    required_sections: List[str] = Field(default_factory=list, description="依赖章节")


class EvaluationConfig(BaseModel):
    """评审服务配置"""
    
    # 维度配置
    dimensions: Dict[str, DimensionConfig] = Field(
        default_factory=lambda: EvaluationConfig._get_default_dimensions(),
        description="维度配置"
    )
    
    # 默认权重
    default_weights: Dict[str, float] = Field(
        default=DEFAULT_WEIGHTS,
        description="默认权重配置"
    )
    
    # 评审选项
    max_retries: int = Field(default=3, description="LLM调用最大重试次数")
    timeout: int = Field(default=300, description="评审超时时间（秒）")
    concurrency: int = Field(default=3, description="并发评审数")
    
    # 评分配置
    min_score: float = Field(default=1.0, description="最低分")
    max_score: float = Field(default=10.0, description="最高分")
    
    # 置信度阈值
    confidence_threshold: float = Field(
        default=0.6,
        description="置信度阈值，低于此值需要人工复核"
    )
    
    # 输出配置
    include_details: bool = Field(default=True, description="结果是否包含详情")
    
    @staticmethod
    def _get_default_dimensions() -> Dict[str, DimensionConfig]:
        """获取默认维度配置"""
        dimensions = {}
        
        # 核心维度
        dimensions[EvaluationDimension.FEASIBILITY.value] = DimensionConfig(
            code=EvaluationDimension.FEASIBILITY.value,
            name="技术可行性",
            category="核心维度",
            default_weight=0.15,
            description="评估项目技术路线的可行性和合理性",
            check_items=[
                {"name": "技术路线清晰度", "weight": "0.3", "description": "技术路线是否清晰、具体"},
                {"name": "关键技术成熟度", "weight": "0.3", "description": "关键技术是否成熟可靠"},
                {"name": "资源保障充分性", "weight": "0.2", "description": "所需资源是否有保障"},
                {"name": "实施条件完备性", "weight": "0.2", "description": "实施条件是否完备"},
            ],
            required_sections=["技术路线", "研究方案", "实施方案"],
        )
        
        dimensions[EvaluationDimension.INNOVATION.value] = DimensionConfig(
            code=EvaluationDimension.INNOVATION.value,
            name="创新性",
            category="核心维度",
            default_weight=0.15,
            description="评估项目的创新程度和技术突破",
            check_items=[
                {"name": "理论创新", "weight": "0.3", "description": "是否有理论创新"},
                {"name": "技术创新", "weight": "0.3", "description": "是否有技术创新"},
                {"name": "方法创新", "weight": "0.2", "description": "是否有方法创新"},
                {"name": "创新可行性", "weight": "0.2", "description": "创新点是否切实可行"},
            ],
            required_sections=["创新点", "技术方案", "研究内容"],
        )
        
        dimensions[EvaluationDimension.TEAM.value] = DimensionConfig(
            code=EvaluationDimension.TEAM.value,
            name="团队能力",
            category="核心维度",
            default_weight=0.10,
            description="评估项目团队的整体能力和结构",
            check_items=[
                {"name": "负责人资质", "weight": "0.3", "description": "负责人资质和业绩"},
                {"name": "团队结构", "weight": "0.25", "description": "团队结构是否合理"},
                {"name": "成员经验", "weight": "0.25", "description": "团队成员相关经验"},
                {"name": "分工明确性", "weight": "0.2", "description": "分工是否明确"},
            ],
            required_sections=["项目团队", "人员分工", "成员简介"],
        )
        
        # 成果维度
        dimensions[EvaluationDimension.OUTCOME.value] = DimensionConfig(
            code=EvaluationDimension.OUTCOME.value,
            name="预期成果",
            category="成果维度",
            default_weight=0.12,
            description="评估项目预期成果的质量和价值",
            check_items=[
                {"name": "成果量化", "weight": "0.25", "description": "成果是否可量化考核"},
                {"name": "技术指标", "weight": "0.3", "description": "技术指标是否先进"},
                {"name": "成果质量", "weight": "0.25", "description": "预期成果质量如何"},
                {"name": "成果可行性", "weight": "0.2", "description": "成果目标是否可实现"},
            ],
            required_sections=["预期成果", "考核指标", "技术指标"],
        )
        
        dimensions[EvaluationDimension.SOCIAL_BENEFIT.value] = DimensionConfig(
            code=EvaluationDimension.SOCIAL_BENEFIT.value,
            name="社会效益",
            category="成果维度",
            default_weight=0.10,
            description="评估项目的社会效益和推广应用价值",
            check_items=[
                {"name": "社会贡献", "weight": "0.3", "description": "对社会发展的贡献"},
                {"name": "推广价值", "weight": "0.3", "description": "成果推广应用价值"},
                {"name": "人才培养", "weight": "0.2", "description": "对人才培养的贡献"},
                {"name": "学科发展", "weight": "0.2", "description": "对学科发展的推动"},
            ],
            required_sections=["预期效益", "社会效益", "推广应用"],
        )
        
        dimensions[EvaluationDimension.ECONOMIC_BENEFIT.value] = DimensionConfig(
            code=EvaluationDimension.ECONOMIC_BENEFIT.value,
            name="经济效益",
            category="成果维度",
            default_weight=0.10,
            description="评估项目的经济效益和产业化前景",
            check_items=[
                {"name": "直接经济效益", "weight": "0.3", "description": "直接产生的经济效益"},
                {"name": "间接经济效益", "weight": "0.25", "description": "间接带来的经济效益"},
                {"name": "产业化前景", "weight": "0.25", "description": "产业化应用前景"},
                {"name": "经济效益可行性", "weight": "0.2", "description": "效益预期是否合理"},
            ],
            required_sections=["预期效益", "经济效益", "产业化"],
        )
        
        # 管理维度
        dimensions[EvaluationDimension.RISK_CONTROL.value] = DimensionConfig(
            code=EvaluationDimension.RISK_CONTROL.value,
            name="风险控制",
            category="管理维度",
            default_weight=0.08,
            description="评估项目风险识别和控制措施",
            check_items=[
                {"name": "风险识别", "weight": "0.35", "description": "风险识别是否全面"},
                {"name": "风险分析", "weight": "0.3", "description": "风险分析是否深入"},
                {"name": "应对措施", "weight": "0.35", "description": "应对措施是否有效"},
            ],
            required_sections=["风险分析", "风险控制", "风险管理"],
        )
        
        dimensions[EvaluationDimension.SCHEDULE.value] = DimensionConfig(
            code=EvaluationDimension.SCHEDULE.value,
            name="进度合理性",
            category="管理维度",
            default_weight=0.10,
            description="评估项目进度安排的合理性",
            check_items=[
                {"name": "阶段划分", "weight": "0.3", "description": "阶段划分是否清晰"},
                {"name": "时间安排", "weight": "0.3", "description": "时间安排是否合理"},
                {"name": "里程碑明确性", "weight": "0.2", "description": "里程碑是否明确"},
                {"name": "计划可行性", "weight": "0.2", "description": "整体计划是否可行"},
            ],
            required_sections=["进度安排", "实施计划", "工作计划"],
        )
        
        dimensions[EvaluationDimension.COMPLIANCE.value] = DimensionConfig(
            code=EvaluationDimension.COMPLIANCE.value,
            name="合规性",
            category="管理维度",
            default_weight=0.10,
            description="评估项目的合规性和规范性",
            check_items=[
                {"name": "政策符合性", "weight": "0.3", "description": "是否符合相关政策"},
                {"name": "伦理合规", "weight": "0.25", "description": "是否符合伦理要求"},
                {"name": "规范完整", "weight": "0.25", "description": "文档是否规范完整"},
                {"name": "预算合理性", "weight": "0.2", "description": "预算是否合理合规"},
            ],
            required_sections=["政策依据", "经费预算", "伦理审查"],
        )
        
        return dimensions
    
    def get_dimension_config(self, dimension: str) -> Optional[DimensionConfig]:
        """获取指定维度的配置"""
        return self.dimensions.get(dimension)
    
    def get_enabled_dimensions(self) -> List[str]:
        """获取启用的维度列表"""
        return [code for code, config in self.dimensions.items() if config.enabled]
    
    def get_weight(self, dimension: str) -> float:
        """获取指定维度的权重"""
        config = self.dimensions.get(dimension)
        return config.default_weight if config else self.default_weights.get(dimension, 0.0)
    
    def validate_weights(self, weights: Dict[str, float]) -> tuple[bool, str, Dict[str, float]]:
        """验证权重配置
        
        Returns:
            (是否有效, 消息, 归一化后的权重)
        """
        enabled = self.get_enabled_dimensions()
        
        # 检查维度是否有效
        invalid_dims = [d for d in weights if d not in enabled]
        if invalid_dims:
            return False, f"无效的维度: {invalid_dims}", {}
        
        # 如果没有指定权重，使用默认权重
        if not weights:
            return True, "使用默认权重", self.default_weights.copy()
        
        # 检查权重范围
        for dim, w in weights.items():
            if w < 0 or w > 1:
                return False, f"维度 {dim} 的权重 {w} 不在有效范围 [0, 1] 内", {}
        
        # 归一化权重
        total = sum(weights.values())
        if total == 0:
            return False, "权重总和不能为0", {}
        
        normalized = {k: v / total for k, v in weights.items()}
        
        return True, "权重验证通过", normalized


# 全局配置实例
evaluation_config = EvaluationConfig()