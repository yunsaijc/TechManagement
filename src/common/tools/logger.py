"""日志工具"""
import logging
import sys
from typing import Optional


def get_logger(
    name: str,
    level: str = "INFO",
) -> logging.Logger:
    """获取日志记录器

    Args:
        name: logger 名称
        level: 日志级别

    Returns:
        Logger 实例
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, level.upper()))
    return logger
