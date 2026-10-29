"""审计事件。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    trace_id: str
    node: str
    event: str
    intent: str | None = None
    confidence: float | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    retrieval_sources: list[dict] = Field(default_factory=list)
    handoff_trigger: dict | None = None
    latency_ms: int = 0
    token_usage: dict = Field(default_factory=dict)
    prompt_version: str = ""
    created_at: str = ""
