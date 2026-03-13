"""类型别名"""
from typing import Any, Callable, TypeAlias

from src.common.models.review import CheckResult

# JSON 类型
JSON: TypeAlias = dict | list | str | int | float | bool | None

# 图像类型：文件路径或二进制
ImageData: TypeAlias = bytes | str

# 检查器类型
CheckFunction: TypeAlias = Callable[..., CheckResult]
