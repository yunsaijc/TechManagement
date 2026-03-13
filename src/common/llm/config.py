"""
LLM 配置

配置从环境变量读取，参考 .env.example
"""
from typing import Optional

from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM 配置 - 从环境变量读取"""

    provider: str = ""  # openai, anthropic, qwen, azure, minimax
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    class Config:
        env_prefix = "LLM_"


# 全局配置实例
llm_config = LLMConfig()
