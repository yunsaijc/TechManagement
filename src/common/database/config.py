"""
数据库配置

配置从环境变量读取，参考 .env.example
"""
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """数据库配置 - 从环境变量读取"""

    # 奖励评审数据库 (MySQL)
    reward_host: str = "192.168.0.211"
    reward_port: int = 3306
    reward_user: str = "hbkjjl"
    reward_password: str = "hbkjjl"

    # 项目评审数据库 (SQL Server)
    project_host: str = ""
    project_port: int = 1433
    project_user: str = ""
    project_password: str = ""
    project_database: str = ""

    # 科技计划合同库 (SQL Server)
    kjjh_host: str = "192.168.0.190"
    kjjh_port: int = 1433
    kjjh_user: str = "sa"
    kjjh_password: str = "tdkx"
    kjjh_database: str = "kjjhxm"

    class Config:
        env_prefix = "DB_"


# 全局配置实例
db_settings = DatabaseSettings()
