"""LLM 客户端工厂"""
import os
from typing import Optional

import httpx

from langchain_openai import ChatOpenAI


def _should_bypass_local_proxy() -> bool:
    """仅在检测到本地回环代理注入时绕过环境代理。"""
    keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ]
    for k in keys:
        v = str(os.getenv(k, "") or "").strip().lower()
        if not v:
            continue
        if "127.0.0.1" in v or "localhost" in v:
            return True
    return False


def _with_proxy_safety_kwargs(kwargs: dict) -> dict:
    """为 OpenAI 兼容客户端附加安全的 http client（必要时）。"""
    if not _should_bypass_local_proxy():
        return kwargs
    out = dict(kwargs)
    # 避免本地代理注入导致的 403/连接失败。
    out.setdefault("http_client", httpx.Client(trust_env=False))
    out.setdefault("http_async_client", httpx.AsyncClient(trust_env=False))
    return out


def get_llm_client(
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    **kwargs
):
    """获取 LLM 客户端

    Args:
        provider: 提供商 "openai" / "anthropic" / "qwen"
        model: 模型名称
        api_key: API Key
        base_url: 自定义端点
        temperature: 温度
        max_tokens: 最大 token 数

    Returns:
        LangChain ChatModel 实例
    """
    safe_kwargs = _with_proxy_safety_kwargs(kwargs)
    if provider == "openai":
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-3-5-sonnet-20241022",
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    elif provider == "qwen":
        return ChatOpenAI(
            model=model or "qwen-vl-max",
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs
        )
    elif provider == "azure":
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            model=model,
            api_key=api_key,
            azure_endpoint=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs
        )
    elif provider == "minimax":
        return ChatOpenAI(
            model=model or "abab6.5s-chat",
            api_key=api_key,
            base_url=base_url or "https://api.minimax.chat/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            **safe_kwargs
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
