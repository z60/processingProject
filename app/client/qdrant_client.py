"""Qdrant REST 客户端（不引入额外 SDK，HTTP 接口足够）。"""

from __future__ import annotations

import time

from app.util.config import settings
from app.util.log import get_logger

import httpx

log = get_logger("qdrant")


class QdrantError(RuntimeError):
    pass


class QdrantClient:
    def __init__(self) -> None:
        conf = settings()
        self._url = conf.qdrant_url
        self._collection = conf.qdrant_collection
        self._dim = conf.qdrant_dim
        self._timeout = conf.qdrant_timeout
        self._client = httpx.Client(
            base_url=self._url,
            timeout=httpx.Timeout(connect=8.0, read=float(self._timeout), write=10.0, pool=8.0),
        )

    # --- 基础请求 ---
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.request(method, path, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("Qdrant 请求失败（第 %s 次）%s %s: %s", attempt, method, path, exc)
                time.sleep(attempt)
                continue
            if response.status_code >= 400:
                raise QdrantError(f"Qdrant {method} {path} -> {response.status_code}: {response.text[:200]}")
            return response.json()
        raise QdrantError(f"Qdrant 请求失败 {method} {path}: {last_error}") from last_error

    # --- 集合管理 ---
    def collection_exists(self) -> bool:
        try:
            response = self._client.get(f"/collections/{self._collection}")
        except httpx.HTTPError as exc:
            raise QdrantError(f"Qdrant 连接失败: {exc}") from exc
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise QdrantError(f"Qdrant 查询集合失败: {response.status_code}")
        return True

    def ensure_collection(self, recreate: bool = False) -> None:
        if recreate:
            response = self._client.delete(f"/collections/{self._collection}")
            if response.status_code >= 400 and response.status_code != 404:
                raise QdrantError(f"Qdrant 删除集合失败: {response.status_code}")
        if self.collection_exists():
            info = self._request("GET", f"/collections/{self._collection}")
            size = info["result"]["config"]["params"]["vectors"]["size"]
            if size != self._dim:
                raise QdrantError(f"集合维度不一致：现有 {size}，期望 {self._dim}")
            return
        self._request(
            "PUT",
            f"/collections/{self._collection}",
            {"vectors": {"size": self._dim, "distance": "Cosine"}},
        )
        log.info("已创建 Qdrant 集合 %s（dim=%s, Cosine）", self._collection, self._dim)

    # --- 数据 ---
    def upsert(self, points: list[dict]) -> None:
        self._request(
            "PUT",
            f"/collections/{self._collection}/points?wait=true",
            {"points": points},
        )

    def count(self) -> int:
        info = self._request("POST", f"/collections/{self._collection}/points/count", {"exact": True})
        return int(info["result"]["count"])

    def search(self, vector: list[float], top_k: int, score_threshold: float | None = None) -> list[dict]:
        payload: dict = {
            "query": vector,
            "limit": top_k,
            "with_payload": True,
        }
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        response = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.post(f"/collections/{self._collection}/points/query", json=payload)
                break
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("Qdrant 检索失败（第 %s 次）：%s", attempt, exc)
                time.sleep(attempt)
        if response is None:
            raise QdrantError(f"Qdrant 检索失败: {last_error}") from last_error
        if response.status_code == 404:
            # 兼容旧版本 Qdrant（<1.10）的检索接口
            response = self._client.post(f"/collections/{self._collection}/points/search", json=payload)
        if response.status_code >= 400:
            raise QdrantError(f"Qdrant 检索失败: {response.status_code} {response.text[:200]}")
        result = response.json()["result"]
        points = result["points"] if isinstance(result, dict) else result
        return [
            {
                "chunk_id": str(point["id"]),
                "score": float(point["score"]),
                **(point.get("payload") or {}),
            }
            for point in points
        ]

    def close(self) -> None:
        self._client.close()
