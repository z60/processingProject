"""知识库文档与分块。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeDoc(BaseModel):
    doc_id: str
    title: str
    category: str
    source: str
    version: str = ""
    text: str


class KnowledgeChunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    category: str
    source: str
    version: str = ""
    chunk_index: int = 0
    text: str


class QdrantHit(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    source: str
    text: str
    score: float
    payload: dict = Field(default_factory=dict)
