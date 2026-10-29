"""离线自检：规则引擎、指纹、缓存 TTL、分块、映射、图路由。

用法：
    python -m app.script.selftest            # 纯离线，不依赖 MySQL/Qdrant/LLM
    python -m app.script.selftest --online   # 额外校验 Qdrant + Embedding 连通
"""

from __future__ import annotations

import argparse
import sys
import time

from app.entity.knowledge import KnowledgeDoc
from app.entity.ticket import HandoffRecord, TicketRecord
from app.mapper import ticket_mapper
from app.mapper.knowledge_mapper import chunk_document, point_id, split_text
from app.model.scripted import classify
from app.repository.cache_repository import CacheRepository
from app.util.rules import RulesEngine
from app.util.text import fingerprint, normalize


def check_rules() -> None:
    rules = RulesEngine()
    gray = rules.evaluate(intent="refund", confidence=0.72, clarify_rounds=0, text="能不能直接退给我")
    assert gray and gray["type"] == "refund_gray_zone", gray
    assert rules.evaluate(intent="refund", confidence=0.95, clarify_rounds=0, text="退款") is None
    human = rules.evaluate(intent="complaint", confidence=0.8, clarify_rounds=0, text="我要转人工")
    assert human and human["type"] == "explicit_human", human
    limit = rules.evaluate(intent="unknown", confidence=0.3, clarify_rounds=3, text="嗯")
    assert limit and limit["type"] == "clarify_limit", limit
    hits = rules.scan("我们一定给您退款，而且绝对不泄露您的信息")
    assert hits, "禁止承诺应命中"
    assert not rules.scan("客服不得在对话中承诺具体减免比例"), "带否定语义的引用条款不应误判"
    rewritten, _, needs_handoff = rules.rewrite("我们一定给您退款")
    assert "一定给您退款" not in rewritten and not needs_handoff, rewritten
    _, _, needs_handoff = rules.rewrite("我可以为您调整额度")
    assert needs_handoff, "额度调整承诺应转人工"
    assert rules.scan_escalation("我要起诉你们"), "用户法律威胁应被识别"


def check_text_and_cache() -> None:
    assert fingerprint("u1", "退款 99 元！") == fingerprint("u1", "退款99元")
    assert normalize("退款 99 元！") == "退款99元"
    cache = CacheRepository()
    cache.set("k", {"v": 1}, ttl=3600)
    assert cache.get("k") == {"v": 1}
    cache.set("k2", 1, ttl=1)
    time.sleep(1.1)
    assert cache.get("k2") is None, "TTL 到期应失效"
    assert cache.incr("c", 60) == 1 and cache.incr("c", 60) == 2


def check_mapper() -> None:
    doc = KnowledgeDoc(
        doc_id="t-1",
        title="测试条款",
        category="ecommerce",
        source="测试",
        text="第一句话。第二句话。第三句话。",
    )
    chunks = chunk_document(doc, chunk_size=6)
    assert len(chunks) == 3 and chunks[0].chunk_id == "t-1-1", chunks
    assert point_id(chunks[0]) == point_id(chunks[0]), "point id 必须确定性"
    assert split_text("", 10) == []

    ticket = TicketRecord(
        ticket_id="TK1",
        session_id="s1",
        user_id="u1",
        trace_id="t-1",
        intent="refund",
        confidence=0.72,
        risk_flag=True,
        raw_input="退款",
        summary="摘要",
        draft_reply="草稿",
        status="HANDOFF",
        handoff_reason="refund_gray_zone",
        created_at="2026-10-28 10:00:00",
    )
    assert len(ticket_mapper.ticket_params(ticket)) == 13
    handoff = HandoffRecord(ticket_id="TK1", trigger_type="refund_gray_zone", trigger_detail={"a": 1})
    assert len(ticket_mapper.handoff_params(handoff)) == 11


def check_classify() -> None:
    cases = {
        "年金领取需要满足什么条件？": "knowledge_qa",
        "订单 SO20261028001 现在到哪了？": "order_query",
        "我的工单 TK202610270001 处理到哪一步了？": "ticket_progress",
        "能不能帮我免掉这个月的息费": "refund",
        "我要转人工": "complaint",
        "嗯，这个情况你们看着处理吧": "unknown",
    }
    for text, expected in cases.items():
        actual = classify(text)["intent"]
        assert actual == expected, f"{text} 期望 {expected} 实际 {actual}"
    ambiguous = classify("耳机拆封了还能七天无理由退货吗？另外能不能直接退 268 元给我？")
    assert ambiguous["intent"] == "unknown" and ambiguous["confidence"] < 0.6, ambiguous


def check_graph_offline() -> None:
    """图装配与澄清分支（不依赖 MySQL / Qdrant / LLM）。"""
    from app.entity.chat import ChatRequest
    from app.service.agent_service import AgentService

    response = AgentService().handle(
        ChatRequest(text="嗯，这个情况你们看着处理吧", user_id="selftest", session_id="selftest-s1")
    )
    assert response.status == "CLARIFY", response.model_dump()
    assert response.reply, "追问不能为空"


def check_online() -> None:
    from app.repository.knowledge_repository import KnowledgeRepository

    repo = KnowledgeRepository()
    hits = repo.search("退款到账时效是多久？")
    assert hits, "Qdrant 检索应有命中"
    assert 0.0 <= hits[0].score <= 1.0
    assert all(hit.text for hit in hits)


def main() -> int:
    parser = argparse.ArgumentParser(description="离线自检")
    parser.add_argument("--online", action="store_true", help="额外校验 Qdrant + Embedding")
    args = parser.parse_args()

    checks = [check_rules, check_text_and_cache, check_mapper, check_classify, check_graph_offline]
    if args.online:
        checks.append(check_online)
    for check in checks:
        check()
        print(f"[PASS] {check.__name__}")
    print(f"自检通过：{len(checks)} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
