# AI 智能客服 Agent

基于 **LangGraph** 的多节点状态机 AI Agent，支持槽位填充、人工审批、反思自检。LLM 自主判断用户意图，从 7 个业务工具中自动选择并执行，集成 RAG 知识库检索和多模型自动降级。

## 架构

```
用户 → FastAPI → LangGraph StateGraph
                      │
           ┌──────────┼──────────┐
           ↓          ↓          ↓
      意图识别    槽位填充    条件路由
           ↓          ↓          ↓
      订单查询    物流跟踪    会员服务
           ↓          ↓          ↓
      售后工单    RAG知识库   转人工兜底
           │          │          │
           └──────────┼──────────┘
                      ↓
              Business API → MySQL
                      ↓
        PostgreSQL (会话记忆 + pgvector 向量库)
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **LangGraph 状态机** | 9 节点图：意图提取 → 槽位校验 → 技能执行 → 敏感检测 → 人工审批 → 回复生成 → 反思自检 → 最终化 |
| **槽位填充** | 用户信息不完整时自动追问，如「我要退货」→「请问您要退哪件商品呢？」 |
| **人工审批** | 退货、创建工单等敏感操作自动暂停，等待客服工作台审核后继续执行 |
| **反思自检** | 回复前校验：是否编造数据、是否遗漏关键信息、是否匹配用户意图。不通过则自动重试 |
| **多模型自动降级** | qwen-max → qwen-plus → deepseek-r1 → qwen-plus-latest → qwen3-235b-a22b，token 耗尽自动切换 |
| **RAG 混合检索** | pgvector 向量检索 + 全文检索 + Re-rank 重排序 |
| **会话记忆** | Redis + PostgreSQL 双层存储，支持多轮对话上下文 |
| **转人工闭环** | 情绪识别 → 自动创建工单 → WebSocket 推送客服工作台 |

## 能做什么

| 场景 | 用户说什么 | Agent 做什么 |
|------|-----------|-------------|
| 查订单 | "我的所有订单" | 调 `query_all_order` → 返回完整订单列表（含金额） |
| 查物流 | "智能电饭煲到哪了" | 调 `query_logistics_by_goods` → 模糊匹配商品→查物流轨迹 |
| 退货 | "退掉恒温热水壶" | 调 `initiate_return_by_goods` → 自动匹配订单→提交审批→人工确认 |
| 查会员 | "我的积分多少" | 调 `query_crm_user_info` → 返回等级/积分/订单数 |
| 政策咨询 | "退换货流程是什么" | 调 `query_knowledge_base` → pgvector RAG 检索 |
| 转人工 | "转人工" | 调 `transfer_human` → 自动创建工单 |

## 快速开始

### Docker 一键启动

```bash
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY=sk-xxx
docker compose up -d
```

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置（MySQL 等本地服务需自行启动）
cp .env.example .env
# 至少填入 DASHSCOPE_API_KEY

# 3. 启动主 API（端口 8000）
python main.py

# 4. 启动业务 API（端口 8001）
python business_api/main.py

# 5. 启动 Web 对话界面（端口 8502）
streamlit run chat_ui.py --server.port 8502
```

### 浏览器访问

| 页面 | 地址 |
|------|------|
| Web 对话界面 | `http://localhost:8502` |
| 客服工作台（人工审批） | `http://localhost:8000/admin/admin.html` |
| 主 API 文档 (Swagger) | `http://localhost:8000/docs` |
| 业务 API 文档 | `http://localhost:8001/docs` |

## 项目结构

```
├── main.py                    # FastAPI 入口
├── config.py                  # 配置（环境变量驱动）
├── chat_ui.py                 # Streamlit Web 对话界面
├── docker-compose.yml         # 一键启动全部服务
├── Dockerfile
│
├── app/
│   ├── api/                   # REST + WebSocket
│   │   ├── chat.py            # /chat/local, /chat/stream
│   │   ├── graph.py           # /chat/graph (LangGraph), /admin/approvals
│   │   ├── task.py            # 异步任务轮询
│   │   ├── admin.py           # 客服工作台 API + 审批管理
│   │   └── ws.py              # WebSocket (任务推送 + 管理员审批通知)
│   ├── services/graph/        # LangGraph Agent 核心
│   │   ├── langgraph_agent.py # StateGraph 定义 (9 节点 + 条件路由)
│   │   ├── state.py           # GraphState (31 字段)
│   │   ├── slot_schemas.py    # 意图→槽位映射 + 敏感操作定义
│   │   ├── checkpoint.py      # PostgresSaver / MemorySaver
│   │   ├── nodes/             # 图节点实现
│   │   │   ├── extract.py     # 意图识别
│   │   │   ├── check.py       # 槽位校验
│   │   │   ├── prompt_slot.py # 追问生成
│   │   │   ├── execute.py     # 技能执行
│   │   │   ├── check_sensitive.py # 敏感操作检测
│   │   │   ├── approval.py    # 人工审批 (LangGraph interrupt)
│   │   │   ├── generate.py    # 回复生成
│   │   │   ├── reflect.py     # 反思自检
│   │   │   └── finalize.py    # 最终化 + 会话保存
│   │   └── tools/
│   │       ├── agent_core.py  # Agent 主调度
│   │       ├── agent_memory.py # 会话记忆
│   │       ├── agent_reflection.py # 自检模块
│   │       ├── biz_skills/    # 7 个业务 Skill
│   │       └── prompts/       # 系统提示词
│   ├── db/                    # 数据库模型 (PostgreSQL)
│   └── utils/                 # LLM/RAG/鉴权/限流/熔断/模型降级
│
├── business_api/main.py       # 业务微服务（订单/CRM/物流/商品/售后）
├── config/prompts/            # 提示词 YAML（热加载）
└── data/                      # 测试数据 SQL
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/chat/local` | POST | Agent 对话 |
| `/api/v1/chat/stream` | POST | 流式对话 |
| `/api/v1/chat/graph` | POST | LangGraph Agent 对话 |
| `/api/v1/chat/graph/stream` | POST | LangGraph 流式对话 |
| `/api/v1/admin/tickets` | GET | 工单列表 |
| `/api/v1/admin/approvals` | GET | 待审批列表 |
| `/api/v1/admin/approvals/{id}/approve` | POST | 批准操作 |
| `/api/v1/admin/approvals/{id}/reject` | POST | 拒绝操作 |
| `/api/v1/ws/task/{task_id}` | WS | 任务状态推送 |
| `/api/v1/ws/admin` | WS | 管理员审批通知 |

## 技术栈

- **框架**: FastAPI + LangGraph + Celery + Streamlit
- **LLM**: 阿里云 DashScope (DeepSeek / Qwen 系列，自动降级)
- **数据库**: PostgreSQL (会话) + pgvector (向量) + MySQL (业务)
- **缓存**: Redis (会话状态 / 消息队列 / 审批记录)
- **部署**: Docker Compose 一键启动




