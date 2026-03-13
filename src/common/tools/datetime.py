"""日期时间工具"""
import re
from datetime import datetime, timezone, timedelta
from typing import Optional


def now() -> datetime:
    """获取当前时间（UTC）"""
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """转换为 ISO 格式"""
    return dt.isoformat()


def from_iso(iso_str: str) -> datetime:
    """从 ISO 格式解析"""
    return datetime.fromisoformat(iso_str)


def format_duration(seconds: float) -> str:
    """格式化时长

    Args:
        seconds: 秒数

    Returns:
        格式化后的字符串，如 "1.5分钟"
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"


def parse_chinese_datetime(date_str: str) -> datetime:
    """解析中文日期格式

    Args:
        date_str: 日期字符串

    Returns:
        datetime 对象

    Raises:
        ValueError: 无法解析
    """
    patterns = [
        (r"(\d{4})年(\d{1,2})月(\d{1,2})日", "%Y年%m月%d日"),
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y-%m-%d"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y/%m/%d"),
    ]

    for pattern, fmt in patterns:
        match = re.match(pattern, date_str)
        if match:
            return datetime.strptime(date_str, fmt)

    raise ValueError(f"无法解析日期: {date_str}")
