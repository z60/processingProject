"""orders 的 SQL 与行映射。"""

from __future__ import annotations

from app.entity.ticket import OrderRecord

ORDER_SELECT = "SELECT * FROM orders WHERE order_no = %s"
ORDER_BY_USER = "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT %s"
ORDER_UPSERT = """
INSERT INTO orders
    (order_no, user_id, status, amount, refundable_amount, logistics_no, product, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    user_id = VALUES(user_id), status = VALUES(status), amount = VALUES(amount),
    refundable_amount = VALUES(refundable_amount), logistics_no = VALUES(logistics_no),
    product = VALUES(product), updated_at = VALUES(updated_at)
"""


def order_from_row(row: dict) -> OrderRecord:
    return OrderRecord(
        order_no=row["order_no"],
        user_id=row["user_id"],
        status=row["status"],
        amount=float(row["amount"]),
        refundable_amount=float(row["refundable_amount"]),
        logistics_no=row.get("logistics_no") or "",
        product=row.get("product") or "",
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def order_params(record: OrderRecord) -> tuple:
    return (
        record.order_no,
        record.user_id,
        record.status,
        record.amount,
        record.refundable_amount,
        record.logistics_no,
        record.product,
        record.created_at,
        record.updated_at,
    )
