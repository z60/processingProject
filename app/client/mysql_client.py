"""MySQL 访问客户端（PyMySQL，每次操作独立连接，失败语义明确）。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from app.util.config import settings
from app.util.log import get_logger

log = get_logger("mysql")


class StorageUnavailable(RuntimeError):
    """MySQL 不可用：调用方决定降级策略，不允许静默吞掉。"""


class MySQLClient:
    def __init__(self, database: str | None = None) -> None:
        self._conf = settings()
        self._database = self._conf.mysql_db if database is None else database

    def connect(self) -> pymysql.connections.Connection:
        try:
            return pymysql.connect(
                host=self._conf.mysql_host,
                port=self._conf.mysql_port,
                user=self._conf.mysql_user,
                password=self._conf.mysql_password,
                database=self._database,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
                connect_timeout=self._conf.mysql_connect_timeout,
                read_timeout=15,
                write_timeout=15,
            )
        except pymysql.err.MySQLError as exc:
            raise StorageUnavailable(f"MySQL 不可用（{self._conf.mysql_host}:{self._conf.mysql_port}）: {exc}") from exc

    @contextmanager
    def cursor(self) -> Iterator[DictCursor]:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                yield cur
        finally:
            conn.close()

    def query(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        try:
            with self.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())
        except pymysql.err.IntegrityError:
            raise
        except pymysql.err.MySQLError as exc:
            raise StorageUnavailable(f"MySQL 查询失败: {exc}") from exc

    def execute(self, sql: str, params: tuple | list | None = None) -> int:
        try:
            with self.cursor() as cur:
                return cur.execute(sql, params or ())
        except pymysql.err.IntegrityError:
            raise
        except pymysql.err.MySQLError as exc:
            raise StorageUnavailable(f"MySQL 执行失败: {exc}") from exc

    def executemany(self, sql: str, params: list[tuple]) -> int:
        try:
            with self.cursor() as cur:
                return cur.executemany(sql, params)
        except pymysql.err.IntegrityError:
            raise
        except pymysql.err.MySQLError as exc:
            raise StorageUnavailable(f"MySQL 批量执行失败: {exc}") from exc

    def ping(self) -> bool:
        try:
            with self.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except StorageUnavailable:
            return False
