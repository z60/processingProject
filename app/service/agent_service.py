"""对话编排：缓存 → LangGraph 执行 → 工单落库。"""

from __future__ import annotations

import time

from app.agent.graph import build_graph
from app.agent.nodes import AgentNodes
from app.agent.state import new_state
from app.entity.chat import ChatRequest, ChatResponse, HandoffInfo
from app.entity.ticket import TicketRecord
from app.repository.audit_repository import AuditRepository
from app.repository.cache_repository import CacheRepository
from app.repository.ticket_repository import TicketRepository
from app.service.audit_service import AuditService
from app.service.ticket_service import TicketService
from app.util.config import conf
from app.util.ids import new_session_id, new_ticket_id, new_trace_id
from app.util.log import get_logger
from app.util.rules import RulesEngine
from app.util.text import fingerprint
from app.util.time import now_str

log = get_logger("agent_service")


class AgentFailure(RuntimeError):
    """处置流程不可用（异常已记录日志，带 trace_id 便于排查）。"""


class AgentService:
    def __init__(self) -> None:
        self.rules = RulesEngine()
        self.cache = CacheRepository()
        self.audit_service = AuditService(AuditRepository())
        self.ticket_repository = TicketRepository()
        self.ticket_service = TicketService(self.ticket_repository, self.cache)
        nodes = AgentNodes(
            rules=self.rules,
            audit_repository=self.audit_service.repository,
            ticket_repository=self.ticket_repository,
            cache=self.cache,
        )
        self.graph = build_graph(nodes)
        self._settings = conf("settings")

    def handle(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        session_id = request.session_id or new_session_id()
        cache_key = f"cache:{fingerprint(request.user_id, request.text)}"

        cached = self.cache.get(cache_key)
        if cached:
            log.info("缓存命中，跳过 LLM：%s", cache_key)
            payload = dict(cached)
            payload.update(cached=True, latency_ms=0)
            return ChatResponse(**payload)

        trace_id = new_trace_id()
        state = new_state(
            trace_id=trace_id,
            session_id=session_id,
            user_id=request.user_id,
            text=request.text,
            started_at=started,
        )
        try:
            result = self.graph.invoke(state, config={"configurable": {"thread_id": session_id}})
        except Exception as exc:
            log.exception("LangGraph 执行失败，trace_id=%s", trace_id)
            raise AgentFailure(f"处置流程执行失败（trace_id={trace_id}），请稍后重试") from exc

        status = result.get("status") or "ANSWERED"
        handoff = result.get("handoff")
        reply = result.get("reply") or result.get("draft") or ""
        ticket_id = handoff["ticket_id"] if handoff else new_ticket_id()
        confidence = float(result.get("confidence") or 0.0)

        self.ticket_service.save_ticket(
            TicketRecord(
                ticket_id=ticket_id,
                session_id=session_id,
                user_id=request.user_id,
                trace_id=trace_id,
                intent=result.get("intent") or "unknown",
                confidence=confidence,
                risk_flag=bool(result.get("risk_flag")),
                raw_input=request.text,
                summary=result.get("summary") or reply[:80],
                draft_reply=reply,
                status=status,
                handoff_reason=handoff["trigger_type"] if handoff else None,
                created_at=now_str(),
            )
        )
        # 本轮未追问则清空连续失败计数（F-14）
        if status != "CLARIFY":
            self.cache.delete(f"clarify:{session_id}")

        response = ChatResponse(
            trace_id=trace_id,
            ticket_id=ticket_id,
            status=status,
            reply=reply,
            intent=result.get("intent") or "unknown",
            confidence=confidence,
            risk_flag=bool(result.get("risk_flag")),
            citations=result.get("citations") or [],
            tool_calls=result.get("tool_calls") or [],
            handoff=HandoffInfo(**handoff) if handoff else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        # 追问结果依赖会话计数，不进缓存，避免多轮计数被缓存跳过（F-14）
        if status != "CLARIFY":
            self.cache.set(cache_key, response.model_dump())
        return response
