"""
节点：人工审批

使用 LangGraph 的 interrupt() 暂停 graph 执行，
等待人工客服在管理后台审批通过或拒绝。
"""
import json
import uuid
from datetime import datetime
from langgraph.types import interrupt
from app.services.graph.state import GraphState
from app.utils.redis_client import redis_client
from app.utils.logging_config import get_logger
import config

logger = get_logger(__name__)


def approval_node(state: GraphState) -> dict:
    """
    暂停 graph 执行，等待人工审批。

    interrupt() 会抛出 GraphInterrupt 异常，
    graph state 被保存到 checkpointer 中。
    审批完成后通过 Command(resume=...) 恢复执行。
    """
    tool_name = state.tool_name or "未知操作"
    tool_args = state.tool_args or {}
    user_id = state.user_id or ""
    session_id = state.session_id or ""
    user_input = state.user_input or state.question or ""

    # 生成审批ID
    approval_id = str(uuid.uuid4())[:12]

    # 构建审批记录
    approval_record = {
        "approval_id": approval_id,
        "session_id": session_id,
        "user_id": user_id,
        "skill": tool_name,
        "params": {k: v for k, v in tool_args.items() if k not in ("db", "user_id", "session_id")},
        "user_query": user_input,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "approved_at": None,
    }

    # 存储到 Redis（过期时间使用配置值）
    redis_key = f"approval:{approval_id}"
    redis_client.setex(
        name=redis_key,
        time=config.APPROVAL_TIMEOUT_SEC,
        value=json.dumps(approval_record, ensure_ascii=False),
    )

    logger.info(
        "审批节点: 暂停graph, approval_id=%s, skill=%s, session=%s",
        approval_id, tool_name, session_id,
    )

    # 操作中文映射
    SKILL_CN_MAP = {
        "initiate_return_by_goods": "退货申请",
        "submit_ticket": "创建工单",
    }
    skill_cn = SKILL_CN_MAP.get(tool_name, tool_name)

    # LangGraph interrupt: 暂停执行，返回中断信息
    interrupt_payload = {
        "type": "approval_required",
        "approval_id": approval_id,
        "skill": tool_name,
        "skill_cn": skill_cn,
        "summary": f"用户 {user_id} 请求{skill_cn}",
    }

    # 调用 interrupt — 这会使 graph 暂停并抛出 GraphInterrupt
    resume_value = interrupt(interrupt_payload)

    # ==== 以下是 graph 恢复后执行的代码 ====
    # resume_value 来自 Command(resume=...)
    if isinstance(resume_value, dict):
        approved = resume_value.get("approved", False)
    else:
        approved = bool(resume_value)

    # 更新 Redis 中的审批记录
    try:
        record = json.loads(redis_client.get(redis_key) or "{}")
        record["status"] = "approved" if approved else "rejected"
        record["approved_at"] = datetime.now().isoformat()
        redis_client.setex(
            name=redis_key,
            time=config.APPROVAL_TIMEOUT_SEC,
            value=json.dumps(record, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("更新审批记录失败: %s", e)

    if approved:
        logger.info("审批通过: approval_id=%s", approval_id)
        return {
            "approval_id": approval_id,
            "approval_status": "approved",
            "approval_required": False,
            "stage": "EXECUTE",
        }
    else:
        logger.info("审批拒绝: approval_id=%s", approval_id)
        return {
            "approval_id": approval_id,
            "approval_status": "rejected",
            "approval_required": False,
            "reply_text": f"抱歉，您的{skill_cn}未能通过审核。如有疑问，请联系人工客服或拨打客服热线。",
            "stage": "FINISH",
        }
