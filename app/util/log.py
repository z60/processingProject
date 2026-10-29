"""日志初始化（控制台或文件；MCP server 必须写文件，避免污染 stdio 协议）。"""

from __future__ import annotations

import logging
import sys

_configured = False


def setup_logging(level: str = "INFO", stream: str = "stdout", path: str | None = None) -> None:
    """stream: stdout | stderr | file（file 需提供 path）。"""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if stream == "file" and path:
        handler: logging.Handler = logging.FileHandler(path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr if stream == "stderr" else sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        setup_logging()
        _configured = True
    return logging.getLogger(f"app.{name}")
