"""验证器工具"""
import re
from typing import Optional


def is_valid_email(email: str) -> bool:
    """验证邮箱

    Args:
        email: 邮箱地址

    Returns:
        是否有效
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def is_valid_phone(phone: str) -> bool:
    """验证手机号（中国）

    Args:
        phone: 手机号

    Returns:
        是否有效
    """
    pattern = r"^1[3-9]\d{9}$"
    return bool(re.match(pattern, phone))


def is_valid_id_card(id_card: str) -> bool:
    """验证身份证号

    Args:
        id_card: 身份证号

    Returns:
        是否有效
    """
    pattern = r"^\d{17}[\dXx]$"
    if not re.match(pattern, id_card):
        return False

    # 校验位验证
    factors = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"

    total = sum(int(id_card[i]) * factors[i] for i in range(17))
    check_code = check_codes[total % 11]

    return check_code == id_card[17].upper()


def validate_file_type(
    filename: str,
    allowed_types: list[str],
) -> bool:
    """验证文件类型

    Args:
        filename: 文件名
        allowed_types: 允许的类型列表

    Returns:
        是否有效
    """
    ext = filename.split(".")[-1].lower()
    return ext in [t.lower().lstrip(".") for t in allowed_types]


def validate_file_size(
    size: int,
    max_size: int = 10 * 1024 * 1024,  # 默认 10MB
) -> bool:
    """验证文件大小

    Args:
        size: 文件大小（字节）
        max_size: 最大大小

    Returns:
        是否有效
    """
    return 0 < size <= max_size
