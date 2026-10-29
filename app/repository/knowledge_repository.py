"""知识库检索仓储（Embedding + Qdrant）。"""

from __future__ import annotations

from app.client.embedding_client import EmbeddingClient
from app.client.qdrant_client import QdrantClient, QdrantError
from app.entity.knowledge import KnowledgeChunk, KnowledgeDoc, QdrantHit
from app.mapper import knowledge_mapper
from app.util.config import conf
from app.util.log import get_logger

log = get_logger("knowledge_repository")


class KnowledgeRepository:
    def __init__(self) -> None:
        self._qdrant = QdrantClient()
        self._embedding = EmbeddingClient()

    def ensure_collection(self, recreate: bool = False) -> None:
        self._qdrant.ensure_collection(recreate=recreate)

    def index_documents(self, docs: list[KnowledgeDoc]) -> int:
        chunk_size = conf("settings")["knowledge"]["chunk_size"]
        chunks: list[KnowledgeChunk] = []
        for doc in docs:
            chunks.extend(knowledge_mapper.chunk_document(doc, chunk_size))
        if not chunks:
            return 0
        vectors = self._embedding.embed([chunk.text for chunk in chunks])
        points = [
            {
                "id": knowledge_mapper.point_id(chunk),
                "vector": vector,
                "payload": knowledge_mapper.chunk_payload(chunk),
            }
            for chunk, vector in zip(chunks, vectors)
        ]
        self._qdrant.upsert(points)
        log.info("已写入 %s 个知识分块", len(points))
        return len(points)

    def search(self, query: str, top_k: int | None = None, min_score: float | None = None) -> list[QdrantHit]:
        settings_conf = conf("settings")["knowledge"]
        top_k = top_k or settings_conf["top_k"]
        min_score = settings_conf["min_score"] if min_score is None else min_score
        vector = self._embedding.embed_one(query)
        rows = self._qdrant.search(vector, top_k=top_k, score_threshold=min_score)
        return [
            QdrantHit(
                chunk_id=row["chunk_id"],
                doc_id=row.get("doc_id", ""),
                title=row.get("title", ""),
                source=row.get("source", ""),
                text=row.get("text", ""),
                score=row["score"],
                payload=row,
            )
            for row in rows
        ]

    def count(self) -> int:
        return self._qdrant.count()

    def ping(self) -> bool:
        try:
            self._qdrant.collection_exists()
            return True
        except QdrantError:
            return False
