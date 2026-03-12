# 🔨 工具函数

## 概述

提供系统中通用的工具函数。

## 模块结构

```
src/common/tools/
├── __init__.py
├── json.py       # JSON 处理
├── datetime.py   # 日期时间
├── validators.py # 验证器
├── files.py      # 文件工具
└── logger.py    # 日志工具
```

## JSON 处理

```python
# src/common/tools/json.py
import json
from typing import Any, TypeVar, Generic

T = TypeVar("T")

def safe_json_loads(
    data: str | bytes,
    default: Any = None
) -> Any:
    """安全的 JSON 解析"""
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default

def safe_json_dumps(
    obj: Any,
    default: str = "{}"
) -> str:
    """安全的 JSON 序列化"""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return default

def parse_json(
    data: str,
    model: type[T]
) -> T | None:
    """解析 JSON 到模型"""
    try:
        obj = json.loads(data)
        return model(**obj)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
```

## 日期时间

```python
# src/common/tools/datetime.py
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
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"

def parse_chinese_datetime(date_str: str) -> datetime:
    """解析中文日期格式"""
    import re
    
    patterns = [
        (r"(\d{4})年(\d{1,2})月(\d{1,2})日", "%Y年%m月%d日"),
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y-%m-%d"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y/%m/%d"),
    ]
    
    for pattern, _ in patterns:
        match = re.match(pattern, date_str)
        if match:
            fmt = next(p for p, f in patterns if p == pattern)
            return datetime.strptime(date_str, fmt)
    
    raise ValueError(f"无法解析日期: {date_str}")
```

## 验证器

```python
# src/common/tools/validators.py
import re
from typing import Optional

def is_valid_email(email: str) -> bool:
    """验证邮箱"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def is_valid_phone(phone: str) -> bool:
    """验证手机号（中国）"""
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))

def is_valid_id_card(id_card: str) -> bool:
    """验证身份证号"""
    pattern = r'^\d{17}[\dXx]$'
    if not re.match(pattern, id_card):
        return False
    
    # 校验位验证
    factors = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = '10X98765432'
    
    total = sum(int(id_card[i]) * factors[i] for i in range(17))
    check_code = check_codes[total % 11]
    
    return check_code == id_card[17].upper()

def validate_file_type(
    filename: str,
    allowed_types: list[str]
) -> bool:
    """验证文件类型"""
    ext = filename.split('.')[-1].lower()
    return ext in [t.lower().lstrip('.') for t in allowed_types]

def validate_file_size(
    size: int,
    max_size: int = 10 * 1024 * 1024  # 默认 10MB
) -> bool:
    """验证文件大小"""
    return 0 < size <= max_size
```

## 文件工具

```python
# src/common/tools/files.py
import os
import hashlib
import mimetypes
from pathlib import Path
from typing import Optional

def get_file_extension(filename: str) -> str:
    """获取文件扩展名"""
    return Path(filename).suffix.lstrip('.').lower()

def get_mime_type(filename: str) -> Optional[str]:
    """获取 MIME 类型"""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type

def calculate_file_hash(
    file_data: bytes,
    algorithm: str = "md5"
) -> str:
    """计算文件哈希"""
    hasher = hashlib.new(algorithm)
    hasher.update(file_data)
    return hasher.hexdigest()

def ensure_dir(path: str) -> None:
    """确保目录存在"""
    Path(path).mkdir(parents=True, exist_ok=True)

def generate_unique_filename(
    original_name: str,
    prefix: str = ""
) -> str:
    """生成唯一文件名"""
    import uuid
    from datetime import datetime
    
    ext = get_file_extension(original_name)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    
    parts = [prefix, timestamp, unique_id]
    filename = "_".join(p for p in parts if p)
    
    return f"{filename}.{ext}" if ext else filename

def get_file_size_display(size_bytes: int) -> str:
    """人类可读的文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"
```

## 日志工具

```python
# src/common/tools/logger.py
import logging
import sys
from typing import Optional

def get_logger(
    name: str,
    level: str = "INFO"
) -> logging.Logger:
    """获取日志记录器"""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    logger.setLevel(getattr(logging, level.upper()))
    return logger

def log_function_call(logger: logging.Logger):
    """日志函数调用装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            logger.debug(f"调用 {func.__name__}")
            try:
                result = await func(*args, **kwargs)
                logger.debug(f"{func.__name__} 完成")
                return result
            except Exception as e:
                logger.error(f"{func.__name__} 错误: {e}")
                raise
        return wrapper
    return decorator
```

## 使用方式

```python
from src.common.tools import (
    safe_json_loads,
    is_valid_email,
    validate_file_type,
    calculate_file_hash,
    get_logger,
    format_duration
)

# JSON 处理
data = safe_json_loads('{"key": "value"}', default={})

# 验证
if not is_valid_email(email):
    raise ValueError("无效邮箱")

# 文件
file_hash = calculate_file_hash(file_data)

# 日志
logger = get_logger(__name__)
logger.info("处理完成", extra={"duration": format_duration(1.5)})
```
