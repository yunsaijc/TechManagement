"""文件相关模型"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """文件类型"""
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    TXT = "txt"


class FileMeta(BaseModel):
    """文件元数据"""
    id: str = Field(..., description="文件唯一标识")
    filename: str = Field(..., description="文件名")
    file_type: FileType = Field(..., description="文件类型")
    size: int = Field(..., description="文件大小（字节）")
    mime_type: str = Field(..., description="MIME类型")
    created_at: datetime = Field(default_factory=datetime.now)
    storage_path: str = Field(..., description="存储路径")


class UploadFile(BaseModel):
    """上传文件"""
    file: bytes
    filename: str
    content_type: str
