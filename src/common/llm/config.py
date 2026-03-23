"""
LLM 配置

配置从环境变量读取，参考 .env.example
"""
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class LLMConfig(BaseSettings):
    """LLM 配置 - 从环境变量读取"""

    # 显式指定 .env，避免仅依赖 shell export。
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = Field(
        default="openai",
        validation_alias=AliasChoices("LLM_PROVIDER", "OPENAI_PROVIDER"),
    )  # openai, anthropic, qwen, azure, minimax
    model: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = Field(
        default=30.0,
        validation_alias=AliasChoices("LLM_TIMEOUT", "OPENAI_TIMEOUT"),
    )
    max_retries: int = Field(
        default=2,
        validation_alias=AliasChoices("LLM_MAX_RETRIES", "OPENAI_MAX_RETRIES"),
    )

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, v: Optional[str]) -> str:
        return (v or "openai").strip().lower()

    @field_validator("model", "api_key", "base_url", mode="before")
    @classmethod
    def _strip_text(cls, v: Optional[str]) -> str:
        return (v or "").strip()

    @field_validator("max_retries", mode="before")
    @classmethod
    def _normalize_max_retries(cls, v: Optional[int]) -> int:
        # 重试统一收口到客户端层；底层 SDK 使用指数退避策略。
        retries = int(v if v is not None else 2)
        return max(0, min(retries, 5))


# 全局配置实例
llm_config = LLMConfig()
