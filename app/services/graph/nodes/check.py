"""
节点：槽位校验

检查当前意图所需的必填参数是否已全部收集。
缺失时路由到追问节点，完整时路由到执行节点。
"""
from app.services.graph.state import GraphState
from app.services.graph.slot_schemas import get_required_slots
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def check_slots_node(state: GraphState) -> dict:
    """
    校验槽位是否完整。

    返回值用于条件边判断：missing_slots 非空 → prompt_slot
    """
    intent = state.intent or "fallback_query"
    collected = state.collected_slots or {}
    required = get_required_slots(intent)
    missing = [s for s in required if not collected.get(s)]

    if intent == "clarify":
        # LLM 无法判断意图，需要引导用户
        logger.info("槽位校验: 意图不明，需要引导用户")
        return {
            "missing_slots": ["intent"],
            "pending_slot": "intent",
            "stage": "FILL_SLOT",
        }

    if missing:
        logger.info("槽位校验: 意图=%s, 缺失=%s", intent, missing)
        return {
            "missing_slots": missing,
            "pending_slot": missing[0],
            "stage": "FILL_SLOT",
        }

    logger.info("槽位校验: 意图=%s, 所有槽位已收集", intent)
    return {
        "missing_slots": [],
        "pending_slot": None,
        "stage": "EXECUTE",
    }
