"""单条对话演示：打印结构化响应与审计证据链。

用法：
    python -m app.script.demo "订单 SO20261028001 现在到哪了？"
    python -m app.script.demo "保温杯我不想要了，能不能直接退 99 元给我？" --user u1002
"""

from __future__ import annotations

import argparse
import json
import sys

from app.entity.chat import ChatRequest
from app.service.agent_service import AgentService


def main() -> int:
    parser = argparse.ArgumentParser(description="工单处置 Agent 单轮演示")
    parser.add_argument("text", help="用户输入")
    parser.add_argument("--user", default="demo-user", help="用户 ID")
    parser.add_argument("--session", default=None, help="会话 ID（多轮演示时复用）")
    args = parser.parse_args()

    service = AgentService()
    response = service.handle(ChatRequest(text=args.text, user_id=args.user, session_id=args.session))
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))

    replay = service.audit_service.replay(response.trace_id)
    print("\n--- 审计回放（%s 条事件）---" % replay["event_count"])
    for event in replay["timeline"]:
        node = event.get("node")
        name = event.get("event")
        extra = event.get("handoff_trigger") or event.get("tool_calls") or ""
        print(f"[{node}] {name} {json.dumps(extra, ensure_ascii=False) if extra else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
