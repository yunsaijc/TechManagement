"""LLM 配置"""
from typing import Optional

from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM 配置"""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096

    class Config:
        env_prefix = "LLM_"
