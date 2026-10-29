"""audit_logs / regression_cases 的 SQL 与行映射。"""

from __future__ import annotations

import json

from app.entity.audit import AuditEvent
from app.entity.eval import RegressionCase
from app.util.time import now_str

AUDIT_INSERT = """
INSERT INTO audit_logs
    (trace_id, node, event, intent, confidence, tool_calls, retrieval_sources,
     handoff_trigger, latency_ms, token_usage, prompt_version, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

AUDIT_BY_TRACE = "SELECT * FROM audit_logs WHERE trace_id = %s ORDER BY id ASC"

CASE_UPSERT = """
INSERT INTO regression_cases
    (case_id, category, input_text, expected_status, expected_intent, assertions, turns, source_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    category = VALUES(category), input_text = VALUES(input_text),
    expected_status = VALUES(expected_status), expected_intent = VALUES(expected_intent),
    assertions = VALUES(assertions), turns = VALUES(turns), source_version = VALUES(source_version)
"""


def audit_params(event: AuditEvent) -> tuple:
    return (
        event.trace_id,
        event.node,
        event.event,
        event.intent,
        event.confidence,
        json.dumps(event.tool_calls, ensure_ascii=False),
        json.dumps(event.retrieval_sources, ensure_ascii=False),
        json.dumps(event.handoff_trigger, ensure_ascii=False) if event.handoff_trigger else None,
        event.latency_ms,
        json.dumps(event.token_usage, ensure_ascii=False),
        event.prompt_version,
        event.created_at or now_str(),
    )


def _load_json(value, default):
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def audit_from_row(row: dict) -> AuditEvent:
    return AuditEvent(
        trace_id=row["trace_id"],
        node=row["node"],
        event=row["event"],
        intent=row.get("intent"),
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        tool_calls=_load_json(row.get("tool_calls"), []),
        retrieval_sources=_load_json(row.get("retrieval_sources"), []),
        handoff_trigger=_load_json(row.get("handoff_trigger"), None),
        latency_ms=int(row.get("latency_ms") or 0),
        token_usage=_load_json(row.get("token_usage"), {}),
        prompt_version=row.get("prompt_version") or "",
        created_at=str(row["created_at"]),
    )


def case_params(case: RegressionCase) -> tuple:
    return (
        case.case_id,
        case.category,
        case.input_text,
        case.expected_status,
        case.expected_intent,
        json.dumps(case.assertions, ensure_ascii=False),
        json.dumps(case.turns, ensure_ascii=False),
        case.source_version,
    )
