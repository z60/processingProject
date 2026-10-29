"""时间工具。"""

from __future__ import annotations

from datetime import datetime


def now_str() -> str:
    """MySQL DATETIME 兼容格式。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
