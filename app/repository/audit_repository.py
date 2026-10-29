"""审计日志仓储：MySQL 为主，不可用时降级到本地 JSONL（不丢事件）。"""

from __future__ import annotations

import json

from app.client.mysql_client import MySQLClient, StorageUnavailable
from app.entity.audit import AuditEvent
from app.mapper import audit_mapper
from app.util.config import settings
from app.util.log import get_logger

log = get_logger("audit_repository")


class AuditRepository:
    def __init__(self) -> None:
        self._db = MySQLClient()
        self._fallback = settings().data_dir / "audit_fallback.jsonl"

    def append(self, events: list[AuditEvent]) -> str:
        """返回落盘位置：mysql / fallback。"""
        if not events:
            return "mysql"
        rows = [audit_mapper.audit_params(event) for event in events]
        try:
            self._db.executemany(audit_mapper.AUDIT_INSERT, rows)
            return "mysql"
        except StorageUnavailable as exc:
            log.warning("审计落库失败，降级写入本地文件：%s", exc)
            self.append_fallback(events)
            return "fallback"

    def append_fallback(self, events: list[AuditEvent]) -> None:
        self._fallback.parent.mkdir(parents=True, exist_ok=True)
        with self._fallback.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(event.model_dump_json() + "\n")

    def replay(self, trace_id: str) -> list[AuditEvent]:
        try:
            rows = self._db.query(audit_mapper.AUDIT_BY_TRACE, (trace_id,))
            events = [audit_mapper.audit_from_row(row) for row in rows]
            if events:
                return events
        except StorageUnavailable as exc:
            log.warning("审计回放读 MySQL 失败，尝试本地文件：%s", exc)
        return self._replay_fallback(trace_id)

    def _replay_fallback(self, trace_id: str) -> list[AuditEvent]:
        if not self._fallback.exists():
            return []
        events: list[AuditEvent] = []
        for line in self._fallback.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("trace_id") == trace_id:
                events.append(AuditEvent(**payload))
        return events

    def ping(self) -> bool:
        return self._db.ping()
