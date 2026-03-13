"""API 响应模型"""
from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field


class ResponseStatus(str, Enum):
    """响应状态"""
    SUCCESS = "success"
    ERROR = "error"


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """API 响应"""
    status: ResponseStatus
    data: Optional[T] = None
    message: str = ""
    code: int = 200


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
    has_next: bool
