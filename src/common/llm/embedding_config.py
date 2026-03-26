"""
Embedding 向量化模型配置

配置从环境变量读取
"""
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 加载 .env 文件（从项目根目录）
_env_path = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(_env_path)


class EmbeddingConfig(BaseSettings):
    """Embedding 配置 - 从环境变量读取"""
    
    # 提供商: openai, qwen, minimax, local
    provider: str = "openai"
    # 模型名称
    model: str = "text-embedding-3-small"
    # API Key
    api_key: str = ""
    # 自定义端点
    base_url: str = ""
    # 向量维度
    dimension: int = 1536

    class Config:
        env_prefix = "EMBEDDING_"


# 全局配置实例
embedding_config = EmbeddingConfig()
