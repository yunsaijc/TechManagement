# 🌍 环境配置

## Python 环境

- **Python 版本**: >= 3.12
- **包管理**: uv

## 核心依赖

```toml
# pyproject.toml
dependencies = [
    # LangChain 生态
    "langchain>=1.2.12",
    "langchain-core>=1.2.0",
    "langchain-openai>=1.2.0",
    "langchain-community>=1.2.0",
    
    # LLM
    "openai>=1.12.0",
    "anthropic>=0.18.0",
    
    # 文档处理
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "paddleocr>=2.7.0",
    "paddlepaddle>=2.6.0",
    
    # 视觉模型
    "transformers>=5.3.0",
    "torch>=2.2.0",
    "torchvision>=0.17.0",
    "ultralytics>=8.1.0",  # YOLO
    "groundingdino-cli>=0.1.0",
    
    # Web 框架
    "fastapi>=0.110.0",
    "uvicorn>=0.27.0",
    "langserve>=1.0.0",
    
    # 数据验证
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    
    # 其他
    "python-multipart>=0.0.9",
    "aiofiles>=23.2.1",
    "python-dotenv>=1.0.0",
]
```

## 环境变量

```bash
# .env

# LLM 配置
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-xxxxx

# 多模态模型（可选）
QWWEN_API_KEY=xxxxx
AZURE_OPENAI_API_KEY=xxxxx
AZURE_OPENAI_ENDPOINT=https://xxxxx.openai.azure.com/

# 文件存储
UPLOAD_DIR=/data/uploads
TEMP_DIR=/data/temp

# 日志
LOG_LEVEL=INFO
```

## 安装

```bash
cd tech
uv sync
```

## 开发依赖

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.3.0",
    "mypy>=1.8.0",
    "pre-commit>=3.6.0",
]
```

## Docker 环境

```dockerfile
# Dockerfile
FROM python:3.12-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync --no-dev

COPY . .
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
