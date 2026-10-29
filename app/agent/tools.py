"""MCP 工具绑定与调用（带 trace 事件）。"""

from __future__ import annotations

import time

from app.client.mcp_client import MCPUnavailable, get_mcp_client
from app.util.log import get_logger

log = get_logger("agent_tools")

_TOOL_CACHE: list[dict] | None = None


def tool_schemas() -> list[dict]:
    """从 MCP 网关读取工具描述，转成 bind_tools 需要的 schema。"""
    global _TOOL_CACHE
    if _TOOL_CACHE is not None:
        return _TOOL_CACHE
    try:
        raw = get_mcp_client().list_tools()
        _TOOL_CACHE = [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
            for tool in raw
        ]
        return _TOOL_CACHE
    except MCPUnavailable as exc:
        log.warning("MCP 工具列表不可用: %s", exc)
        return []


def schemas_for(names: list[str]) -> list[dict]:
    return [schema for schema in tool_schemas() if schema["name"] in names]


def execute_tool(name: str, arguments: dict) -> tuple[dict, dict]:
    """执行 MCP 工具，返回 (payload, 审计事件字段)。失败不抛异常，交给专家如实反馈。"""
    started = time.perf_counter()
    try:
        payload = get_mcp_client().call_tool(name, arguments)
        error = payload.get("error")
    except MCPUnavailable as exc:
        log.warning("MCP 工具调用失败 %s: %s", name, exc)
        payload = {"found": False, "error": "MCP_UNAVAILABLE", "message": "业务工具暂不可用"}
        error = "MCP_UNAVAILABLE"
    cost_ms = int((time.perf_counter() - started) * 1000)
    event = {
        "tool": name,
        "args": arguments,
        "cost_ms": cost_ms,
        "found": bool(payload.get("found")),
        "error": error,
    }
    return payload, event
