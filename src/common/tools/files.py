"""文件工具"""
import hashlib
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_file_extension(filename: str) -> str:
    """获取文件扩展名

    Args:
        filename: 文件名

    Returns:
        扩展名（不含点）
    """
    return Path(filename).suffix.lstrip(".").lower()


def get_mime_type(filename: str) -> Optional[str]:
    """获取 MIME 类型

    Args:
        filename: 文件名

    Returns:
        MIME 类型或 None
    """
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type


def calculate_file_hash(
    file_data: bytes,
    algorithm: str = "md5",
) -> str:
    """计算文件哈希

    Args:
        file_data: 文件数据
        algorithm: 哈希算法（md5/sha1/sha256）

    Returns:
        哈希值
    """
    hasher = hashlib.new(algorithm)
    hasher.update(file_data)
    return hasher.hexdigest()


def ensure_dir(path: str) -> None:
    """确保目录存在

    Args:
        path: 目录路径
    """
    Path(path).mkdir(parents=True, exist_ok=True)


def generate_unique_filename(
    original_name: str,
    prefix: str = "",
) -> str:
    """生成唯一文件名

    Args:
        original_name: 原始文件名
        prefix: 前缀

    Returns:
        唯一文件名
    """
    ext = get_file_extension(original_name)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]

    parts = [prefix, timestamp, unique_id]
    filename = "_".join(p for p in parts if p)

    return f"{filename}.{ext}" if ext else filename


def get_file_size_display(size_bytes: int) -> str:
    """人类可读的文件大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化的大小字符串
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"
