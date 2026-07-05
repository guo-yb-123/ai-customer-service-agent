from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import requests
import json
import os
from app.services.graph.tools.agent_core import escape_brace
from app.db.database import get_db
from app.utils.redis_client import redis_client
from app.utils.llm import call_qwen_stream
from app.utils.embedding import build_rag_prompt
from app.services.graph.tools.agent_memory import AgentExternalMemory
from app.services.graph.tools.agent_core import agent_main_run
from app.utils.logging_config import get_logger
from app.utils.input_sanitizer import (
    validate_session_id, validate_user_id, validate_question, sanitize_text,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["对话管理"])

# 【修复 1】根据环境动态获取业务微服务地址，不再写死 127.0.0.1
DOCKER_ENV = os.getenv("DOCKER_ENV", "0") == "1"
BUSINESS_API_BASE = "http://business_api:8001" if DOCKER_ENV else "http://127.0.0.1:8001"


class LocalChatRequest(BaseModel):
    session_id: str
    question: str
    user_id: str


@router.post("/local")
def chat_local(
        body: LocalChatRequest,
        db: Session = Depends(get_db),
):
    # 输入校验
    sid = validate_session_id(body.session_id)
    uid = validate_user_id(body.user_id)
    question = validate_question(body.question)

    # 1. 会话不存在则初始化
    session_key = f"agent:session:{sid}"
    if not redis_client.exists(session_key):
        AgentExternalMemory.init_session(sid, uid)

    # ========== 前置拉取CRM会员上下文 ==========
    # 【修复 2】初始值必须设为 None，绝不能给 "普通用户"，否则大模型会被误导！
    member_level = None
    try:
        resp_customer = requests.get(
            f"{BUSINESS_API_BASE}/api/crm/customer",
            params={"user_id": uid},
            timeout=3
        )
        # 只有当请求返回 200 状态码时，才真正尝试读取会员等级
        if resp_customer.status_code == 200:
            customer_info = resp_customer.json()
            member_level = customer_info.get("member_level")
        else:
            logger.warning(f"CRM接口返回非200状态码: {resp_customer.status_code}")
    except Exception as e:
        # 发生任何网络异常，member_level 依然保持为 None
        logger.warning(f"CRM接口网络异常 session={sid}, user={uid}, err={str(e)}")

    # ========== 调用Agent主调度，传入已查询会员等级 ==========
    try:
        msg_obj = agent_main_run(
            session_id=sid,
            user_id=uid,
            user_query=question,
            db=db,
            max_tool_round=3,
            member_level=member_level  # 👈 这里现在传入的是 None 或者真正查到的等级
        )

        reply_text = msg_obj.content if hasattr(msg_obj, 'content') else str(msg_obj)

        response_data = {
            "reply": reply_text,
            "error_msg": ""
        }

        if hasattr(msg_obj, "task_id") and msg_obj.task_id:
            response_data["task_id"] = msg_obj.task_id
        if hasattr(msg_obj, "ticket_id") and msg_obj.ticket_id:
            response_data["ticket_id"] = msg_obj.ticket_id
        if hasattr(msg_obj, "action") and msg_obj.action:
            response_data["action"] = msg_obj.action

        return response_data

    except Exception as e:
        logger.exception(f"Agent调度全局异常 session_id={sid}, user_id={uid}")
        return {
            "reply": "服务暂时出现异常，请稍后重试",
            "error_msg": str(e)
        }


class StreamChatRequest(BaseModel):
    session_id: str
    question: str
    user_id: str


@router.post("/stream")
async def stream_chat(
        body: StreamChatRequest,
        db: Session = Depends(get_db),
):
    uid = body.user_id
    question = body.question
    sid = body.session_id
    session_key = f"agent:session:{sid}"
    if not redis_client.exists(session_key):
        AgentExternalMemory.init_session(sid, uid)

    if any(k in question for k in ["所有订单", "查我的全部", "有什么订单", "全部订单", "我的订单"]):
        async def async_gen():
            yield f"data: {json.dumps({'type': 'async_task'})}\n\n"

        return StreamingResponse(async_gen(), media_type="text/event-stream")

    # 构建 RAG 提示词（走知识库）— build_rag_prompt 返回 (prompt, docs)
    rag_prompt, rag_docs = build_rag_prompt(question)
    prompt = escape_brace(rag_prompt)

    def stream_generator():
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        for chunk in call_qwen_stream(prompt):
            if chunk:
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")