# 工单处置 Agent

基于 **LangChain + LangGraph + MCP** 的多智能体工单处置系统：路由 → 专家 Agent（订单查询 / 知识问答 / 合规风控）→ 确定性规则门禁 → 转人工 → 审计回放。详见 [需求文档.md](需求文档.md) 与 [docs/项目计划.md](docs/项目计划.md)。

## 技术栈

| 组件 | 选型 |
|---|---|
| 编排 | LangGraph 1.x（SQLite Checkpoint，缺失时退化为内存） |
| Agent 框架 | LangChain Core（结构化输出、工具绑定） |
| 工具网关 | MCP（stdio + JSON-RPC 2.0，4 个只读工具） |
| 结构化库 | MySQL 8（`project1028`） |
| 向量库 | Qdrant（集合 `knowledge_chunks`，1024 维，Cosine） |
| 向量模型 | OpenAI 兼容 `/v1/embeddings`（1024 维） |
| 服务 | FastAPI + Uvicorn |

## 目录结构

```
app/
├── api/          # 接入层：路由与 DTO 转换
├── service/      # 业务层：编排、降级、门禁
├── agent/        # LangGraph 状态图、节点、MCP 工具绑定
├── repository/   # 数据访问：MySQL / Qdrant / 缓存
├── mapper/       # SQL、DDL、payload 与行→实体映射
├── client/       # MySQL / Qdrant / Embedding / MCP 客户端与服务端
├── entity/       # 数据实体与接口 DTO
├── model/        # LLM 工厂 + 离线脚本模型
├── util/         # 配置、日志、规则引擎、文本、时间
└── script/       # 初始化 / 演示 / 回归 / 自检脚本
conf/             # settings.json、risk_rules.json、intents.json、mcp.json、seed/
prompts/          # router / clarify / order / knowledge / compliance / summary
docs/             # 项目计划、代码评审报告
data/             # 运行时产物：checkpoint、审计降级文件、MCP 日志
```

## 快速开始

```bash
pip install -r requirements.txt
copy .env.example .env        # 按实际环境填写
python -m app.script.init_mysql     # 建表 + 种子数据（幂等）
python -m app.script.init_qdrant    # 建集合 + 向量化知识库（幂等）
python -m app.script.selftest --online
python -m app.script.regression     # 质量门禁，FAIL 时退出码 1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后这样访问：

| 入口 | 说明 |
|---|---|
| `http://127.0.0.1:8000/` | 服务索引页（自包含 HTML，不依赖 CDN，列全部接口与 curl 示例） |
| `http://127.0.0.1:8000/docs` | Swagger 交互文档（需要能访问 jsdelivr CDN，打不开就用 `/` 或 `/healthz`） |
| `http://127.0.0.1:8000/healthz` | MySQL / Qdrant / Embedding / LLM 状态 |

> 改动代码或重新初始化数据后必须**重启 uvicorn 进程**才会生效（未开 `--reload`）。

单轮演示：

```bash
python -m app.script.demo "订单 SO20261028001 现在到哪了？"
python -m app.script.demo "保温杯我不想要了，能不能直接退 99 元给我？" --user u1002
```

> 数据库/向量库地址全部来自 `.env`：换环境只改 `MYSQL_*`、`QDRANT_*`、`EMBEDDING_*`，代码不动。远端库不可达时服务会降级（审计落 `data/audit_fallback.jsonl`、工单落缓存、查询如实反馈“业务系统不可用”），不会编造数据。

## 配置

所有配置走环境变量（`.env`），阈值、规则、意图、门禁在 `conf/*.json`，改配置不改代码：

| 变量 | 说明 |
|---|---|
| `MYSQL_HOST/PORT/USER/PASSWORD/DB` | 结构化数据源 |
| `QDRANT_URL/COLLECTION/DIM` | 向量库与集合 |
| `EMBEDDING_BASE_URL/MODEL/DIM` | 向量模型（OpenAI 兼容） |
| `LLM_BASE_URL/API_KEY/MODEL` | 大模型；**留空则使用离线脚本模型**，链路仍可演示与回归 |

`conf/settings.json`：路由阈值、退款灰色地带、连续失败 N、检索 top_k/最低分、缓存 TTL、门禁通过率。
`conf/risk_rules.json`：三类强制转人工规则 + 禁止承诺模式（rewrite / handoff）。
`conf/intents.json`：5 类意图与专家映射。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 对话入口，返回 `status`(ANSWERED/CLARIFY/HANDOFF)、答复、意图、引用、转人工信息 |
| POST | `/api/ticket` | 工单入口（同上，含 `ticket_id`） |
| GET | `/api/audit/{trace_id}` | 审计回放，还原“为什么转人工” |
| GET | `/api/handoff?status=OPEN` | 转人工工单列表 |
| POST | `/api/handoff/{ticket_id}/action` | 人工确认/退回/修改，幂等键去重 |
| POST | `/api/eval/regression` | 跑 15 条回归集 + 质量门禁 |
| GET | `/healthz` | MySQL / Qdrant / Embedding / LLM 状态 |

## 处置链路

```
缓存检查 → router（结构化输出）→ 低置信/多意图 → clarify（追问，最多 3 轮）
                                   ├─ order_query/ticket_progress → order_expert（MCP: query_order/query_ticket/query_user_orders）
                                   ├─ knowledge_qa → knowledge_expert（MCP: search_knowledge，低分拒答）
                                   └─ refund/complaint → compliance_expert（MCP: search_knowledge）
          → guard（确定性规则：退款灰色地带 / 连续失败 / 显式人工 / 禁止承诺）→ handoff（打包工单）→ audit（逐节点落库）
```

模型只能生成答复草稿；**是否转人工由 guard 的代码规则决定**，模型自述“已转人工”不会改变系统状态。

## 数据初始化

- MySQL：`orders`、`tickets`、`handoff_tickets`、`audit_logs`、`regression_cases`、`idempotency_keys`；种子见 `conf/seed/*.jsonl`（12 订单 / 6 工单 / 2 转人工 / 3 审计样本 / 15 回归用例）。
- Qdrant：`knowledge_chunks`，1024 维 Cosine，12 篇知识文档切成 13 个分块，ID 为确定性 UUID（重复初始化幂等）。

## 已知限制（v1 有意为之）

1. **Redis 未提供地址**：缓存、转人工工单、连续失败计数使用进程内 TTL 存储，接口在 `cache_repository`，替换 Redis 只改一个类（服务重启会丢缓存与计数）。
2. **MCP 为最小实现**：仅覆盖 initialize / tools/list / tools/call，未接官方 SDK；工具均为只读，写操作走人工工作台接口。
3. **Checkpoint**：本机缺少 `langgraph-checkpoint-sqlite` 依赖时自动退化为内存 Checkpointer；`requirements.txt` 已给出可用的版本组合，装好后即启用 SQLite 持久化。
4. **离线脚本模型**：未配置 `LLM_API_KEY` 时使用确定性替身（`app/model/scripted.py`），用于演示与回归，不代表生产回答质量。
5. **未接真实 ERP**：订单/工单均为合成数据，不执行任何资金操作。

## 验证

```bash
python -m app.script.selftest --online   # 规则/指纹/缓存/映射/分块/图路由 + Qdrant 检索
python -m app.script.regression          # 15 条回归集 + 高风险漏转 + 审计完整性门禁
python -m app.script.api_smoke           # 25 项 HTTP 接口冒烟（默认打 http://127.0.0.1:8000）
```

| 验证项 | 结果 |
|---|---|
| 离线自检 | 5/5 通过 |
| 在线自检（含 Qdrant 检索） | 6/6 通过 |
| 回归 + 门禁 | 15/15 通过（100%），高风险漏转 0/4，门禁 PASS |
| 接口冒烟（25 项） | 25/25 通过（页面/健康检查/OpenAPI/对话三类意图/缓存命中/多轮追问/参数校验/工单/审计/转人工列表/人工动作幂等与 404/回归接口） |
| MySQL 初始化 | 6 张表 + 12 订单 / 6 工单 / 2 转人工 / 15 用例 / 3 审计样本，幂等重跑 |
| Qdrant 初始化 | 集合 `knowledge_chunks`（1024 维 Cosine）+ 13 个分块，幂等重跑 |
| HTTP 接口 | `/healthz`、`/api/chat`、`/api/ticket`、`/api/audit/{trace_id}`、`/api/handoff`、`/api/handoff/{id}/action`、`/api/eval/regression` 全部通过；人工动作幂等（第二次 `idempotent: true`）、不存在工单返回 404 |

> 验证环境说明：远端 MySQL `111.230.143.239:3306` 从本机 TCP 不可达，验证改用本机 MySQL 8.0.26（`MYSQL_HOST=127.0.0.1`）；Qdrant 与向量模型使用远端服务验证；未提供 LLM Key，生成走离线脚本模型。详见 [docs/代码评审报告.md](docs/代码评审报告.md)。

