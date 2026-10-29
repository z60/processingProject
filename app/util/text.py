"""文本归一化与幂等指纹。"""

from __future__ import annotations

import hashlib
import re

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:（）()【】\[\]\"'“”‘’]")


def normalize(text: str) -> str:
    """去空白与中英文标点，用于内容指纹。"""
    return _PUNCT_RE.sub("", _SPACE_RE.sub(" ", text or "")).lower()


def fingerprint(user_id: str, text: str) -> str:
    """缓存/幂等键：用户 ID + 归一化内容。"""
    raw = f"{user_id or 'anonymous'}::{normalize(text)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:32]


def digest(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]
