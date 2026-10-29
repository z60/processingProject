"""离线脚本模型：未配置 LLM_API_KEY 时的确定性替身。

只用于离线演示与回归，保证「无外部模型也能把链路跑通」；
生产环境由 model.llm.get_chat_model 返回真实 ChatOpenAI，行为由 Prompt 决定。
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.util.config import conf

_EXPLICIT_HUMAN = ("转人工", "人工客服", "找人工", "要人工", "叫客服")
_ESCALATION = ("起诉", "法院", "律师", "报警", "监管部门", "曝光")
_REFUND = ("退款", "退货", "退钱", "减免", "免单", "免息", "息费", "赔付", "额度", "征信")
_REFUND_RE = re.compile(r"(退|减|免)[^。；\n]{0,10}?\d+\s*(元|块)")
_POLICY = ("政策", "条款", "规则", "规定", "时效", "多久", "几天", "条件", "是什么", "怎么", "流程", "如何")
_REQUEST = ("能不能", "可以", "帮我", "直接退", "行不行", "给我")
_ORDER_MARK = ("订单", "运单", "发货", "到哪")
_TICKET_MARK = ("工单", "处理到")
_CONNECTOR = ("另外", "还有", "同时", "顺便", "以及")
_QUESTION = ("吗", "怎么", "如何", "什么")

_ORDER_NO_RE = re.compile(r"SO\d{8,}")
_TICKET_NO_RE = re.compile(r"TK\d{8,}")
_USER_ID_RE = re.compile(r"\bu\d{4}\b")


def classify(text: str) -> dict:
    """确定性路由：返回意图、置信度、风险标记与槽位。"""
    has = lambda words: any(w in text for w in words)  # noqa: E731
    refund_marker = has(_REFUND) or bool(_REFUND_RE.search(text))
    order_no = _ORDER_NO_RE.search(text)
    ticket_no = _TICKET_NO_RE.search(text)
    slots: dict[str, Any] = {}
    if order_no:
        slots["order_no"] = order_no.group(0)
    if ticket_no:
        slots["ticket_id"] = ticket_no.group(0)
    user = _USER_ID_RE.search(text)
    if user:
        slots["user_id"] = user.group(0)

    ambiguous = has(_CONNECTOR) and has(_REQUEST) and has(_QUESTION)

    if has(_EXPLICIT_HUMAN):
        return _intent("complaint", 0.82, True, slots, "用户显式要求人工")
    if has(_ESCALATION):
        return _intent("complaint", 0.66, True, slots, "命中法律/投诉升级话术")
    if ambiguous:
        return _intent("unknown", 0.55, True, slots, "多意图冲突，需要澄清")
    if order_no:
        return _intent("order_query", 0.92, False, slots, "带订单号的精确查询")
    if ticket_no:
        return _intent("ticket_progress", 0.90, False, slots, "带工单号的进度查询")
    if has(_REFUND) or refund_marker:
        if has(_POLICY):
            return _intent("knowledge_qa", 0.88, False, slots, "退款政策咨询")
        if has(_REQUEST):
            return _intent("refund", 0.72, True, slots, "退款诉求，置信度落在灰色地带")
        return _intent("refund", 0.85, True, slots, "退款诉求")
    if has(_ORDER_MARK):
        return _intent("order_query", 0.90, False, slots, "订单查询")
    if has(_TICKET_MARK):
        return _intent("ticket_progress", 0.88, False, slots, "工单进度查询")
    if has(_POLICY):
        return _intent("knowledge_qa", 0.86, False, slots, "知识问答")
    return _intent("unknown", 0.35, False, slots, "信息不足，需要澄清")


def _intent(intent: str, confidence: float, risk: bool, slots: dict, reason: str) -> dict:
    return {
        "intent": intent,
        "confidence": round(confidence, 2),
        "risk_flag": risk,
        "slots": slots,
        "reason": reason,
    }


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


class ScriptedChatModel(BaseChatModel):
    """按角色返回确定性消息的离线模型。"""

    role: str = "router"

    @property
    def _llm_type(self) -> str:
        return f"scripted-{self.role}"

    def bind_tools(
        self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any
    ) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if self.role == "router":
            text = _text_of(last)
            payload = classify(text)
            return AIMessage(content=json.dumps(payload, ensure_ascii=False))

        if self.role == "clarify":
            return AIMessage(content="请问您是想咨询相关规则政策，还是查询具体订单/退款进度？")

        if self.role == "summary":
            return AIMessage(content=f"用户诉求：{_text_of(last)[:50]}")

        if self.role in ("order_expert", "knowledge_expert", "compliance_expert"):
            if isinstance(last, ToolMessage):
                return AIMessage(content=self._final_answer(last))
            return self._tool_call(messages)

        return AIMessage(content="")

    def _tool_call(self, messages: list[BaseMessage]) -> AIMessage:
        human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        text = _text_of(human) if human else ""
        top_k = conf("settings")["knowledge"]["top_k"]
        order_no = _ORDER_NO_RE.search(text)
        ticket_no = _TICKET_NO_RE.search(text)
        user_id = _USER_ID_RE.search(text)

        if self.role == "order_expert":
            if order_no:
                return _tool("query_order", {"order_no": order_no.group(0)})
            if ticket_no:
                return _tool("query_ticket", {"ticket_id": ticket_no.group(0)})
            if user_id:
                return _tool("query_user_orders", {"user_id": user_id.group(0), "limit": 5})
            return AIMessage(content="请提供订单号或工单号，我来帮您查询。")
        return _tool("search_knowledge", {"query": text[:160], "top_k": top_k})

    def _final_answer(self, tool_message: ToolMessage) -> str:
        raw = _text_of(tool_message)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return "查询结果解析失败，请稍后重试或转人工。"

        if self.role == "order_expert":
            return _order_answer(payload)
        if payload.get("error"):
            return "知识库暂时不可用，无法核实条款，请稍后重试或转人工。"
        hits = payload.get("hits", [])
        if self.role == "knowledge_expert":
            return _knowledge_answer(hits)
        return _compliance_answer(hits)


def _tool(name: str, args: dict) -> AIMessage:
    import uuid

    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}],
    )


def _order_answer(payload: dict) -> str:
    if payload.get("error"):
        return "业务系统暂时不可用，无法查询该记录，请稍后重试或转人工。"
    if not payload.get("found"):
        subject = payload.get("order_no") or payload.get("ticket_id") or "该记录"
        return f"未查询到{subject}的记录，请确认单号是否正确。"
    order = payload.get("order")
    if order:
        extra = f"运单号：{order['logistics_no']}。" if order.get("logistics_no") else "尚未发货。"
        return (
            f"订单 {order['order_no']} 当前状态：{order['status']}，"
            f"商品：{order['product']}，可退款金额：{order['refundable_amount']} 元。{extra}"
        )
    ticket = payload.get("ticket")
    if ticket:
        return f"工单 {ticket['ticket_id']} 当前状态：{ticket['status']}，处理摘要：{ticket['summary'] or '暂无'}"
    orders = payload.get("orders") or []
    if not orders:
        return "未查询到您名下的订单记录，请确认账号是否正确。"
    detail = "；".join(f"{o['order_no']}（{o['status']}）" for o in orders)
    return f"共查询到 {len(orders)} 笔订单：{detail}。"


def _knowledge_answer(hits: list[dict]) -> str:
    threshold = conf("settings")["knowledge"]["min_score"]
    top = max((float(h.get("score", 0)) for h in hits), default=0.0)
    if not hits or top < threshold:
        return conf("risk_rules")["no_evidence_reply"]
    best = hits[0]
    snippet = best["text"][:120].strip()
    return f"{snippet}（来源：{best['source']}）"


def _compliance_answer(hits: list[dict]) -> str:
    base = "您的诉求已登记，具体处理结果需人工审核确认，客服不会在对话中承诺金额或时限。"
    if hits:
        return f"{base}可参考条款：{hits[0]['title']}。"
    return base
