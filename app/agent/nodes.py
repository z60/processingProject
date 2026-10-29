"""LangGraph 节点实现。

路由 → 追问/专家 → 规则门禁 → 转人工 → 审计。
转人工由 guard 节点的确定性规则决定，模型没有转人工发言权（F-10）。
"""

from __future__ import annotations

import json
import re
import time

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.state import AgentState
from app.agent.tools import execute_tool, schemas_for
from app.client.mysql_client import StorageUnavailable
from app.entity.audit import AuditEvent
from app.entity.ticket import HandoffRecord
from app.model.llm import get_chat_model
from app.repository.audit_repository import AuditRepository
from app.repository.cache_repository import CacheRepository
from app.repository.ticket_repository import TicketRepository
from app.util.config import conf, load_prompt
from app.util.ids import new_ticket_id
from app.util.log import get_logger
from app.util.rules import RulesEngine
from app.util.time import now_str

log = get_logger("agent_nodes")

_JSON_RE = re.compile(r"\{.*\}", re.S)
_CLARIFY_FALLBACK = "为了准确处理您的问题，请补充一下：您是想咨询相关规则政策，还是查询具体订单/退款进度？"


def _content(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


def _add_tokens(tokens: dict, message: BaseMessage) -> dict:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "prompt": tokens.get("prompt", 0) + int(usage.get("input_tokens", 0)),
        "completion": tokens.get("completion", 0) + int(usage.get("output_tokens", 0)),
    }


def _event(state: AgentState, node: str, event: str, **kwargs) -> dict:
    payload = {"trace_id": state["trace_id"], "node": node, "event": event}
    payload.update({key: value for key, value in kwargs.items() if value is not None})
    return payload


class AgentNodes:
    def __init__(
        self,
        *,
        rules: RulesEngine,
        audit_repository: AuditRepository,
        ticket_repository: TicketRepository,
        cache: CacheRepository,
    ) -> None:
        self.rules = rules
        self.audit_repository = audit_repository
        self.ticket_repository = ticket_repository
        self.cache = cache
        self._intents = conf("intents")["intents"]
        self._expert_by_intent = {item["name"]: item["expert"] for item in self._intents}
        self._settings = conf("settings")

    # --- 路由 ---
    def router(self, state: AgentState) -> dict:
        started = time.perf_counter()
        prompt, version = load_prompt("router")
        model = get_chat_model("router")
        parsed: dict = {}
        tokens = {"prompt": 0, "completion": 0}
        for attempt in range(self._settings["router"]["parse_retry"] + 1):
            message = model.invoke([SystemMessage(content=prompt), HumanMessage(content=state["text"])])
            tokens = _add_tokens(tokens, message)
            parsed = self._parse_json(_content(message))
            if parsed:
                break
            log.warning("路由 JSON 解析失败（第 %s 次），准备重试", attempt + 1)
        intent = parsed.get("intent", "unknown")
        if intent not in self._expert_by_intent:
            intent = "unknown"
        confidence = float(parsed.get("confidence") or 0.0)
        risk_flag = bool(parsed.get("risk_flag"))
        slots = parsed.get("slots") or {}
        latency = int((time.perf_counter() - started) * 1000)
        event = _event(
            state,
            "router",
            "intent_routed",
            intent=intent,
            confidence=confidence,
            latency_ms=latency,
            token_usage=tokens,
            prompt_version=version,
        )
        return {
            "intent": intent,
            "confidence": confidence,
            "risk_flag": risk_flag,
            "slots": slots,
            "tokens": tokens,
            "events": [*state.get("events", []), event],
        }

    @staticmethod
    def _parse_json(content: str) -> dict:
        match = _JSON_RE.search(content or "")
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    # --- 追问 ---
    def clarify(self, state: AgentState) -> dict:
        started = time.perf_counter()
        prompt, version = load_prompt("clarify")
        ttl = self._settings["cache"]["fail_counter_ttl_seconds"]
        rounds = self.cache.incr(f"clarify:{state['session_id']}", ttl)
        question = _CLARIFY_FALLBACK
        tokens = {"prompt": 0, "completion": 0}
        try:
            message = get_chat_model("clarify").invoke(
                [SystemMessage(content=prompt), HumanMessage(content=state["text"])]
            )
            tokens = _add_tokens(tokens, message)
            if _content(message).strip():
                question = _content(message).strip()
        except Exception as exc:  # 追问失败不能中断会话
            log.warning("追问生成失败，使用兜底话术: %s", exc)
        latency = int((time.perf_counter() - started) * 1000)
        event = _event(
            state,
            "clarify",
            "clarify_asked",
            intent=state.get("intent"),
            confidence=state.get("confidence"),
            latency_ms=latency,
            token_usage=tokens,
            prompt_version=version,
            clarify_rounds=rounds,
        )
        return {
            "clarify_rounds": rounds,
            "status": "CLARIFY",
            "reply": question,
            "tokens": tokens,
            "events": [*state.get("events", []), event],
        }

    # --- 专家 ---
    def order_expert(self, state: AgentState) -> dict:
        return self._run_expert(state, role="order_expert", prompt_name="order_expert",
                                tool_names=["query_order", "query_user_orders", "query_ticket"])

    def knowledge_expert(self, state: AgentState) -> dict:
        return self._run_expert(state, role="knowledge_expert", prompt_name="knowledge_expert",
                                tool_names=["search_knowledge"])

    def compliance_expert(self, state: AgentState) -> dict:
        return self._run_expert(state, role="compliance_expert", prompt_name="compliance_expert",
                                tool_names=["search_knowledge"])

    def _run_expert(self, state: AgentState, *, role: str, prompt_name: str, tool_names: list[str]) -> dict:
        started = time.perf_counter()
        prompt, version = load_prompt(prompt_name)
        tokens = dict(state.get("tokens") or {"prompt": 0, "completion": 0})
        citations: list[dict] = []
        tool_calls: list[dict] = []
        draft = ""
        messages: list[BaseMessage] = [
            SystemMessage(content=f"{prompt}\n\n## 运行上下文\n当前用户ID：{state['user_id']}"),
            HumanMessage(content=state["text"]),
        ]
        max_rounds = self._settings["expert"]["max_tool_rounds"]
        try:
            model = get_chat_model(role).bind_tools(schemas_for(tool_names))
            for _ in range(max_rounds):
                ai_message = model.invoke(messages)
                tokens = _add_tokens(tokens, ai_message)
                if not ai_message.tool_calls:
                    draft = _content(ai_message).strip()
                    break
                messages.append(ai_message)
                for call in ai_message.tool_calls:
                    name = call.get("name", "")
                    args = call.get("args") or {}
                    if name not in tool_names:
                        messages.append(
                            ToolMessage(
                                content=json.dumps({"error": "TOOL_NOT_ALLOWED", "message": f"不允许的工具: {name}"}, ensure_ascii=False),
                                tool_call_id=call.get("id", ""),
                            )
                        )
                        continue
                    payload, tool_event = execute_tool(name, args)
                    tool_calls.append(tool_event)
                    if name == "search_knowledge":
                        citations = [
                            {
                                "chunk_id": hit.get("chunk_id", ""),
                                "title": hit.get("title", ""),
                                "source": hit.get("source", ""),
                                "score": hit.get("score", 0.0),
                            }
                            for hit in payload.get("hits", [])
                        ]
                    messages.append(
                        ToolMessage(
                            content=json.dumps(payload, ensure_ascii=False),
                            tool_call_id=call.get("id", ""),
                        )
                    )
            else:
                draft = "抱歉，这次查询没有在限定轮次内完成，请稍后重试或转人工。"
        except Exception as exc:
            log.exception("专家节点 %s 执行失败", role)
            draft = "抱歉，处理过程中出现问题，请稍后重试或转人工。"
            tool_calls.append({"tool": role, "args": {}, "error": "EXPERT_FAILED", "message": str(exc)[:200]})
        if not draft:
            draft = "抱歉，暂时无法生成答复，请稍后重试或转人工。"
        latency = int((time.perf_counter() - started) * 1000)
        event = _event(
            state,
            role,
            "expert_completed",
            intent=state.get("intent"),
            confidence=state.get("confidence"),
            tool_calls=tool_calls,
            retrieval_sources=citations,
            latency_ms=latency,
            token_usage=tokens,
            prompt_version=version,
        )
        return {
            "draft": draft,
            "citations": citations,
            "tool_calls": [*state.get("tool_calls", []), *tool_calls],
            "tokens": tokens,
            "expert": role,
            "events": [*state.get("events", []), event],
        }

    # --- 规则门禁 ---
    def guard(self, state: AgentState) -> dict:
        started = time.perf_counter()
        status = state.get("status") or ""
        draft = state.get("draft") or ""
        rewritten, hits, needs_handoff = self.rules.rewrite(draft)
        escalations = self.rules.scan_escalation(state["text"])

        trigger: dict | None = None
        if escalations:
            trigger = {
                "type": "user_escalation",
                "detail": {"source": "user_input", "hits": [hit["rule_id"] for hit in escalations]},
            }
        elif needs_handoff:
            trigger = {
                "type": "forbidden_commitment",
                "detail": {"source": "reply", "hits": [hit.rule_id for hit in hits if hit.action == "handoff"]},
            }
        else:
            trigger = self.rules.evaluate(
                intent=state.get("intent", "unknown"),
                confidence=float(state.get("confidence") or 0.0),
                clarify_rounds=int(state.get("clarify_rounds") or 0),
                text=state["text"],
            )

        latency = int((time.perf_counter() - started) * 1000)
        event = _event(
            state,
            "guard",
            "handoff_triggered" if trigger else "guard_passed",
            intent=state.get("intent"),
            confidence=state.get("confidence"),
            handoff_trigger=trigger,
            latency_ms=latency,
        )
        result: dict = {"events": [*state.get("events", []), event]}
        if status != "CLARIFY":
            result["draft"] = rewritten
            result["reply"] = rewritten
        if trigger:
            result["handoff_trigger"] = trigger
            result["status"] = "HANDOFF"
        elif status != "CLARIFY":
            result["status"] = "ANSWERED"
        return result

    # --- 转人工 ---
    def handoff(self, state: AgentState) -> dict:
        started = time.perf_counter()
        trigger = state.get("handoff_trigger") or {}
        ticket_id = new_ticket_id()
        draft = state.get("draft") or ""
        if not draft:
            # 追问超限触发的转人工没有专家草稿，给人工一句上下文，避免把追问话术当草稿
            draft = state.get("reply") if state.get("expert") else "AI 未能确认用户诉求，转人工澄清。"
        summary = self._summary(state)
        record = HandoffRecord(
            ticket_id=ticket_id,
            trigger_type=str(trigger.get("type", "unknown")),
            trigger_detail=trigger.get("detail") or {},
            conversation_snapshot=[{"role": "user", "content": state["text"]}],
            slots=state.get("slots") or {},
            draft_reply=draft,
            status="OPEN",
            created_at=now_str(),
        )
        sink = "mysql"
        try:
            self.ticket_repository.save_handoff(record)
        except StorageUnavailable as exc:
            sink = "cache"
            log.warning("转人工工单落库失败，降级写缓存：%s", exc)
        ttl = self._settings["cache"]["handoff_ttl_seconds"]
        self.cache.set(f"handoff:{ticket_id}", record.model_dump(), ttl)
        latency = int((time.perf_counter() - started) * 1000)
        event = _event(
            state,
            "handoff",
            "handoff_created",
            intent=state.get("intent"),
            confidence=state.get("confidence"),
            handoff_trigger=trigger,
            latency_ms=latency,
            storage=sink,
        )
        return {
            "handoff": {
                "ticket_id": ticket_id,
                "trigger_type": record.trigger_type,
                "trigger_detail": record.trigger_detail,
                "draft_reply": draft,
            },
            "summary": summary,
            "status": "HANDOFF",
            "reply": self.rules.handoff_reply(ticket_id),
            "events": [*state.get("events", []), event],
        }

    def _summary(self, state: AgentState) -> str:
        prompt, version = load_prompt("summary")
        try:
            message = get_chat_model("summary").invoke(
                [SystemMessage(content=prompt), HumanMessage(content=state["text"])]
            )
            content = _content(message).strip()
        except Exception as exc:
            log.warning("摘要生成失败: %s", exc)
            content = ""
        return content or f"用户诉求：{state['text'][:80]}"

    # --- 审计 ---
    def audit(self, state: AgentState) -> dict:
        events = list(state.get("events", []))
        elapsed = int((time.perf_counter() - float(state.get("started_at") or time.perf_counter())) * 1000)
        events.append(
            _event(
                state,
                "audit",
                "response",
                intent=state.get("intent"),
                confidence=state.get("confidence"),
                handoff_trigger=state.get("handoff_trigger"),
                status=state.get("status"),
                latency_ms=elapsed,
            )
        )
        sink = "mysql"
        try:
            sink = self.audit_repository.append([AuditEvent(**event) for event in events])
        except Exception:  # 审计失败不得中断用户请求：落本地文件并告警
            log.exception("审计落库异常，降级写入本地文件")
            self.audit_repository.append_fallback([AuditEvent(**event) for event in events])
            sink = "fallback"
        if sink == "fallback":
            log.warning("审计事件走本地降级文件，trace_id=%s", state["trace_id"])
        return {"events": events, "audit_sink": sink}
