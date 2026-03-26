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
        self.batch_size = 10  # Dashscope批量最大10条
        self.max_workers = 5  # 并发数
        self.max_retries = 3

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        if not batch:
            return []
        
        # 过滤空字符串
        batch = [text for text in batch if text and text.strip()]
        if not batch:
            return []
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        # 支持真正的批量请求 - DashScope/OpenAI 兼容格式
        data = {
            "model": self.model,
            "input": batch  # 直接传字符串列表
        }
        
        # 调试日志
        import logging
        logging.getLogger(__name__).info(f"[Embedding] 发送请求: batch_size={len(batch)}, 首条长度={len(batch[0]) if batch else 0}")
        
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/embeddings",
                    json=data,
                    headers=headers,
                    timeout=300  # 批量请求需要更长时间
                )
                import logging
                logging.getLogger(__name__).info(f"[Embedding] 响应状态: {resp.status_code}")
                if resp.status_code == 429:
                    wait_seconds = 2 ** attempt
                    time.sleep(wait_seconds)
                    continue
                if resp.status_code != 200:
                    logging.getLogger(__name__).error(f"[Embedding] 非200响应: {resp.status_code}, body: {resp.text[:500]}")
                resp.raise_for_status()
                result = resp.json()
                items = result.get("data", [])
                if len(items) != len(batch):
                    raise RuntimeError(f"Dashscope embedding response mismatch: expected {len(batch)}, got {len(items)}")
                return [item["embedding"] for item in items]
            except requests.HTTPError as exc:
                last_error = exc
                import logging
                logging.getLogger(__name__).error(f"[Embedding] HTTP错误: {exc.response.status_code if exc.response else 'N/A'}, 响应: {exc.response.text[:500] if exc.response else 'N/A'}")
                if getattr(exc.response, "status_code", None) == 429 and attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.RequestException as exc:
                last_error = exc
                import logging
                logging.getLogger(__name__).error(f"[Embedding] 请求异常: {type(exc).__name__}: {str(exc)[:200]}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(f"[Embedding] 未知异常: {type(exc).__name__}: {str(exc)[:200]}")
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Dashscope embedding request failed")
    
    def embed_documents(self, texts: List[str], progress_callback=None) -> List[List[float]]:
        """Embed a list of texts"""
        if not texts:
            return []

        indexed_batches = [
            (start, texts[start:start + self.batch_size])
            for start in range(0, len(texts), self.batch_size)
        ]
        total_batches = len(indexed_batches)

        ordered_results: dict[int, List[List[float]]] = {}
        completed_batches = 0
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(indexed_batches))) as executor:
            future_map = {
                executor.submit(self._embed_batch, batch): start
                for start, batch in indexed_batches
            }
            for future in as_completed(future_map):
                start = future_map[future]
                ordered_results[start] = future.result()
                completed_batches += 1
                if progress_callback:
                    progress_callback(completed_batches, total_batches)

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
