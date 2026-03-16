"""Embedding 向量模型工厂"""
from typing import List, Optional

from langchain_openai import OpenAIEmbeddings

from src.common.llm.embedding_config import embedding_config


def get_embedding_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    dimension: Optional[int] = None,
    **kwargs
):
    """获取 Embedding 客户端

    Args:
        provider: 提供商 (openai/qwen/minimax/local)
        model: 模型名称
        api_key: API Key
        base_url: 自定义端点
        dimension: 向量维度

    Returns:
        LangChain Embeddings 实例
    """
    # 使用配置或传入的参数
    provider = provider or embedding_config.provider
    model = model or embedding_config.model
    api_key = api_key or embedding_config.api_key
    base_url = base_url or embedding_config.base_url
    dimension = dimension or embedding_config.dimension

    if provider == "openai":
        return OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            dimensions=dimension,
            **kwargs
        )
    elif provider == "qwen":
        # 阿里云通义千问 embedding
        return OpenAIEmbeddings(
            model=model or "text-embedding-v3",
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            dimensions=dimension,
            **kwargs
        )
    elif provider == "minimax":
        return OpenAIEmbeddings(
            model=model or "embo-01",
            api_key=api_key,
            base_url=base_url or "https://api.minimax.chat/v1",
            dimensions=dimension,
            **kwargs
        )
    elif provider == "azure":
        from langchain_openai import AzureOpenAIEmbeddings
        return AzureOpenAIEmbeddings(
            model=model,
            api_key=api_key,
            azure_endpoint=base_url,
            dimensions=dimension,
            **kwargs
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


def get_default_embedding_client():
    """获取默认 Embedding 客户端

    Returns:
        默认 LangChain Embeddings 实例
    """
    return get_embedding_client()
