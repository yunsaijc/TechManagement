"""LLM 统一封装

基于 LangChain 提供统一的 LLM 调用能力。
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from src.common.llm.config import LLMConfig
from src.common.llm.factory import get_llm_client
from src.common.llm.embedding_config import EmbeddingConfig
from src.common.llm.embedding_factory import (
    get_embedding_client,
    get_default_embedding_client,
)

# 全局 LLM 配置实例
llm_config = LLMConfig()

# 全局 Embedding 配置实例
embedding_config = EmbeddingConfig()


def get_default_llm_client():
    """获取默认 LLM 客户端（使用环境变量配置）"""
    api_key = (
        llm_config.api_key
        or os.getenv("apikey")
        or os.getenv("API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    return get_llm_client(
        provider=llm_config.provider or "openai",
        model=llm_config.model or None,
        api_key=api_key or None,
        base_url=llm_config.base_url or None,
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens,
        timeout=llm_config.timeout,
        max_retries=llm_config.max_retries,
    )


def get_review_llm_client():
    """获取 review 场景专用 LLM 客户端。

    review 审查链路更看重可复现性而不是发散性，统一固定 temperature=0.7。
    """
    api_key = (
        llm_config.api_key
        or os.getenv("apikey")
        or os.getenv("API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    extra_body = None
    if llm_config.provider == "qwen" and llm_config.model.startswith("qwen3.5"):
        # review 链路以抽取/定位/校验为主，统一关闭 thinking，避免长耗时与脑补。
        extra_body = {"enable_thinking": False}
    return get_llm_client(
        provider=llm_config.provider or "openai",
        model=llm_config.model or None,
        api_key=api_key or None,
        base_url=llm_config.base_url or None,
        temperature=0.7,
        max_tokens=llm_config.max_tokens,
        timeout=llm_config.timeout,
        max_retries=llm_config.max_retries,
        extra_body=extra_body,
    )


__all__ = [
    "get_llm_client",
    "LLMConfig",
    "get_default_llm_client",
    "get_review_llm_client",
    "llm_config",
    "get_embedding_client",
    "get_default_embedding_client",
    "EmbeddingConfig",
    "embedding_config",
]
