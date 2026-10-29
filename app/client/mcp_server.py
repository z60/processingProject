"""MCP 工具网关（stdio + JSON-RPC 2.0，按行分隔），只暴露只读工具。

由 app/client/mcp_client.py 以子进程方式拉起；专家 Agent 的所有业务查询都经由
这里，保证工具调用有统一轨迹（F-15）与写操作隔离（4.4）。
"""

from __future__ import annotations

import json
import sys

from app.client.mysql_client import StorageUnavailable
from app.client.qdrant_client import QdrantError
from app.util.config import settings
from app.util.log import get_logger, setup_logging

log = get_logger("mcp_server")

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "query_order",
        "description": "按订单号查询订单状态、金额、物流信息。只返回业务系统真实数据，查无记录时 found=false。",
        "inputSchema": {
            "type": "object",
            "properties": {"order_no": {"type": "string", "description": "订单号，形如 SO20261028001"}},
            "required": ["order_no"],
        },
    },
    {
        "name": "query_user_orders",
        "description": "查询某个用户名下的近期订单列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户 ID，形如 u1001"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 5", "default": 5},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "query_ticket",
        "description": "按工单号查询工单处理状态与摘要。",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string", "description": "工单号，形如 TK202610270001"}},
            "required": ["ticket_id"],
        },
    },
    {
        "name": "search_knowledge",
        "description": "检索制度条款/售后政策知识库，返回命中的条款分块与来源，用于带引用的回答。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题"},
                "top_k": {"type": "integer", "description": "返回条数，默认 4", "default": 4},
            },
            "required": ["query"],
        },
    },
]

_repos: dict = {}


def _repos_get():
    if not _repos:
        from app.repository.knowledge_repository import KnowledgeRepository
        from app.repository.order_repository import OrderRepository
        from app.repository.ticket_repository import TicketRepository

        _repos["order"] = OrderRepository()
        _repos["ticket"] = TicketRepository()
        _repos["knowledge"] = KnowledgeRepository()
    return _repos


def _query_order(args: dict) -> dict:
    order_no = str(args.get("order_no", "")).strip()
    if not order_no:
        return {"found": False, "error": "INVALID_ARGUMENT", "message": "缺少订单号"}
    record = _repos_get()["order"].get_order(order_no)
    if record is None:
        return {"found": False, "order_no": order_no, "order": None}
    return {"found": True, "order_no": order_no, "order": record.model_dump()}


def _query_user_orders(args: dict) -> dict:
    user_id = str(args.get("user_id", "")).strip()
    if not user_id:
        return {"found": False, "error": "INVALID_ARGUMENT", "message": "缺少用户ID"}
    limit = int(args.get("limit") or 5)
    records = _repos_get()["order"].list_user_orders(user_id, limit=limit)
    return {"found": bool(records), "user_id": user_id, "orders": [record.model_dump() for record in records]}


def _query_ticket(args: dict) -> dict:
    ticket_id = str(args.get("ticket_id", "")).strip()
    if not ticket_id:
        return {"found": False, "error": "INVALID_ARGUMENT", "message": "缺少工单号"}
    record = _repos_get()["ticket"].get_ticket(ticket_id)
    if record is None:
        return {"found": False, "ticket_id": ticket_id, "ticket": None}
    return {"found": True, "ticket_id": ticket_id, "ticket": record.model_dump()}


def _search_knowledge(args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"found": False, "error": "INVALID_ARGUMENT", "message": "缺少检索内容"}
    top_k = int(args.get("top_k") or 4)
    hits = _repos_get()["knowledge"].search(query, top_k=top_k)
    return {"found": bool(hits), "query": query, "hits": [hit.model_dump() for hit in hits]}


HANDLERS = {
    "query_order": _query_order,
    "query_user_orders": _query_user_orders,
    "query_ticket": _query_ticket,
    "search_knowledge": _search_knowledge,
}


def _call_tool(params: dict) -> dict:
    name = params.get("name", "")
    arguments = params.get("arguments") or {}
    handler = HANDLERS.get(name)
    if handler is None:
        return _text_result({"error": "UNKNOWN_TOOL", "message": f"未知工具: {name}"}, is_error=True)
    try:
        payload = handler(arguments)
        return _text_result(payload)
    except StorageUnavailable as exc:
        log.warning("工具 %s 访问 MySQL 失败: %s", name, exc)
        return _text_result({"found": False, "error": "STORAGE_UNAVAILABLE", "message": "业务系统暂不可用"}, is_error=False)
    except QdrantError as exc:
        log.warning("工具 %s 访问 Qdrant 失败: %s", name, exc)
        return _text_result({"found": False, "error": "KNOWLEDGE_UNAVAILABLE", "message": "知识库暂不可用"}, is_error=False)
    except Exception as exc:  # 工具失败不得让整个会话崩溃
        log.exception("工具 %s 执行异常", name)
        return _text_result({"found": False, "error": "TOOL_FAILED", "message": str(exc)[:200]}, is_error=True)


def _text_result(payload: dict, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ticket-mcp-server", "version": "1.0.0"},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": msg_id, "result": _call_tool(params)}
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"未实现的方法: {method}"}}


def main() -> None:
    setup_logging(path=str(settings().data_dir / "mcp_server.log"), stream="file")
    stdin, stdout = sys.stdin, sys.stdout
    try:
        stdin.reconfigure(encoding="utf-8")
        stdout.reconfigure(encoding="utf-8")
    except AttributeError:  # 非标准流（例如被测试替换）
        pass
    log.info("MCP server 启动，工具: %s", ", ".join(HANDLERS))
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log.warning("非 JSON 消息，忽略：%s", line[:120])
            continue
        response = _handle(message)
        if response is not None:
            _write(response)


if __name__ == "__main__":
    main()
