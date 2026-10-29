"""审计服务：事件落库与按 trace_id 回放。"""

from __future__ import annotations

from app.entity.audit import AuditEvent
from app.repository.audit_repository import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> AuditRepository:
        return self._repo

    def log_events(self, events: list[AuditEvent]) -> str:
        return self._repo.append(events)

    def replay(self, trace_id: str) -> dict:
        events = self._repo.replay(trace_id)
        trigger = next((event.handoff_trigger for event in events if event.handoff_trigger), None)
        return {
            "trace_id": trace_id,
            "found": bool(events),
            "event_count": len(events),
            "handoff_trigger": trigger,
            "timeline": [event.model_dump() for event in events],
        }
