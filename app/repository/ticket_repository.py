"""工单、转人工工单、幂等键仓储。"""

from __future__ import annotations

import pymysql

from app.client.mysql_client import MySQLClient
from app.entity.ticket import HandoffRecord, TicketRecord
from app.mapper import ticket_mapper
from app.util.log import get_logger

log = get_logger("ticket_repository")


class HandoffNotFound(LookupError):
    """转人工工单不存在。"""


class TicketRepository:
    def __init__(self) -> None:
        self._db = MySQLClient()

    # --- tickets ---
    def save_ticket(self, ticket: TicketRecord) -> None:
        self._db.execute(ticket_mapper.TICKET_UPSERT, ticket_mapper.ticket_params(ticket))

    def get_ticket(self, ticket_id: str) -> TicketRecord | None:
        rows = self._db.query(ticket_mapper.TICKET_SELECT, (ticket_id,))
        return ticket_mapper.ticket_from_row(rows[0]) if rows else None

    # --- handoff_tickets ---
    def save_handoff(self, record: HandoffRecord) -> None:
        self._db.execute(ticket_mapper.HANDOFF_UPSERT, ticket_mapper.handoff_params(record))

    def get_handoff(self, ticket_id: str) -> HandoffRecord | None:
        rows = self._db.query(ticket_mapper.HANDOFF_SELECT, (ticket_id,))
        return ticket_mapper.handoff_from_row(rows[0]) if rows else None

    def list_handoffs(self, status: str = "", limit: int = 50) -> list[HandoffRecord]:
        rows = self._db.query(ticket_mapper.HANDOFF_LIST, (status, status, limit))
        return [ticket_mapper.handoff_from_row(row) for row in rows]

    def apply_action(
        self,
        ticket_id: str,
        status: str,
        action: str,
        note: str,
        idem_key: str,
    ) -> tuple[bool, bool]:
        """返回 (是否成功, 是否幂等命中)。工单不存在返回 (False, False)。"""
        if self.get_handoff(ticket_id) is None:
            return False, False
        if not self._claim_idem(idem_key, "handoff_action", ticket_id):
            return True, True
        self._db.execute(
            ticket_mapper.HANDOFF_ACTION,
            (status, action, note[:512], ticket_id),
        )
        return True, False

    # --- 幂等 ---
    def _claim_idem(self, idem_key: str, scope: str, ref: str) -> bool:
        try:
            self._db.execute(ticket_mapper.IDEM_INSERT, (idem_key, scope, ref))
            return True
        except pymysql.err.IntegrityError:
            log.info("幂等命中，跳过重复写：%s", idem_key)
            return False

    def ping(self) -> bool:
        return self._db.ping()
