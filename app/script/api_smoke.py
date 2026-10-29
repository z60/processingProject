"""HTTP 接口冒烟测试：逐个打所有对外接口 + 关键边界，全部通过退出码 0。

用法：
    python -m app.script.api_smoke                       # 默认 http://127.0.0.1:8000
    python -m app.script.api_smoke --base http://127.0.0.1:8011
    python -m app.script.api_smoke --skip-eval          # 跳过耗时的回归接口
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((ok, name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}{'' if not detail else ' — ' + detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP 接口冒烟测试")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--skip-eval", action="store_true", help="跳过 /api/eval/regression")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base, timeout=300.0)
    session = f"smoke-{uuid.uuid4().hex[:8]}"

    # --- 基础页面 ---
    root = client.get("/")
    check("GET /", root.status_code == 200 and "工单处置 Agent" in root.text and "jsdelivr" not in root.text.lower(), f"{root.status_code}")

    health = client.get("/healthz").json()
    check("GET /healthz", health.get("mysql") is True and health.get("qdrant") is True and health.get("embedding") is True, str(health))

    spec = client.get("/openapi.json")
    paths = set(spec.json().get("paths", {})) if spec.status_code == 200 else set()
    required = {"/api/chat", "/api/ticket", "/api/audit/{trace_id}", "/api/handoff", "/api/handoff/{ticket_id}/action", "/api/eval/regression", "/healthz"}
    check("GET /openapi.json", spec.status_code == 200 and required <= paths, f"缺 {sorted(required - paths)}")

    docs = client.get("/docs")
    check("GET /docs", docs.status_code == 200 and "swagger" in docs.text.lower(), f"{docs.status_code}")

    # --- 对话接口 ---
    knowledge = client.post("/api/chat", json={"text": "年金领取需要满足什么条件？", "user_id": "smoke"})
    body = knowledge.json() if knowledge.status_code == 200 else {}
    check("POST /api/chat 知识问答", knowledge.status_code == 200 and body.get("status") == "ANSWERED" and len(body.get("citations", [])) > 0,
          f"{knowledge.status_code} status={body.get('status')} citations={len(body.get('citations', []))}")

    order = client.post("/api/chat", json={"text": "订单 SO20261028001 现在到哪了？", "user_id": "smoke"})
    order_body = order.json()
    check("POST /api/chat 订单查询", order.status_code == 200 and "SO20261028001" in order_body.get("reply", ""), order_body.get("reply", "")[:60])

    cached = client.post("/api/chat", json={"text": "订单 SO20261028001 现在到哪了？", "user_id": "smoke"})
    check("POST /api/chat 缓存命中", cached.status_code == 200 and cached.json().get("cached") is True, f"cached={cached.json().get('cached')}")

    refund = client.post("/api/chat", json={"text": "保温杯我不想要了，能不能直接退 99 元给我？", "user_id": "smoke"})
    refund_body = refund.json()
    handoff = refund_body.get("handoff") or {}
    check("POST /api/chat 退款灰色地带转人工",
          refund.status_code == 200 and refund_body.get("status") == "HANDOFF" and handoff.get("trigger_type") == "refund_gray_zone" and handoff.get("ticket_id"),
          f"status={refund_body.get('status')} trigger={handoff.get('trigger_type')}")

    escalation = client.post("/api/chat", json={"text": "平板买了半个月，我要全额退款，不给我就找律师", "user_id": "smoke"})
    check("POST /api/chat 法律威胁转人工", escalation.status_code == 200 and (escalation.json().get("handoff") or {}).get("trigger_type") == "user_escalation",
          str((escalation.json().get("handoff") or {}).get("trigger_type")))

    # 多轮追问：同一会话连续 3 次歧义输入 → clarify_limit 转人工
    clarify_status: list[str] = []
    for _ in range(3):
        r = client.post("/api/chat", json={"text": "耳机拆封了还能七天无理由退货吗？另外能不能直接退 268 元给我？", "user_id": "smoke", "session_id": session})
        clarify_status.append((r.json().get("status"), (r.json().get("handoff") or {}).get("trigger_type")))
    check("POST /api/chat 多轮追问计数",
          clarify_status[0][0] == "CLARIFY" and clarify_status[1][0] == "CLARIFY" and clarify_status[2] == ("HANDOFF", "clarify_limit"),
          str(clarify_status))

    # 参数校验
    check("POST /api/chat 空文本 422", client.post("/api/chat", json={"text": ""}).status_code == 422)
    check("POST /api/chat 缺字段 422", client.post("/api/chat", json={"user_id": "smoke"}).status_code == 422)
    check("POST /api/chat 超长 422", client.post("/api/chat", json={"text": "退" * 2001, "user_id": "smoke"}).status_code == 422)

    # --- 工单入口 ---
    ticket = client.post("/api/ticket", json={"text": "我要转人工", "user_id": "smoke"})
    ticket_body = ticket.json()
    check("POST /api/ticket", ticket.status_code == 200 and ticket_body.get("ticket_id") and ticket_body.get("status") == "HANDOFF",
          f"ticket_id={ticket_body.get('ticket_id')}")

    # --- 审计回放 ---
    replay = client.get(f"/api/audit/{order_body['trace_id']}")
    replay_body = replay.json() if replay.status_code == 200 else {}
    check("GET /api/audit/{trace_id}", replay.status_code == 200 and replay_body.get("event_count", 0) > 0, f"events={replay_body.get('event_count')}")
    check("GET /api/audit 不存在 404", client.get("/api/audit/t-not-exist").status_code == 404)

    # --- 转人工工单 ---
    handoff_list = client.get("/api/handoff", params={"status": "OPEN"})
    rows = handoff_list.json() if handoff_list.status_code == 200 else []
    check("GET /api/handoff", handoff_list.status_code == 200 and all(row["status"] == "OPEN" for row in rows) and rows, f"{len(rows)} 条")
    check("GET /api/handoff 非法参数 422", client.get("/api/handoff", params={"limit": "abc"}).status_code == 422)

    ticket_id = handoff.get("ticket_id") or (rows[0]["ticket_id"] if rows else "")
    confirm = client.post(f"/api/handoff/{ticket_id}/action", json={"action": "CONFIRM", "note": "核对无误", "operator": "smoke"})
    check("POST /api/handoff/{id}/action CONFIRM", confirm.status_code == 200 and confirm.json().get("status") == "CONFIRMED", str(confirm.json()))

    again = client.post(f"/api/handoff/{ticket_id}/action", json={"action": "CONFIRM", "note": "核对无误", "operator": "smoke"})
    check("POST 人工动作幂等", again.status_code == 200 and again.json().get("idempotent") is True, str(again.json()))

    edited = client.post(f"/api/handoff/{ticket_id}/action", json={"action": "EDIT", "note": "补充说明", "edited_reply": "修改后的答复"})
    check("POST 人工动作 EDIT", edited.status_code == 200 and edited.json().get("status") == "EDITED", str(edited.json()))

    returned = client.post(f"/api/handoff/{ticket_id}/action", json={"action": "RETURN", "note": "信息不全"})
    check("POST 人工动作 RETURN", returned.status_code == 200 and returned.json().get("status") == "RETURNED", str(returned.json()))

    check("POST 非法动作 422", client.post(f"/api/handoff/{ticket_id}/action", json={"action": "DROP"}).status_code == 422)
    check("POST 不存在工单 404", client.post("/api/handoff/H-NOT-EXIST/action", json={"action": "CONFIRM", "note": ""}).status_code == 404)

    # --- 回归接口 ---
    if not args.skip_eval:
        report = client.post("/api/eval/regression")
        report_body = report.json() if report.status_code == 200 else {}
        check("POST /api/eval/regression", report.status_code == 200 and report_body.get("gate") == "PASS",
              f"gate={report_body.get('gate')} {report_body.get('passed')}/{report_body.get('total')}")

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\n通过 {len(RESULTS) - len(failed)}/{len(RESULTS)}" + ("" if not failed else f"，失败：{failed}"))
    client.close()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
