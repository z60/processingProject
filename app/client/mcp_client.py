"""最小 MCP stdio 客户端（JSON-RPC 2.0，按行分隔）。

不依赖额外 SDK：协议部分只有 initialize / notifications/initialized /
tools/list / tools/call 四个方法，够用且行为可审计。
"""

from __future__ import annotations

import itertools
import json
import queue
import subprocess
import sys
import threading
import time
from typing import Any

from app.util.config import ROOT, conf, settings
from app.util.log import get_logger

log = get_logger("mcp_client")


class MCPUnavailable(RuntimeError):
    pass


class MCPClient:
    def __init__(self, command: str, args: list[str], timeout: float = 20.0) -> None:
        self._command = command
        self._args = args
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._stderr_handle = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> dict:
        stderr_path = settings().data_dir / "mcp_client_stderr.log"
        self._stderr_handle = stderr_path.open("a", encoding="utf-8")
        try:
            self._proc = subprocess.Popen(
                [self._command, *self._args],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_handle,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise MCPUnavailable(f"MCP server 启动失败: {exc}") from exc
        self._queue = queue.Queue()
        threading.Thread(target=self._pump, name="mcp-reader", daemon=True).start()
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ticket-agent", "version": "1.0.0"},
            },
        )
        self._notify("notifications/initialized", {})
        log.info("MCP 会话已建立: %s", result.get("serverInfo"))
        return result

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            self._queue.put(line)
        self._queue.put(None)

    def _write(self, payload: dict) -> None:
        if not self.alive or self._proc is None or self._proc.stdin is None:
            raise MCPUnavailable("MCP 进程不可用")
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        msg_id = next(self._ids)
        with self._lock:
            self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
            deadline = time.time() + (timeout or self._timeout)
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise MCPUnavailable(f"MCP 调用超时: {method}")
                try:
                    line = self._queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MCPUnavailable(f"MCP 调用超时: {method}") from exc
                if line is None:
                    raise MCPUnavailable("MCP 进程已退出")
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") != msg_id:
                    continue
                if "error" in message:
                    raise MCPUnavailable(f"MCP 错误({method}): {message['error']}")
                return message.get("result", {})

    def list_tools(self) -> list[dict]:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content") or []
        text = next((item.get("text", "") for item in content if item.get("type") == "text"), "")
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"found": False, "error": "BAD_TOOL_OUTPUT", "message": text[:200]}
        if result.get("isError") and "error" not in payload:
            payload["error"] = "TOOL_ERROR"
        return payload

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._proc.kill()
        if self._stderr_handle:
            self._stderr_handle.close()
            self._stderr_handle = None


_singleton: MCPClient | None = None
_singleton_lock = threading.Lock()


def get_mcp_client() -> MCPClient:
    """进程内复用同一个 MCP 会话；进程挂掉时自动重启。"""
    global _singleton
    with _singleton_lock:
        if _singleton is not None and _singleton.alive:
            return _singleton
        server_conf = conf("mcp")["servers"]["ticket_tools"]
        command = server_conf.get("command") or sys.executable
        if command == "python":
            command = sys.executable
        client = MCPClient(command, server_conf["args"], timeout=float(server_conf.get("timeout_seconds", 20)))
        client.start()
        if _singleton is not None:
            _singleton.close()
        _singleton = client
        return client
