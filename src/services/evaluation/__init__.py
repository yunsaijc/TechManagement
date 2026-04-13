"""
正文评审服务

提供项目正文内容的智能评审功能，包括9个评审维度的评分和分析。
"""
from .agent import EvaluationAgent
from .config import EvaluationConfig

__all__ = ["EvaluationAgent", "EvaluationConfig"]