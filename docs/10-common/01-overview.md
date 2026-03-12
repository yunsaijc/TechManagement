# 🔧 通用组件概述

## 定位

Common Layer（通用组件层）是整个系统的基础，为所有服务提供共享能力。

## 与服务层的关系

```
┌─────────────────────────────────────────────────────────────┐
│                      Service Layer                          │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│   │  review  │  │ project  │  │  award   │  │  expert  │ │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
└────────┼─────────────┼─────────────┼─────────────┼───────┘
         │             │             │             │
         └─────────────┴──────┬──────┴─────────────┘
                              │
              ┌───────────────▼───────────────┐
              │         Common Layer          │
              │                               │
              │   models  llm  file  vision   │
              │                               │
              └───────────────────────────────┘
```

## 模块说明

| 模块 | 职责 | 依赖方 |
|------|------|--------|
| **models** | 通用数据模型定义 | 所有服务 |
| **llm** | LLM 统一封装、多模型切换 | Agent、规则 |
| **file_handler** | 文件解析、格式转换 | 文档处理相关服务 |
| **vision** | 目标检测、图像分析 | 形式审查、文档解析 |
| **tools** | 通用工具函数 | 所有模块 |

## 设计原则

### 1. 高内聚、低耦合

- 每个模块专注单一职责
- 模块间通过接口通信
- 避免循环依赖

### 2. 可复用

- 通用逻辑抽取到 Common Layer
- 配置化支持多场景
- 良好的扩展接口

### 3. 可替换

- 使用抽象基类
- 依赖注入
- 便于切换实现（如换 LLM Provider）

## 使用方式

```python
# 方式 1: 直接导入
from src.common.models import FileMeta, ReviewResult
from src.common.llm import get_llm_client

# 方式 2: 依赖注入
from src.services.base import BaseService
from src.common.llm import BaseLLM

class MyService(BaseService):
    def __init__(self, llm: BaseLLM):
        self.llm = llm
```

## 扩展 Common Layer

### 新增模块

1. 在 `src/common/` 下创建目录
2. 定义模块接口（抽象类）
3. 实现具体功能
4. 在 `__init__.py` 导出

### 示例：新增缓存模块

```python
# src/common/cache/__init__.py
from src.common.cache.base import BaseCache
from src.common.cache.memory import MemoryCache

__all__ = ["BaseCache", "MemoryCache"]

# src/common/cache/base.py
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar("T")

class BaseCache(ABC, Generic[T]):
    @abstractmethod
    async def get(self, key: str) -> T | None:
        pass
    
    @abstractmethod
    async def set(self, key: str, value: T, ttl: int = 3600):
        pass
```

## 下游文档

- [通用数据模型 →](02-models.md)
- [LLM 统一封装 →](03-llm.md)
- [文件处理 →](04-file-handler.md)
- [视觉能力 →](05-vision.md)
- [工具函数 →](06-tools.md)
