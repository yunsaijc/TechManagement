"""Embedding 向量模型工厂"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
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
        self.batch_size = 1
        self.max_workers = 2
        self.max_retries = 3

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        if not batch:
            return []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": self.model,
            "input": batch[0]
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/embeddings",
                    json=data,
                    headers=headers,
                    timeout=60
                )
                if resp.status_code == 429:
                    wait_seconds = 2 ** attempt
                    time.sleep(wait_seconds)
                    continue
                resp.raise_for_status()
                result = resp.json()
                items = result.get("data", [])
                if len(items) != 1:
                    raise RuntimeError("Dashscope embedding response missing embeddings")
                return [item["embedding"] for item in items]
            except requests.HTTPError as exc:
                last_error = exc
                if getattr(exc.response, "status_code", None) == 429 and attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Dashscope embedding request failed")
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts"""
        if not texts:
            return []

        indexed_batches = [
            (start, texts[start:start + self.batch_size])
            for start in range(0, len(texts), self.batch_size)
        ]

        ordered_results: dict[int, List[List[float]]] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(indexed_batches))) as executor:
            future_map = {
                executor.submit(self._embed_batch, batch): start
                for start, batch in indexed_batches
            }
            for future in as_completed(future_map):
                start = future_map[future]
                ordered_results[start] = future.result()

        embeddings: List[List[float]] = []
        for start, _ in indexed_batches:
            embeddings.extend(ordered_results[start])

        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """Embed a single text"""
        return self.embed_documents([text])[0]


def get_embedding_client(
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dimension: Optional[int] = None,
        **kwargs
):
    """获取 Embeddings 客户端

    Args:
        provider: Embedding提供商
        api_key: API密钥
        base_url: API基础URL
        model: 模型名称
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
