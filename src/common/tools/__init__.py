"""工具函数模块

提供系统中通用的工具函数。
"""
from src.common.tools.datetime import format_duration, from_iso, now, to_iso
from src.common.tools.files import (
    calculate_file_hash,
    ensure_dir,
    generate_unique_filename,
    get_file_extension,
    get_file_size_display,
    get_mime_type,
)
from src.common.tools.json import parse_json, safe_json_dumps, safe_json_loads
from src.common.tools.logger import get_logger
from src.common.tools.validators import (
    is_valid_email,
    is_valid_id_card,
    is_valid_phone,
    validate_file_size,
    validate_file_type,
)

__all__ = [
    # JSON
    "safe_json_loads",
    "safe_json_dumps",
    "parse_json",
    # Datetime
    "now",
    "to_iso",
    "from_iso",
    "format_duration",
    # Validators
    "is_valid_email",
    "is_valid_phone",
    "is_valid_id_card",
    "validate_file_type",
    "validate_file_size",
    # Files
    "get_file_extension",
    "get_mime_type",
    "calculate_file_hash",
    "ensure_dir",
    "generate_unique_filename",
    "get_file_size_display",
    # Logger
    "get_logger",
]
