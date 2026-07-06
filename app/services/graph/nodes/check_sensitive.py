"""
节点：检查是否为敏感操作

判断当前技能是否需要人工审批。
敏感操作 → 路由到 approval 节点
普通操作 → 路由到 generate_reply 节点
"""
from app.services.graph.state import GraphState
from app.services.graph.slot_schemas import is_sensitive
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def check_sensitive_node(state: GraphState) -> dict:
    """
    判断当前操作是否需要人工审批。

    如果 approval_status 已经是 "approved" 或 "rejected"，则跳过。
    如果需要审批，预先设置友好的等待回复。
    """
    tool_name = state.tool_name or ""
    approval_status = state.approval_status

    # 操作中文映射
    SKILL_CN_MAP = {
        "initiate_return_by_goods": "退货申请",
        "submit_ticket": "创建工单",
    }

    # 已审批通过的，直接跳过
    if approval_status == "approved":
        logger.info("操作 %s 已获审批，跳过审批节点", tool_name)
        return {
            "approval_required": False,
            "stage": "EXECUTE",
        }

    # 已拒绝的
    if approval_status == "rejected":
        skill_cn = SKILL_CN_MAP.get(tool_name, tool_name)
        logger.info("操作 %s 审批被拒绝", tool_name)
        return {
            "approval_required": False,
            "reply_text": f"抱歉，您的{skill_cn}未能通过审核。如有疑问，请联系人工客服。",
            "stage": "FINISH",
        }

    # 判断是否为敏感操作
    if is_sensitive(tool_name):
        skill_cn = SKILL_CN_MAP.get(tool_name, tool_name)
        user_id = state.user_id or ""
        logger.info("操作 %s 需要人工审批", tool_name)
        return {
            "approval_required": True,
            "stage": "APPROVAL",
            "reply_text": (
                f"好的，我已收到您的{skill_cn}请求～\n\n"
                f"为了保障您的权益，{skill_cn}需要人工客服审核确认。"
                f"已为您提交审核，请稍候。"
                f"客服人员会尽快处理，审核通过后将自动为您完成后续操作。\n\n"
                f"⏳ 如有疑问，也可以直接联系人工客服哦～"
            ),
        }

    logger.info("操作 %s 无需审批", tool_name)
    return {
        "approval_required": False,
        "stage": "EXECUTE",
    }
