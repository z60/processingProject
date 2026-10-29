"""知识文档分块与 Qdrant point 映射。"""

from __future__ import annotations

import re
import uuid

from app.entity.knowledge import KnowledgeChunk, KnowledgeDoc

_SENTENCE_RE = re.compile(r"[^。！？\n]+[。！？]?")


def split_text(text: str, chunk_size: int) -> list[str]:
    """按句切分并合并到接近 chunk_size 的分块；空文本返回空列表。"""
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]
    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) > chunk_size:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        chunks.append(buffer)
    return chunks


def chunk_document(doc: KnowledgeDoc, chunk_size: int = 180) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for index, text in enumerate(split_text(doc.text, chunk_size)):
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{doc.doc_id}-{index + 1}",
                doc_id=doc.doc_id,
                title=doc.title,
                category=doc.category,
                source=doc.source,
                version=doc.version,
                chunk_index=index,
                text=text,
            )
        )
    return chunks


def chunk_payload(chunk: KnowledgeChunk) -> dict:
    """Qdrant payload：检索后直接用于引用展示。"""
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "category": chunk.category,
        "source": chunk.source,
        "version": chunk.version,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
    }


def point_id(chunk: KnowledgeChunk) -> str:
    """确定性 UUID：重复初始化幂等（Qdrant 只接受 UUID/整数 ID）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"knowledge::{chunk.chunk_id}"))
