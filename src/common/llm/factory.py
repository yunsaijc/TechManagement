"""LLM 客户端工厂"""
from typing import Optional

from langchain_openai import ChatOpenAI


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
    if provider == "openai":
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
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
            **kwargs
        )
    elif provider == "azure":
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            model=model,
            api_key=api_key,
            azure_endpoint=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
