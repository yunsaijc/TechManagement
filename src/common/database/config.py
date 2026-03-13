"""
数据库配置

配置从环境变量读取，参考 .env.example
"""
from pydantic_settings import BaseSettings
from typing import Optional


class DatabaseSettings(BaseSettings):
    """数据库配置 - 从环境变量读取"""
    
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
    project_database: str = "kjjhxm_wlps"
    
    class Config:
        env_prefix = "DB_"


# 全局配置实例
db_settings = DatabaseSettings()
