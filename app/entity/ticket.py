"""持久化实体：工单、转人工工单、订单。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TicketRecord(BaseModel):
    ticket_id: str
    session_id: str
    user_id: str
    trace_id: str
    intent: str = "unknown"
    confidence: float = 0.0
    risk_flag: bool = False
    raw_input: str = ""
    summary: str = ""
    draft_reply: str = ""
    status: str = "ANSWERED"
    handoff_reason: str | None = None
    created_at: str = ""


class HandoffRecord(BaseModel):
    ticket_id: str
    trigger_type: str
    trigger_detail: dict = Field(default_factory=dict)
    conversation_snapshot: list[dict] = Field(default_factory=list)
    slots: dict = Field(default_factory=dict)
    draft_reply: str = ""
    status: str = "OPEN"
    handler_action: str | None = None
    handler_note: str | None = None
    created_at: str = ""
    handled_at: str | None = None


class OrderRecord(BaseModel):
    order_no: str
    user_id: str
    status: str
    amount: float = 0.0
    refundable_amount: float = 0.0
    logistics_no: str = ""
    product: str = ""
    created_at: str = ""
    updated_at: str = ""
