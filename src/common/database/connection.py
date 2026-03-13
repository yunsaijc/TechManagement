"""
数据库连接管理
"""
import pymysql
import pyodbc
from typing import Optional
from src.common.database.config import db_settings


def get_reward_connection(db_name: str = "zjknew") -> pymysql.Connection:
    """
    获取奖励评审数据库连接 (MySQL)
    
    Args:
        db_name: 数据库名 (hbstanew, xmsbnew, zjknew)
    
    Returns:
        pymysql.Connection
    """
    return pymysql.connect(
        host=db_settings.reward_host,
        port=db_settings.reward_port,
        user=db_settings.reward_user,
        password=db_settings.reward_password,
        database=db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_project_connection() -> pyodbc.Connection:
    """
    获取项目评审数据库连接 (SQL Server)
    
    Returns:
        pyodbc.Connection
    """
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={db_settings.project_host},{db_settings.project_port};"
        f"DATABASE={db_settings.project_database};"
        f"UID={db_settings.project_user};PWD={db_settings.project_password};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def reward_execute(db_name: str, sql: str, params: tuple = None):
    """
    执行奖励评审数据库查询
    
    Args:
        db_name: 数据库名
        sql: SQL语句
        params: 参数
    
    Returns:
        查询结果列表
    """
    conn = get_reward_connection(db_name)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    finally:
        conn.close()


def project_execute(sql: str, params: tuple = None):
    """
    执行项目评审数据库查询
    
    Args:
        sql: SQL语句
        params: 参数
    
    Returns:
        查询结果列表
    """
    conn = get_project_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    finally:
        conn.close()
