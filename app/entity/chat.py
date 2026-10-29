"""对话/工单接口的出入参。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    user_id: str = "anonymous"
    session_id: str | None = None


class HandoffInfo(BaseModel):
    ticket_id: str
    trigger_type: str
    trigger_detail: dict = Field(default_factory=dict)
    draft_reply: str = ""


class ChatResponse(BaseModel):
    trace_id: str
    ticket_id: str = ""
    status: str  # ANSWERED | CLARIFY | HANDOFF
    reply: str
    intent: str = "unknown"
    confidence: float = 0.0
    risk_flag: bool = False
    citations: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    handoff: HandoffInfo | None = None
    latency_ms: int = 0
    cached: bool = False


class HandoffActionRequest(BaseModel):
    action: str = Field(pattern="^(CONFIRM|RETURN|EDIT)$")
    note: str = ""
    edited_reply: str = ""
    operator: str = "human_agent"


class HandoffActionResponse(BaseModel):
    ok: bool
    ticket_id: str
    status: str
    idempotent: bool = False
