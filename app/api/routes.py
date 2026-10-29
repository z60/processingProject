"""HTTP 接入层：只做参数校验与 DTO 转换，业务在 service。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.client.mysql_client import StorageUnavailable
from app.entity.chat import ChatRequest, ChatResponse, HandoffActionRequest, HandoffActionResponse
from app.entity.eval import RegressionReport
from app.entity.ticket import HandoffRecord
from app.repository.ticket_repository import HandoffNotFound
from app.service.agent_service import AgentFailure, AgentService
from app.service.audit_service import AuditService
from app.service.eval_service import EvalService
from app.service.ticket_service import TicketService
from app.util.log import get_logger

log = get_logger("api")

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def agent_service() -> AgentService:
    return AgentService()


@lru_cache(maxsize=1)
def ticket_service() -> TicketService:
    return agent_service().ticket_service


@lru_cache(maxsize=1)
def audit_service() -> AuditService:
    return agent_service().audit_service


@lru_cache(maxsize=1)
def eval_service() -> EvalService:
    service = agent_service()
    return EvalService(service, service.rules)


@router.post("/chat", response_model=ChatResponse, summary="对话入口")
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return agent_service().handle(request)
    except AgentFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ticket", response_model=ChatResponse, summary="工单提交入口")
def submit_ticket(request: ChatRequest) -> ChatResponse:
    try:
        return agent_service().handle(request)
    except AgentFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/audit/{trace_id}", summary="按 trace_id 回放审计证据链")
def replay_audit(trace_id: str) -> dict:
    payload = audit_service().replay(trace_id)
    if not payload["found"]:
        raise HTTPException(status_code=404, detail=f"未找到 trace_id={trace_id} 的审计事件")
    return payload


@router.get("/handoff", response_model=list[HandoffRecord], summary="转人工工单列表")
def list_handoffs(status: str = "OPEN", limit: int = 50) -> list[HandoffRecord]:
    return ticket_service().list_handoffs(status=status, limit=limit)


@router.post("/handoff/{ticket_id}/action", response_model=HandoffActionResponse, summary="人工动作回写")
def handoff_action(ticket_id: str, request: HandoffActionRequest) -> HandoffActionResponse:
    try:
        return ticket_service().handle_action(ticket_id, request)
    except HandoffNotFound as exc:
        raise HTTPException(status_code=404, detail=f"转人工工单不存在：{ticket_id}") from exc
    except StorageUnavailable as exc:
        log.error("人工动作写入失败: %s", exc)
        raise HTTPException(status_code=503, detail="工单存储不可用，请稍后重试") from exc


@router.post("/eval/regression", response_model=RegressionReport, summary="跑回归集与质量门禁")
def run_regression() -> RegressionReport:
    return eval_service().run()
