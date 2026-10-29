"""工单服务：工单落库、转人工工单读取与人工动作回写。"""

from __future__ import annotations

from app.client.mysql_client import StorageUnavailable
from app.entity.chat import HandoffActionRequest, HandoffActionResponse
from app.entity.ticket import HandoffRecord, TicketRecord
from app.repository.cache_repository import CacheRepository
from app.repository.ticket_repository import HandoffNotFound, TicketRepository
from app.util.config import conf
from app.util.log import get_logger
from app.util.text import digest

log = get_logger("ticket_service")


class TicketService:
    def __init__(self, repository: TicketRepository, cache: CacheRepository) -> None:
        self._repo = repository
        self._cache = cache

    def save_ticket(self, ticket: TicketRecord) -> None:
        """工单结果必须留痕：MySQL 不可用时写缓存，至少不丢当次会话。"""
        try:
            self._repo.save_ticket(ticket)
        except StorageUnavailable as exc:
            log.warning("工单落库失败，降级写缓存：%s", exc)
            ttl = conf("settings")["cache"]["handoff_ttl_seconds"]
            self._cache.set(f"ticket:{ticket.ticket_id}", ticket.model_dump(), ttl)

    def get_handoff(self, ticket_id: str) -> HandoffRecord | None:
        try:
            record = self._repo.get_handoff(ticket_id)
            if record:
                return record
        except StorageUnavailable as exc:
            log.warning("读取转人工工单失败，降级读缓存：%s", exc)
        cached = self._cache.get(f"handoff:{ticket_id}")
        return HandoffRecord(**cached) if cached else None

    def list_handoffs(self, status: str = "", limit: int = 50) -> list[HandoffRecord]:
        try:
            return self._repo.list_handoffs(status=status, limit=limit)
        except StorageUnavailable as exc:
            log.warning("读取转人工工单列表失败：%s", exc)
            return []

    def handle_action(self, ticket_id: str, request: HandoffActionRequest) -> HandoffActionResponse:
        status_map = {"CONFIRM": "CONFIRMED", "RETURN": "RETURNED", "EDIT": "EDITED"}
        new_status = status_map[request.action]
        idem_key = digest(ticket_id, request.action, request.note, request.edited_reply)
        ok, idempotent = self._repo.apply_action(
            ticket_id=ticket_id,
            status=new_status,
            action=request.action,
            note=request.note,
            idem_key=idem_key,
        )
        if not ok:
            raise HandoffNotFound(ticket_id)
        if not idempotent:
            record = self._repo.get_handoff(ticket_id)
            if record:
                self._cache.set(f"handoff:{ticket_id}", record.model_dump(), conf("settings")["cache"]["handoff_ttl_seconds"])
        return HandoffActionResponse(ok=ok, ticket_id=ticket_id, status=new_status, idempotent=idempotent)
