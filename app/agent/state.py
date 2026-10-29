"""Agent 状态定义（LangGraph 只保留 schema 内字段）。"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    trace_id: str
    session_id: str
    user_id: str
    text: str
    started_at: float
    intent: str
    confidence: float
    risk_flag: bool
    slots: dict[str, Any]
    clarify_rounds: int
    expert: str
    draft: str
    summary: str
    citations: list[dict]
    tool_calls: list[dict]
    tokens: dict
    handoff_trigger: dict | None
    handoff: dict | None
    status: str
    reply: str
    audit_sink: str
    events: list[dict]


def new_state(*, trace_id: str, session_id: str, user_id: str, text: str, started_at: float = 0.0) -> AgentState:
    return AgentState(
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        text=text,
        started_at=started_at,
        intent="unknown",
        confidence=0.0,
        risk_flag=False,
        slots={},
        clarify_rounds=0,
        expert="",
        draft="",
        summary="",
        citations=[],
        tool_calls=[],
        tokens={"prompt": 0, "completion": 0},
        handoff_trigger=None,
        handoff=None,
        status="",
        reply="",
        audit_sink="",
        events=[],
    )
