"""JSON 处理工具"""
import json
from typing import Any, TypeVar

T = TypeVar("T")


def safe_json_loads(
    data: str | bytes,
    default: Any = None,
) -> Any:
    """安全的 JSON 解析

    Args:
        data: JSON 字符串或字节
        default: 解析失败时的默认值

    Returns:
        解析后的对象或默认值
    """
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(
    obj: Any,
    default: str = "{}",
) -> str:
    """安全的 JSON 序列化

    Args:
        obj: 要序列化的对象
        default: 序列化失败时的默认值

    Returns:
        JSON 字符串或默认值
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


def parse_json(
    data: str,
    model: type[T],
) -> T | None:
    """解析 JSON 到模型

    Args:
        data: JSON 字符串
        model: Pydantic 模型类

    Returns:
        模型实例或 None
    """
    try:
        obj = json.loads(data)
        return model(**obj)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
