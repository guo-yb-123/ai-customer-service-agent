"""
LangGraph 专用 API 端点

- /chat/graph: 完整 graph 调用（同步）
- /chat/graph/stream: 流式 graph 执行
- /admin/approvals: 审批管理
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langgraph.types import Command

from app.db.database import get_db
from app.services.graph import get_compiled_graph, GraphState
from app.services.graph.tools.agent_memory import AgentExternalMemory
from app.utils.redis_client import redis_client
from app.utils.logging_config import get_logger
from app.utils.input_sanitizer import (
    validate_session_id, validate_user_id, validate_question
)
import config

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["LangGraph Agent"])


class GraphChatRequest(BaseModel):
    session_id: str
    question: str
    user_id: str


class ApprovalAction(BaseModel):
    reason: str = ""


# ===== Graph 调用端点 =====

@router.post("/chat/graph")
def chat_graph(
    body: GraphChatRequest,
):
    """
    使用 LangGraph 处理对话（同步模式）。

    返回格式与 /chat/local 兼容：
    {
        "reply": "...",
        "stage": "FINISH" | "FILL_SLOT" | "APPROVAL",
        "approval_id": "...",    # 仅在 stage=APPROVAL 时
        "ticket_id": "...",
        "action": "...",
        "error_msg": "..."
    }
    """
    sid = validate_session_id(body.session_id)
    uid = validate_user_id(body.user_id)
    question = validate_question(body.question)

    # 初始化会话
    session_key = f"agent:session:{sid}"
    if not redis_client.exists(session_key):
        AgentExternalMemory.init_session(sid, uid)

    # 获取会员等级
    member_level = _fetch_member_level(uid)

    # 加载历史
    memory = AgentExternalMemory.load_session_meta(sid)
    chat_history = memory.get("chat_history", [])
    extracted_slots = memory.get("extracted_slots", {})

    # 构建初始 state
    initial_state = GraphState(
        session_id=sid,
        user_id=uid,
        user_input=question,
        question=question,
        member_level=member_level,
        chat_history=chat_history,
        collected_slots={"user_id": uid, **extracted_slots},
        max_reflection_retries=config.MAX_REFLECTION_RETRIES,
    )

    graph = get_compiled_graph()
    config_dict = {"configurable": {"thread_id": sid}}

    try:
        # 执行 graph（可能因 interrupt 而提前返回）
        final_state = graph.invoke(initial_state, config_dict)

        # 只在追问中保留槽位，对话完成则清空
        stage = final_state.get("stage", "")
        if stage == "FILL_SLOT":
            AgentExternalMemory.save_slots(
                session_id=sid,
                collected_slots=final_state.get("collected_slots", {}),
                missing_slots=final_state.get("missing_slots", []),
            )
        else:
            AgentExternalMemory.save_slots(sid, {}, [])
            # 清空 checkpointer 残留状态，防止跨话题污染
            try:
                graph.update_state(config_dict, {"collected_slots": {}, "missing_slots": [], "tool_name": None})
            except Exception:
                pass

        response = {
            "reply": final_state.get("reply_text", ""),
            "stage": final_state.get("stage", "FINISH"),
            "error_msg": final_state.get("error_msg", ""),
        }

        # 检查是否有中断（审批等待）
        if "__interrupt__" in final_state:
            interrupts = final_state["__interrupt__"]
            if interrupts:
                interrupt_data = interrupts[0].value if hasattr(interrupts[0], 'value') else interrupts[0]
                response["action"] = "approval_required"
                response["approval_id"] = interrupt_data.get("approval_id", "")
                response["stage"] = "APPROVAL"
                logger.info("Graph 审批中断: approval_id=%s", interrupt_data.get("approval_id"))

        # 传递额外字段
        for field in ("task_id", "ticket_id", "action"):
            val = final_state.get(field)
            if val and field not in response:
                response[field] = val

        return response

    except Exception as e:
        error_str = str(e)
        # GraphInterrupt 会在 langgraph 调用中表现为特定异常
        if "GraphInterrupt" in type(e).__name__ or "interrupt" in error_str.lower():
            logger.info("Graph 被中断（审批），session=%s", sid)
            # 中断时返回审批信息
            return {
                "reply": "您的操作已提交审核，请稍候...",
                "stage": "APPROVAL",
                "action": "approval_required",
                "error_msg": "",
            }

        logger.exception("Graph 执行异常 session=%s: %s", sid, e)
        return {
            "reply": "服务暂时出现异常，请稍后重试",
            "stage": "FINISH",
            "error_msg": error_str,
        }


@router.post("/chat/graph/stream")
async def chat_graph_stream(
    body: GraphChatRequest,
):
    """
    使用 LangGraph 处理对话（流式模式）。

    返回 SSE 事件流，包含每个节点的执行状态。
    """
    from fastapi.responses import StreamingResponse

    sid = validate_session_id(body.session_id)
    uid = validate_user_id(body.user_id)
    question = validate_question(body.question)

    session_key = f"agent:session:{sid}"
    if not redis_client.exists(session_key):
        AgentExternalMemory.init_session(sid, uid)

    member_level = _fetch_member_level(uid)
    memory = AgentExternalMemory.load_session_meta(sid)
    chat_history = memory.get("chat_history", [])
    extracted_slots = memory.get("extracted_slots", {})
    missing_slots = memory.get("missing_slots", [])

    initial_state = GraphState(
        session_id=sid,
        user_id=uid,
        user_input=question,
        question=question,
        member_level=member_level,
        chat_history=chat_history,
        collected_slots={"user_id": uid, **extracted_slots},
        missing_slots=missing_slots,
        max_reflection_retries=config.MAX_REFLECTION_RETRIES,
    )

    graph = get_compiled_graph()
    config_dict = {"configurable": {"thread_id": sid}}

    async def event_stream():
        try:
            for event in graph.stream(initial_state, config_dict, stream_mode="updates"):
                for node_name, state_update in event.items():
                    # 推送节点名称（终端可显示进度）
                    yield f"data: {json.dumps({'type': 'node', 'node': node_name})}\n\n"

                    # 推送非 LLM 生成的回复文本（追问、审批提示）
                    if node_name in ("prompt_slot", "check_sensitive"):
                        reply = state_update.get("reply_text", "")
                        if reply:
                            yield f"data: {json.dumps({'type': 'reply', 'content': reply})}\n\n"

            # 获取最终状态并保存槽位
            final_state = graph.get_state(config_dict)
            if final_state and final_state.values:
                vals = final_state.values
                reply = vals.get("reply_text", "")
                if reply:
                    yield f"data: {json.dumps({'type': 'reply', 'content': reply})}\n\n"
                # 只在追问中保留槽位，对话完成则清空
                stage = vals.get("stage", "")
                if stage == "FILL_SLOT":
                    AgentExternalMemory.save_slots(
                        session_id=sid,
                        collected_slots=vals.get("collected_slots", {}),
                        missing_slots=vals.get("missing_slots", []),
                    )
                else:
                    AgentExternalMemory.save_slots(sid, {}, [])
                    try:
                        graph.update_state(config_dict, {"collected_slots": {}, "missing_slots": [], "tool_name": None})
                    except Exception:
                        pass

            yield f"data: {json.dumps({'type': 'end'})}\n\n"

        except Exception as e:
            error_str = str(e)
            if "interrupt" in error_str.lower():
                # 审批中断：从 checkpointer 获取审批提示
                try:
                    interrupted_state = graph.get_state(config_dict)
                    if interrupted_state and interrupted_state.values:
                        reply = interrupted_state.values.get("reply_text", "")
                        if reply:
                            yield f"data: {json.dumps({'type': 'reply', 'content': reply})}\n\n"
                except Exception:
                    pass
                yield f"data: {json.dumps({'type': 'interrupt', 'message': '等待审批'})}\n\n"
            else:
                logger.exception("Graph 流式执行异常: %s", e)
                yield f"data: {json.dumps({'type': 'error', 'message': error_str})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ===== 审批管理端点 =====

@router.get("/admin/approvals")
def list_pending_approvals():
    """
    列出所有待审批的操作。

    Returns:
        list[dict]: 待审批记录列表
    """
    approvals = []
    try:
        for key in redis_client.scan_iter("approval:*"):
            data = redis_client.get(key)
            if data:
                try:
                    record = json.loads(data)
                    if record.get("status") == "pending":
                        approvals.append(record)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning("扫描审批记录失败: %s", e)

    # 按创建时间倒序
    approvals.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return approvals


@router.post("/admin/approvals/{approval_id}/approve")
def approve_action(approval_id: str, body: ApprovalAction = ApprovalAction()):
    """
    批准指定的待审批操作。

    批准后，对应的 graph 会恢复执行。
    """
    redis_key = f"approval:{approval_id}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(status_code=404, detail="审批记录不存在或已过期")

    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="审批记录格式错误")

    if record.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"审批记录状态为 {record.get('status')}，无法操作")

    session_id = record.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="审批记录缺少 session_id")

    # 恢复 graph 执行
    try:
        _resume_graph(session_id, {"approved": True})
    except Exception as e:
        logger.exception("恢复 graph 失败: %s", e)
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {str(e)}")

    logger.info("审批已批准: approval_id=%s, session=%s", approval_id, session_id)
    return {"success": True, "message": "操作已批准，Agent 已继续执行"}


@router.post("/admin/approvals/{approval_id}/reject")
def reject_action(approval_id: str, body: ApprovalAction = ApprovalAction()):
    """
    拒绝指定的待审批操作。

    拒绝后，graph 会继续执行并生成拒绝回复。
    """
    redis_key = f"approval:{approval_id}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(status_code=404, detail="审批记录不存在或已过期")

    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="审批记录格式错误")

    if record.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"审批记录状态为 {record.get('status')}，无法操作")

    session_id = record.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="审批记录缺少 session_id")

    # 恢复 graph 执行（拒绝）
    try:
        _resume_graph(session_id, {"approved": False, "reason": body.reason})
    except Exception as e:
        logger.exception("恢复 graph 失败: %s", e)
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {str(e)}")

    logger.info("审批已拒绝: approval_id=%s, session=%s, reason=%s",
                 approval_id, session_id, body.reason)
    return {"success": True, "message": "操作已拒绝"}


# ===== 内部辅助函数 =====

def _fetch_member_level(user_id: str) -> str | None:
    """从业务微服务获取会员等级"""
    import requests
    import os
    docker_env = os.getenv("DOCKER_ENV", "0") == "1"
    api_base = "http://business_api:8001" if docker_env else "http://127.0.0.1:8001"

    try:
        resp = requests.get(
            f"{api_base}/api/crm/customer",
            params={"user_id": user_id},
            timeout=3,
        )
        if resp.status_code == 200:
            info = resp.json()
            return info.get("member_level")
    except Exception:
        pass
    return None


def _resume_graph(session_id: str, resume_value: dict):
    """
    恢复被中断的 graph 执行。

    Args:
        session_id: 会话ID（用作 thread_id）
        resume_value: 传给 interrupt 的恢复值，如 {"approved": True}
    """
    graph = get_compiled_graph()
    config_dict = {"configurable": {"thread_id": session_id}}

    # 使用 Command(resume=...) 恢复执行
    # LangGraph 会从中断点继续，并将 resume_value 返回给 interrupt() 调用处
    result = graph.invoke(
        Command(resume=resume_value),
        config_dict,
    )

    logger.info("Graph 恢复执行完成: session=%s, stage=%s",
                 session_id, result.get("stage", "?"))
    return result
