"""LangGraph 状态图装配。"""

from __future__ import annotations

import sqlite3

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentNodes
from app.agent.state import AgentState
from app.util.config import conf, settings
from app.util.log import get_logger

log = get_logger("agent_graph")

EXPERT_ROUTES = {
    "order_expert": "order_expert",
    "knowledge_expert": "knowledge_expert",
    "compliance_expert": "compliance_expert",
}


def build_graph(nodes: AgentNodes):
    """节点依赖由外部注入，图结构固定。"""
    router_conf = conf("settings")["router"]
    expert_by_intent = {item["name"]: item["expert"] for item in conf("intents")["intents"]}

    def route_after_router(state: AgentState) -> str:
        intent = state.get("intent", "unknown")
        confidence = float(state.get("confidence") or 0.0)
        expert = expert_by_intent.get(intent)
        if intent == "unknown" or confidence < router_conf["min_confidence"] or not expert:
            return "clarify"
        return EXPERT_ROUTES[expert]

    def route_after_guard(state: AgentState) -> str:
        return "handoff" if state.get("handoff_trigger") else "audit"

    graph = StateGraph(AgentState)
    graph.add_node("router", nodes.router)
    graph.add_node("clarify", nodes.clarify)
    graph.add_node("order_expert", nodes.order_expert)
    graph.add_node("knowledge_expert", nodes.knowledge_expert)
    graph.add_node("compliance_expert", nodes.compliance_expert)
    graph.add_node("guard", nodes.guard)
    graph.add_node("handoff", nodes.handoff)
    graph.add_node("audit", nodes.audit)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "clarify": "clarify",
            "order_expert": "order_expert",
            "knowledge_expert": "knowledge_expert",
            "compliance_expert": "compliance_expert",
        },
    )
    for expert in EXPERT_ROUTES:
        graph.add_edge(expert, "guard")
    graph.add_edge("clarify", "guard")
    graph.add_conditional_edges("guard", route_after_guard, {"handoff": "handoff", "audit": "audit"})
    graph.add_edge("handoff", "audit")
    graph.add_edge("audit", END)
    return graph.compile(checkpointer=_checkpointer())


def _checkpointer():
    """优先 SQLite 持久化（F-22），依赖缺失时退化为内存。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = settings().data_dir / "checkpoint.sqlite3"
        connection = sqlite3.connect(str(path), check_same_thread=False)
        log.info("Checkpoint 使用 SQLite：%s", path)
        return SqliteSaver(connection)
    except Exception as exc:  # pragma: no cover - 依赖缺失时
        from langgraph.checkpoint.memory import InMemorySaver

        log.warning("SQLite Checkpointer 不可用（%s），退化为内存 Checkpointer", exc)
        return InMemorySaver()
