"""
节点：最终化

在 graph 执行结束时：
1. 可选追加兜底声明
2. 保存对话到 AgentExternalMemory
3. 保存 graph state 用于后续恢复
"""
from app.services.graph.state import GraphState
from app.services.graph.tools.agent_memory import AgentExternalMemory
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def finalize_node(state: GraphState) -> dict:
    """
    最终化处理：追加声明（如需要）、保存会话、设置 FINISH 状态。
    """
    reply_text = state.reply_text or ""
    reflection_passed = state.reflection_passed
    reflection_count = state.reflection_count or 0
    max_retries = state.max_reflection_retries or 2
    session_id = state.session_id or ""
    user_input = state.user_input or state.question or ""

    # 如果反思未通过且已超过最大重试，用人工客服兜底替换回复
    if not reflection_passed and reflection_count >= max_retries:
        reply_text = (
            "抱歉，我没能查询到准确的结果。\n\n"
            "建议您回复「转人工」，由人工客服为您核实处理，这样能更快解决您的问题。"
        )
        logger.info("反思多次不通过，替换为人工客服引导回复")

    # 保存对话到外部记忆
    if session_id:
        try:
            AgentExternalMemory.append_chat(session_id=session_id, role="user", content=user_input)
            AgentExternalMemory.append_chat(session_id=session_id, role="assistant", content=reply_text)
            AgentExternalMemory.save_task_state(session_id, state)
            # 同步 collected_slots 和 missing_slots 到 session meta，确保多轮对话状态不丢失
            AgentExternalMemory.save_slots(
                session_id=session_id,
                collected_slots=state.collected_slots or {},
                missing_slots=state.missing_slots or [],
            )
            logger.info("会话记忆已保存: session=%s", session_id)
        except Exception as e:
            logger.warning("保存会话记忆失败: %s", e)

    logger.info(
        "Graph执行完成: session=%s, reflection_passed=%s, retries=%d, reply_len=%d",
        session_id, reflection_passed, reflection_count, len(reply_text),
    )

    return {
        "reply_text": reply_text,
        "stage": "FINISH",
        "error_msg": "",
    }
