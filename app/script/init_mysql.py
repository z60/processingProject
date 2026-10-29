"""初始化 MySQL：建库、建表、装载种子数据（幂等，可重复执行）。

用法：
    python -m app.script.init_mysql            # 建表 + 装载种子
    python -m app.script.init_mysql --dry-run  # 只打印将要执行的语句与条数
"""

from __future__ import annotations

import argparse
import sys

from app.client.mysql_client import MySQLClient, StorageUnavailable
from app.entity.audit import AuditEvent
from app.entity.eval import RegressionCase
from app.entity.ticket import HandoffRecord, OrderRecord, TicketRecord
from app.mapper import audit_mapper, order_mapper, ticket_mapper
from app.mapper.schema import CREATE_DATABASE, SCHEMA
from app.util.config import read_jsonl, settings
from app.util.log import get_logger

log = get_logger("init_mysql")


def _seed_rows() -> dict[str, list[tuple]]:
    seed = settings().seed_dir
    orders = [OrderRecord(**item) for item in read_jsonl(seed / "orders.jsonl")]
    tickets = [TicketRecord(**item) for item in read_jsonl(seed / "tickets.jsonl")]
    handoffs = [HandoffRecord(**item) for item in read_jsonl(seed / "handoff_tickets.jsonl")]
    return {
        "orders": [order_mapper.order_params(item) for item in orders],
        "tickets": [ticket_mapper.ticket_params(item) for item in tickets],
        "handoff_tickets": [ticket_mapper.handoff_params(item) for item in handoffs],
    }


def init_mysql(dry_run: bool = False) -> None:
    conf = settings()
    statements = dict(SCHEMA)
    rows = _seed_rows()

    if dry_run:
        print(f"-- 目标库: {conf.mysql_host}:{conf.mysql_port}/{conf.mysql_db}")
        print(CREATE_DATABASE.format(db=conf.mysql_db))
        for name, ddl in statements.items():
            print(f"-- {name}: {len(rows.get(name, []))} 条种子")
            print(ddl.strip())
        return

    bootstrap = MySQLClient(database="")
    bootstrap.execute(CREATE_DATABASE.format(db=conf.mysql_db))
    log.info("数据库就绪：%s", conf.mysql_db)

    db = MySQLClient()
    for name, ddl in statements.items():
        db.execute(ddl)
        log.info("表就绪：%s", name)

    seed_plan = {
        "orders": (order_mapper.ORDER_UPSERT, rows["orders"]),
        "tickets": (ticket_mapper.TICKET_UPSERT, rows["tickets"]),
        "handoff_tickets": (ticket_mapper.HANDOFF_UPSERT, rows["handoff_tickets"]),
    }
    for name, (sql, params) in seed_plan.items():
        if params:
            db.executemany(sql, params)
        log.info("种子装载完成：%s（%s 条）", name, len(params))

    case_rows = [audit_mapper.case_params(RegressionCase(**item)) for item in read_jsonl(settings().seed_dir / "regression_cases.jsonl")]
    db.executemany(audit_mapper.CASE_UPSERT, case_rows)
    log.info("回归用例装载完成：%s 条", len(case_rows))

    audit_seed = read_jsonl(settings().seed_dir / "audit_logs.jsonl")
    audit_rows = [audit_mapper.audit_params(AuditEvent(**item)) for item in audit_seed]
    db.executemany(audit_mapper.AUDIT_INSERT, audit_rows)
    log.info("审计样本装载完成：%s 条", len(audit_rows))

    for name in ("orders", "tickets", "handoff_tickets", "audit_logs", "regression_cases"):
        count = db.query(f"SELECT COUNT(*) AS c FROM {name}")[0]["c"]
        log.info("校验 %s 当前行数：%s", name, count)


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 MySQL 表结构与种子数据")
    parser.add_argument("--dry-run", action="store_true", help="只打印 SQL 与种子条数，不连库")
    args = parser.parse_args()
    try:
        init_mysql(dry_run=args.dry_run)
    except StorageUnavailable as exc:
        log.error("MySQL 不可用：%s", exc)
        log.error("请确认 %s:%s 可从本机访问、%s 有写权限，然后重跑本脚本", settings().mysql_host, settings().mysql_port, settings().mysql_db)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
