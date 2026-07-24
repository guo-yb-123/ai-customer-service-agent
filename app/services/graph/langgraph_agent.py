"""
LangGraph Agent — 客服主图定义

构建并编译带检查点持久化的 StateGraph，实现：
1. 多步骤意图路由 + 槽位填充
2. 敏感操作人工审批（Human-in-the-Loop）
3. 回复反思 + 重试循环
"""
from langgraph.graph import StateGraph, END

from app.services.graph.state import GraphState
from app.services.graph.checkpoint import get_checkpointer
from app.services.graph.nodes import (
    extract_intent_node,
    check_slots_node,
    prompt_slot_node,
    execute_skill_node,
    check_sensitive_node,
    approval_node,
    generate_reply_node,
    reflect_node,
    finalize_node,
)
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# ===== 条件边路由函数 =====


def route_after_check_slots(state: GraphState) -> str:
    """槽位校验后的路由：缺失 → 追问，完整 → 执行"""
    if state.missing_slots:
        logger.info("路由: check_slots → prompt_slot (缺失: %s)", state.missing_slots)
        return "prompt_slot"
    logger.info("路由: check_slots → execute_skill")
    return "execute_skill"


def route_after_execute(state: GraphState) -> str:
    """技能执行后的路由：异步/转人工 → 直接finalize，正常 → 检查敏感"""
    action = state.action or ""
    if action in ("async_task_pending", "transfer_human"):
        logger.info("路由: execute_skill → finalize (action=%s)", action)
        return "finalize"
    logger.info("路由: execute_skill → check_sensitive")
    return "check_sensitive"


def route_after_check_sensitive(state: GraphState) -> str:
    """敏感检查后的路由：需要审批 → approval，否则 → generate_reply"""
    # 已拒绝的情况
    if state.approval_status == "rejected":
        logger.info("路由: check_sensitive → finalize (已拒绝)")
        return "finalize"
    # 需要审批
    if state.approval_required and state.approval_status != "approved":
        logger.info("路由: check_sensitive → approval")
        return "approval"
    # 不需要审批或已审批
    logger.info("路由: check_sensitive → generate_reply")
    return "generate_reply"


def route_after_approval(state: GraphState) -> str:
    """审批后的路由：通过 → 执行技能，拒绝 → finalize"""
    if state.approval_status == "approved":
        logger.info("路由: approval → execute_skill (已批准)")
        return "execute_skill"
    logger.info("路由: approval → finalize (已拒绝)")
    return "finalize"


def route_after_reflect(state: GraphState) -> str:
    """反思后的路由：通过 → finalize，不通过且有重试 → generate_reply，不通过且无重试 → finalize"""
    if state.reflection_passed:
        logger.info("路由: reflect → finalize (通过)")
        return "finalize"
    reflection_count = state.reflection_count or 0
    max_retries = state.max_reflection_retries or 2
    if reflection_count <= max_retries:
        logger.info("路由: reflect → generate_reply (重新生成, 重试 %d/%d)", reflection_count, max_retries)
        return "generate_reply"
    logger.info("路由: reflect → finalize (超过最大重试 %d)", max_retries)
    return "finalize"


# ===== 构建 StateGraph =====

def build_agent_graph() -> StateGraph:
    """
    构建并编译客服 Agent 的 LangGraph 图。

    Returns:
        编译后的 StateGraph（带 checkpointer）。
    """
    # 创建图
    workflow = StateGraph(GraphState)

    # 添加节点
    workflow.add_node("extract_intent", extract_intent_node)
    workflow.add_node("check_slots", check_slots_node)
    workflow.add_node("prompt_slot", prompt_slot_node)
    workflow.add_node("execute_skill", execute_skill_node)
    workflow.add_node("check_sensitive", check_sensitive_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("generate_reply", generate_reply_node)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("finalize", finalize_node)

    # 设置入口
    workflow.set_entry_point("extract_intent")

    # 边：extract_intent → check_slots
    workflow.add_edge("extract_intent", "check_slots")

    # 条件边：check_slots → prompt_slot 或 execute_skill
    workflow.add_conditional_edges(
        "check_slots",
        route_after_check_slots,
        {
            "prompt_slot": "prompt_slot",
            "execute_skill": "execute_skill",
        },
    )

    # prompt_slot → END（等待用户输入）
    workflow.add_edge("prompt_slot", END)

    # 条件边：execute_skill → check_sensitive 或 finalize
    workflow.add_conditional_edges(
        "execute_skill",
        route_after_execute,
        {
            "check_sensitive": "check_sensitive",
            "finalize": "finalize",
        },
    )

    # 条件边：check_sensitive → approval 或 generate_reply 或 finalize
    workflow.add_conditional_edges(
        "check_sensitive",
        route_after_check_sensitive,
        {
            "approval": "approval",
            "generate_reply": "generate_reply",
            "finalize": "finalize",
        },
    )

    # 条件边：approval → execute_skill 或 finalize
    workflow.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "execute_skill": "execute_skill",
            "finalize": "finalize",
        },
    )

    # generate_reply → reflect
    workflow.add_edge("generate_reply", "reflect")

    # 条件边：reflect → finalize / generate_reply（重试）
    workflow.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "finalize": "finalize",
            "generate_reply": "generate_reply",
        },
    )

    # finalize → END
    workflow.add_edge("finalize", END)

    # 编译图（带检查点持久化）
    checkpointer = get_checkpointer()
    compiled_graph = workflow.compile(checkpointer=checkpointer)

    logger.info("LangGraph Agent 图编译完成 (节点数: 9, checkpointer: %s)",
                 type(checkpointer).__name__)

    return compiled_graph


# ===== 全局单例 =====
# 模块导入时编译一次，全局复用
_compiled_graph = build_agent_graph()


def get_compiled_graph():
    """获取编译后的 graph 单例"""
    return _compiled_graph
