"""初始化 Qdrant：建集合（dim=1024, Cosine）并把知识库文档向量化入库。

用法：
    python -m app.script.init_qdrant             # 增量写入（确定性 ID，幂等）
    python -m app.script.init_qdrant --recreate  # 先删集合再重建
    python -m app.script.init_qdrant --dry-run   # 只统计文档与分块，不写库
"""

from __future__ import annotations

import argparse
import sys

from app.entity.knowledge import KnowledgeDoc
from app.mapper.knowledge_mapper import chunk_document
from app.repository.knowledge_repository import KnowledgeRepository
from app.util.config import conf, read_jsonl, settings
from app.util.log import get_logger

log = get_logger("init_qdrant")


def load_docs() -> list[KnowledgeDoc]:
    return [KnowledgeDoc(**item) for item in read_jsonl(settings().seed_dir / "knowledge.jsonl")]


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 Qdrant 知识与向量")
    parser.add_argument("--recreate", action="store_true", help="删除并重建集合")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不连库")
    args = parser.parse_args()

    docs = load_docs()
    chunk_size = conf("settings")["knowledge"]["chunk_size"]
    planned = sum(len(chunk_document(doc, chunk_size)) for doc in docs)
    if args.dry_run:
        print(f"文档 {len(docs)} 篇，预计分块 {planned} 个，向量维度 {settings().qdrant_dim}")
        return 0

    repo = KnowledgeRepository()
    repo.ensure_collection(recreate=args.recreate)
    written = repo.index_documents(docs)
    total = repo.count()
    print(f"已写入分块 {written} 个，集合内当前共 {total} 个向量（维度 {settings().qdrant_dim}，集合 {settings().qdrant_collection}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
