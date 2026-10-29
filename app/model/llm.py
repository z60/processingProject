"""模型工厂：真实 LLM 与离线脚本模型二选一。"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.model.scripted import ScriptedChatModel
from app.util.config import settings


def get_chat_model(role: str) -> BaseChatModel:
    """role: router / clarify / order_expert / knowledge_expert / compliance_expert / summary。"""
    conf = settings()
    if not conf.llm_enabled:
        return ScriptedChatModel(role=role)
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的明确提示
        raise RuntimeError("已配置 LLM_API_KEY 但缺少 langchain-openai，请执行 pip install -r requirements.txt") from exc
    return ChatOpenAI(
        model=conf.llm_model,
        base_url=conf.llm_base_url or None,
        api_key=conf.llm_api_key,
        temperature=conf.llm_temperature,
        timeout=conf.llm_timeout,
    )
