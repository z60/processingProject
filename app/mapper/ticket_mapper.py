"""tickets / handoff_tickets 的 SQL 与行映射。"""

from __future__ import annotations

import json

from app.entity.ticket import HandoffRecord, TicketRecord

TICKET_UPSERT = """
INSERT INTO tickets
    (ticket_id, session_id, user_id, trace_id, intent, confidence, risk_flag,
     raw_input, summary, draft_reply, status, handoff_reason, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    intent = VALUES(intent), confidence = VALUES(confidence), risk_flag = VALUES(risk_flag),
    summary = VALUES(summary), draft_reply = VALUES(draft_reply), status = VALUES(status),
    handoff_reason = VALUES(handoff_reason), updated_at = NOW()
"""

TICKET_SELECT = "SELECT * FROM tickets WHERE ticket_id = %s"

HANDOFF_UPSERT = """
INSERT INTO handoff_tickets
    (ticket_id, trigger_type, trigger_detail, conversation_snapshot, slots,
     draft_reply, status, handler_action, handler_note, created_at, handled_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    trigger_type = VALUES(trigger_type), trigger_detail = VALUES(trigger_detail),
    conversation_snapshot = VALUES(conversation_snapshot), slots = VALUES(slots),
    draft_reply = VALUES(draft_reply)
"""

HANDOFF_SELECT = "SELECT * FROM handoff_tickets WHERE ticket_id = %s"
HANDOFF_LIST = "SELECT * FROM handoff_tickets WHERE (%s = '' OR status = %s) ORDER BY created_at DESC LIMIT %s"
HANDOFF_ACTION = """
UPDATE handoff_tickets
SET status = %s, handler_action = %s, handler_note = %s, handled_at = NOW()
WHERE ticket_id = %s
"""

IDEM_INSERT = "INSERT INTO idempotency_keys (idem_key, scope, result_ref) VALUES (%s, %s, %s)"
IDEM_SELECT = "SELECT result_ref FROM idempotency_keys WHERE idem_key = %s"


def ticket_params(ticket: TicketRecord) -> tuple:
    return (
        ticket.ticket_id,
        ticket.session_id,
        ticket.user_id,
        ticket.trace_id,
        ticket.intent,
        ticket.confidence,
        int(ticket.risk_flag),
        ticket.raw_input,
        ticket.summary,
        ticket.draft_reply,
        ticket.status,
        ticket.handoff_reason,
        ticket.created_at,
    )


def ticket_from_row(row: dict) -> TicketRecord:
    return TicketRecord(
        ticket_id=row["ticket_id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        trace_id=row["trace_id"],
        intent=row["intent"],
        confidence=float(row["confidence"]),
        risk_flag=bool(row["risk_flag"]),
        raw_input=row.get("raw_input") or "",
        summary=row.get("summary") or "",
        draft_reply=row.get("draft_reply") or "",
        status=row["status"],
        handoff_reason=row.get("handoff_reason"),
        created_at=str(row["created_at"]),
    )


def handoff_params(record: HandoffRecord) -> tuple:
    return (
        record.ticket_id,
        record.trigger_type,
        json.dumps(record.trigger_detail, ensure_ascii=False),
        json.dumps(record.conversation_snapshot, ensure_ascii=False),
        json.dumps(record.slots, ensure_ascii=False),
        record.draft_reply,
        record.status,
        record.handler_action,
        record.handler_note,
        record.created_at,
        record.handled_at,
    )


def _load_json(value: str | dict | None, default):
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def handoff_from_row(row: dict) -> HandoffRecord:
    return HandoffRecord(
        ticket_id=row["ticket_id"],
        trigger_type=row["trigger_type"],
        trigger_detail=_load_json(row.get("trigger_detail"), {}),
        conversation_snapshot=_load_json(row.get("conversation_snapshot"), []),
        slots=_load_json(row.get("slots"), {}),
        draft_reply=row.get("draft_reply") or "",
        status=row["status"],
        handler_action=row.get("handler_action"),
        handler_note=row.get("handler_note"),
        created_at=str(row["created_at"]),
        handled_at=str(row["handled_at"]) if row.get("handled_at") else None,
    )
