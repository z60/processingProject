"""OpenAI 兼容向量模型客户端（/v1/embeddings，维度 1024）。"""

from __future__ import annotations

import time

import httpx

from app.util.config import settings
from app.util.log import get_logger

log = get_logger("embedding")


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    def __init__(self) -> None:
        conf = settings()
        self._base_url = conf.embedding_base_url
        self._model = conf.embedding_model
        self._dim = conf.embedding_dim
        self._batch = max(1, conf.embedding_batch)
        self._timeout = conf.embedding_timeout
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=float(self._timeout), write=10.0, pool=10.0)
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            batch = texts[start : start + self._batch]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload = {"input": batch, "model": self._model}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._client.post(f"{self._base_url}/embeddings", json=payload)
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
                vectors = [item["embedding"] for item in data]
                for vector in vectors:
                    if len(vector) != self._dim:
                        raise EmbeddingError(f"向量维度 {len(vector)} 与配置 {self._dim} 不一致")
                return vectors
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                log.warning("向量化失败（第 %s 次）：%s", attempt, exc)
                time.sleep(min(2 * attempt, 5))
        raise EmbeddingError(f"向量化失败：{last_error}") from last_error

    def close(self) -> None:
        self._client.close()
