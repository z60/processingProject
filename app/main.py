"""FastAPI 应用装配。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.client.embedding_client import EmbeddingClient
from app.client.qdrant_client import QdrantClient
from app.repository.ticket_repository import TicketRepository
from app.util.config import settings
from app.util.log import get_logger

log = get_logger("main")

INDEX_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>工单处置 Agent</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;line-height:1.7;color:#222}
code{background:#f3f3f3;padding:1px 5px;border-radius:4px}
td{padding:4px 12px 4px 0;vertical-align:top}</style></head>
<body>
<h1>工单处置 Agent</h1>
<p>服务已启动。本页不依赖外部 CDN；交互式接口文档见 <a href="/docs">/docs</a>，
依赖状态见 <a href="/healthz">/healthz</a>。</p>
<table>
<tr><td><code>POST /api/chat</code></td><td>对话入口，返回 status（ANSWERED / CLARIFY / HANDOFF）</td></tr>
<tr><td><code>POST /api/ticket</code></td><td>工单入口（同上）</td></tr>
<tr><td><code>GET /api/audit/{trace_id}</code></td><td>审计回放</td></tr>
<tr><td><code>GET /api/handoff?status=OPEN</code></td><td>转人工工单列表</td></tr>
<tr><td><code>POST /api/handoff/{ticket_id}/action</code></td><td>人工确认 / 退回 / 修改</td></tr>
<tr><td><code>POST /api/eval/regression</code></td><td>回归集与质量门禁</td></tr>
<tr><td><code>GET /healthz</code></td><td>MySQL / Qdrant / Embedding / LLM 状态</td></tr>
</table>
<p>示例：<code>curl -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d "{\\"text\\":\\"我要转人工\\",\\"user_id\\":\\"u1001\\"}"</code></p>
</body></html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    conf = settings()
    log.info("服务启动：env=%s，LLM=%s", conf.env, "on" if conf.llm_enabled else "offline")
    if not conf.llm_enabled:
        log.warning("未配置 LLM_API_KEY，当前使用离线脚本模型，仅供演示/回归，不得用于生产")
    yield
    log.info("服务关闭")


def create_app() -> FastAPI:
    conf = settings()
    app = FastAPI(
        title="工单处置 Agent",
        version="1.0.0",
        description="LangChain + LangGraph + MCP 多智能体协同",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/", response_class=HTMLResponse, summary="服务索引（浏览器可直接打开）")
    def index() -> str:
        return INDEX_PAGE

    @app.get("/healthz", summary="依赖健康检查")
    def healthz() -> dict:
        mysql_ok = TicketRepository().ping()

        qdrant = QdrantClient()
        try:
            qdrant_ok = qdrant.collection_exists()
        except Exception:  # noqa: BLE001 - 健康检查不抛异常
            qdrant_ok = False
        finally:
            qdrant.close()

        embedding = EmbeddingClient()
        try:
            embedding_ok = len(embedding.embed_one("健康检查")) == conf.embedding_dim
        except Exception:  # noqa: BLE001
            embedding_ok = False
        finally:
            embedding.close()

        return {
            "status": "ok" if mysql_ok and qdrant_ok and embedding_ok else "degraded",
            "mysql": mysql_ok,
            "qdrant": qdrant_ok,
            "embedding": embedding_ok,
            "llm": "configured" if conf.llm_enabled else "offline-scripted",
            "env": conf.env,
        }

    return app


app = create_app()
