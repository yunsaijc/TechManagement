"""
Embedding 向量模型工厂

支持多种Embedding providers
"""
from typing import List, Optional
import numpy as np
import requests

from src.common.llm.embedding_config import embedding_config


class DashscopeEmbeddings:
    """Dashscope embedding client (qwen)"""
    
    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v3", dimension: int = 1024):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.dimension = dimension
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        embeddings = []
        for text in texts:
            data = {
                "model": self.model,
                "input": text
            }
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json=data,
                headers=headers,
                timeout=30
            )
            resp.raise_for_status()
            result = resp.json()
            embeddings.append(result["data"][0]["embedding"])
        
        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """Embed a single text"""
        return self.embed_documents([text])[0]


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
        Embeddings 实例
    """
    # 使用配置或传入的参数
    provider = provider or embedding_config.provider
    model = model or embedding_config.model
    api_key = api_key or embedding_config.api_key
    base_url = base_url or embedding_config.base_url
    dimension = dimension or embedding_config.dimension
    
    if provider == "qwen":
        # 使用自定义Dashscope客户端
        return DashscopeEmbeddings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            dimension=dimension
        )
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=model,
            api_key=api_key,
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
        默认 Embeddings 实例
    """
    return get_embedding_client()
