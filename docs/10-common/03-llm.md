# 🤖 LLM 统一封装

## 概述

基于 LangChain 提供统一的 LLM 调用能力，支持 OpenAI、Claude、Qwen 等多种模型。

## 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                      Service Layer                       │
│                  (Agent / Rules / Tools)                 │
└────────────────────────────┬────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│                    LangChain LCEL                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │              ChatOpenAI / ChatAnthropic          │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│                   LLM Providers                          │
│        OpenAI    Claude   Qwen   Azure   本地模型       │
└─────────────────────────────────────────────────────────┘
```

## 核心实现

### 配置

```python
# src/common/llm/config.py
from pydantic_settings import BaseSettings
from typing import Optional


class LLMConfig(BaseSettings):
    """LLM 配置"""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096

    class Config:
        env_prefix = "LLM_"
```

### 获取 LLM 客户端

```python
# src/common/llm/__init__.py
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic


def get_llm_client(
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    **kwargs
):
    """获取 LLM 客户端

    Args:
        provider: 提供商 "openai" / "anthropic" / "qwen"
        model: 模型名称
        api_key: API Key
        base_url: 自定义端点
        temperature: 温度
        max_tokens: 最大 token 数

    Returns:
        LangChain ChatModel 实例
    """
    if provider == "openai":
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    elif provider == "anthropic":
        return ChatAnthropic(
            model=model or "claude-3-5-sonnet-20241022",
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    elif provider == "qwen":
        return ChatOpenAI(
            model=model or "qwen-vl-max",
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


# 导出
__all__ = ["get_llm_client", "LLMConfig"]
```

## 使用方式

### 1. 直接使用

```python
from src.common.llm import get_llm_client

# 获取客户端
llm = get_llm_client(provider="openai", model="gpt-4o")

# 同步调用
response = llm.invoke("你好，请介绍一下自己")
print(response.content)

# 异步调用
response = await llm.ainvoke("你好，请介绍一下自己")
```

### 2. LCEL 链式调用

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 构建链
prompt = ChatPromptTemplate.from_template("请用一句话介绍{topic}")
chain = prompt | llm | StrOutputParser()

# 调用
result = chain.invoke({"topic": "人工智能"})
```

### 3. 多模态（带图像）

```python
from langchain_core.messages import HumanMessage

# 带图像的消息
messages = [
    HumanMessage(
        content=[
            {"type": "text", "text": "描述这张图片"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]
    )
]

response = llm.invoke(messages)
```

### 4. 流式输出

```python
# 流式调用
for chunk in llm.stream("写一首诗"):
    print(chunk.content, end="", flush=True)
```

## LangChain 优势

| 特性 | 说明 |
|------|------|
| **Runnable 接口** | 统一调用方式 `.invoke()` / `.stream()` / `.batch()` |
| **LCEL** | 声明式链式组合 `prompt \| model \| parser` |
| **内置工具** | Tool、Agent、Memory 等组件 |
| **社区支持** | 丰富文档和示例 |
| **多模型支持** | OpenAI、Claude、Qwen 等 |

## 配置示例

### 环境变量

```bash
# .env
OPENAI_API_KEY=sk-xxxxx
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7
```

### 代码配置

```python
from src.common.llm import LLMConfig

config = LLMConfig()
llm = get_llm_client(
    provider=config.provider,
    model=config.model,
    api_key=config.api_key,
    temperature=config.temperature
)
```

## 扩展新的 Provider

LangChain 内置支持多种模型，只需添加 provider 判断：

```python
# 新增 provider
elif provider == "azure":
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        model=model,
        api_key=api_key,
        azure_endpoint=base_url,
        **kwargs
    )
```
