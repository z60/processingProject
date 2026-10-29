"""意图路由结果与检索命中。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    intent: str = "unknown"
    confidence: float = 0.0
    risk_flag: bool = False
    slots: dict = Field(default_factory=dict)
    reason: str = ""


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    source: str
    text: str
    score: float
