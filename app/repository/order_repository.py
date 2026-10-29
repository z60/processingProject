"""订单数据仓储。"""

from __future__ import annotations

from app.client.mysql_client import MySQLClient
from app.entity.ticket import OrderRecord
from app.mapper import order_mapper


class OrderRepository:
    def __init__(self) -> None:
        self._db = MySQLClient()

    def get_order(self, order_no: str) -> OrderRecord | None:
        rows = self._db.query(order_mapper.ORDER_SELECT, (order_no,))
        return order_mapper.order_from_row(rows[0]) if rows else None

    def list_user_orders(self, user_id: str, limit: int = 5) -> list[OrderRecord]:
        rows = self._db.query(order_mapper.ORDER_BY_USER, (user_id, limit))
        return [order_mapper.order_from_row(row) for row in rows]

    def ping(self) -> bool:
        return self._db.ping()
