"""LLM 统一封装

基于 LangChain 提供统一的 LLM 调用能力。
"""
from src.common.llm.config import LLMConfig
from src.common.llm.factory import get_llm_client

__all__ = ["get_llm_client", "LLMConfig"]
