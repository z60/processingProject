"""内存 TTL 存储：语义缓存、转人工工单缓存、连续失败计数。

Redis 地址未提供，先用进程内 TTL 实现同一组语义（F-02 / F-12 / F-14）；
接入 Redis 时只替换本类实现，其余代码不动。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.util.config import conf


class CacheRepository:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, payload = item
            if expires_at and expires_at < time.time():
                self._store.pop(key, None)
                return None
            return json.loads(payload)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = conf("settings")["cache"]["cache_ttl_seconds"] if ttl is None else ttl
        expires_at = time.time() + ttl if ttl else 0.0
        with self._lock:
            if len(self._store) > 5000:  # 顺手清理过期项，避免长驻进程无限增长
                now = time.time()
                for item_key, (item_expire, _) in list(self._store.items()):
                    if item_expire and item_expire < now:
                        self._store.pop(item_key, None)
            self._store[key] = (expires_at, json.dumps(value, ensure_ascii=False))

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            item = self._store.get(key)
            value = 1
            if item and (not item[0] or item[0] > time.time()):
                try:
                    value = int(json.loads(item[1])) + 1
                except (json.JSONDecodeError, ValueError):
                    value = 1
            expires_at = time.time() + ttl if ttl else 0.0
            self._store[key] = (expires_at, json.dumps(value))
            return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
