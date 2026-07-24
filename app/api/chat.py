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
    validate_session_id, validate_user_id, validate_question
)
import config

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
    member_level = None
    try:
        resp_customer = requests.get(
            f"{BUSINESS_API_BASE}/api/crm/customer",
            params={"user_id": uid},
            timeout=3
        )
        if resp_customer.status_code == 200:
            customer_info = resp_customer.json()
            member_level = customer_info.get("member_level")
        else:
            logger.warning(f"CRM接口返回非200状态码: {resp_customer.status_code}")
    except Exception as e:
        logger.warning(f"CRM接口网络异常 session={sid}, user={uid}, err={str(e)}")

    # ========== LangGraph 功能开关 ==========
    if config.ENABLE_LANGGRAPH:
        return _run_langgraph_chat(sid, uid, question, member_level)

    # ========== 原有 Agent 调度（兜底） ==========
    return _run_legacy_chat(sid, uid, question, db, member_level)


def _run_langgraph_chat(session_id: str, user_id: str, question: str, member_level: str | None) -> dict:
    """使用 LangGraph 处理对话"""
    from app.services.graph import get_compiled_graph, GraphState

    memory = AgentExternalMemory.load_session_meta(session_id)
    chat_history = memory.get("chat_history", [])
    extracted_slots = memory.get("extracted_slots", {})
    missing_slots = memory.get("missing_slots", [])

    initial_state = GraphState(
        session_id=session_id,
        user_id=user_id,
        user_input=question,
        question=question,
        member_level=member_level,
        chat_history=chat_history,
        collected_slots={"user_id": user_id, **extracted_slots},
        missing_slots=missing_slots,
        max_reflection_retries=config.MAX_REFLECTION_RETRIES,
    )

    graph = get_compiled_graph()
    graph_config = {"configurable": {"thread_id": session_id}}

    try:
        final_state = graph.invoke(initial_state, graph_config)

        # 只在追问中保留槽位，对话完成则清空，防止跨话题污染
        stage = final_state.get("stage", "")
        if stage == "FILL_SLOT":
            AgentExternalMemory.save_slots(
                session_id=session_id,
                collected_slots=final_state.get("collected_slots", {}),
                missing_slots=final_state.get("missing_slots", []),
            )
        else:
            AgentExternalMemory.save_slots(session_id, {}, [])
            try:
                graph.update_state(graph_config, {"collected_slots": {}, "missing_slots": [], "tool_name": None})
            except Exception:
                pass

        response_data = {
            "reply": final_state.get("reply_text", ""),
            "error_msg": final_state.get("error_msg", ""),
        }

        # 检查是否有中断（审批等待）
        if "__interrupt__" in final_state:
            interrupts = final_state["__interrupt__"]
            if interrupts:
                interrupt_data = interrupts[0].value if hasattr(interrupts[0], 'value') else interrupts[0]
                response_data["action"] = "approval_required"
                response_data["approval_id"] = interrupt_data.get("approval_id", "")
                response_data["stage"] = "APPROVAL"
                logger.info("LangGraph 审批中断: approval_id=%s", interrupt_data.get("approval_id"))

        for field in ("task_id", "ticket_id", "action"):
            val = final_state.get(field)
            if val and field not in response_data:
                response_data[field] = val

        return response_data

    except Exception as e:
        error_str = str(e)
        if "GraphInterrupt" in type(e).__name__ or "interrupt" in error_str.lower():
            logger.info("LangGraph 被中断（审批等待），session=%s", session_id)
            return {
                "reply": "您的操作已提交审核，请稍候...",
                "action": "approval_required",
                "error_msg": "",
            }

        logger.exception("LangGraph 执行异常 session=%s: %s", session_id, e)
        return {
            "reply": "服务暂时出现异常，请稍后重试",
            "error_msg": error_str,
        }


def _run_legacy_chat(session_id: str, user_id: str, question: str, db: Session, member_level: str | None) -> dict:
    """使用原有 agent_main_run 处理对话（向后兼容）"""
    try:
        msg_obj = agent_main_run(
            session_id=session_id,
            user_id=user_id,
            user_query=question,
            db=db,
            max_tool_round=3,
            member_level=member_level,
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
        logger.exception(f"Agent调度全局异常 session_id={session_id}, user_id={user_id}")
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