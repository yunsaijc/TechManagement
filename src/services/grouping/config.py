"""智能分组与专家匹配服务 - 配置"""
from pydantic_settings import BaseSettings


class GroupingSettings(BaseSettings):
    """分组服务配置"""

    # 分组配置
    default_max_per_group: int = 30  # 每组默认最大项目数
    default_experts_per_project: int = 5  # 每个项目默认专家数
    default_min_experts_per_group: int = 10  # 每组默认最少懂行专家数

    # Embedding 配置
    embedding_model: str = "bge-m3"  # 向量化模型
    embedding_dimension: int = 1024  # 向量维度

    # 匹配配置
    match_score_threshold: float = 60.0  # 匹配度阈值
    enable_avoidance: bool = True  # 启用回避

    class Config:
        env_prefix = "GROUPING_"


# 全局配置实例
grouping_settings = GroupingSettings()
