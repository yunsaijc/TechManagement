"""服务配置"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class ServiceConfig(BaseModel):
    """服务配置基类"""

    name: str = Field(..., description="服务名称")
    version: str = Field(default="1.0.0", description="服务版本")
    description: Optional[str] = Field(default=None, description="服务描述")
    metadata: dict[str, Any] = Field(default_factory=dict, description="其他元数据")
