"""
数据库配置

配置从环境变量读取，默认同时加载项目根目录 ``.env``。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class DatabaseSettings(BaseSettings):
    """数据库配置 - 从环境变量读取"""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 奖励评审数据库 (MySQL)
    reward_host: str = ""
    reward_port: int = 3306
    reward_user: str = ""
    reward_password: str = ""
    
    # 项目评审数据库 (SQL Server)
    project_host: str = ""
    project_port: int = 1433
    project_user: str = ""
    project_password: str = ""
    project_database: str = ""
    
# 全局配置实例
db_settings = DatabaseSettings()
