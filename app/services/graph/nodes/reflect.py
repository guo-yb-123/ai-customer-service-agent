"""
节点：反思自检

对生成的回复进行质量检查：是否编造信息、是否遗漏关键字段、是否匹配用户意图。
通过 → 进入 finalize，不通过 → 重试或兜底。
"""
import os
import json
from app.services.graph.state import GraphState
from app.services.graph.tools.agent_reflection import reflection_check
from app.utils.logging_config import get_logger
import config

logger = get_logger(__name__)


def reflect_node(state: GraphState) -> dict:
    """
    对生成的回复进行反思自检。

    返回 reflection_passed 和 reflection_feedback 用于条件路由。
    """
    reply_text = state.reply_text or ""
    user_input = state.user_input or state.question or ""
    tool_results = state.tool_results or []
    tool_name = state.tool_name or ""
    reflection_count = state.reflection_count or 0
    max_retries = state.max_reflection_retries or config.MAX_REFLECTION_RETRIES

    # 构建工具结果文本 — 优先使用 text 字段（LLM生成回复时用的数据源）
    tool_result_text = ""
    if tool_results:
        result = tool_results[-1].get("result", {}) if tool_results else {}
        if isinstance(result, dict):
            # 用 text 字段而非 str(result)，确保所有订单号都能被反思检查到
            tool_result_text = result.get("text", result.get("reply", "")) or json.dumps(result, ensure_ascii=False)
        else:
            tool_result_text = str(result)
        # 不截断 — 工具返回的所有数据都需要参与校验

    # 如果 ENABLE_REFLECTION 环境变量为 "0"，跳过反思
    if os.getenv("ENABLE_REFLECTION", "1") == "0":
        logger.info("反思已通过环境变量关闭，默认通过")
        return {
            "reflection_passed": True,
            "reflection_count": reflection_count,
            "reflection_feedback": "",
            "stage": "FINALIZE",
        }

    try:
        check = reflection_check(
            user_question=user_input,
            ai_reply=reply_text,
            tool_name=tool_name,
            tool_result=tool_result_text,
        )
    except Exception as e:
        logger.warning("反思检查异常，默认通过: %s", e)
        return {
            "reflection_passed": True,
            "reflection_count": reflection_count,
            "reflection_feedback": "",
            "stage": "FINALIZE",
        }

    passed = check.get("passed", True)
    new_count = reflection_count + 1

    if passed:
        logger.info("反思通过: score=%s", check.get("overall_score", "?"))
        return {
            "reflection_passed": True,
            "reflection_count": new_count,
            "reflection_feedback": "",
            "stage": "FINALIZE",
        }

    # 反思不通过
    feedback = check.get("fix_suggestion", "回复存在质量问题，请重新生成")
    can_retry = new_count < max_retries

    logger.warning(
        "反思不通过 (第%d次): score=%s, hallucination=%s, missing=%s, can_retry=%s, feedback=%s",
        new_count,
        check.get("overall_score", "?"),
        check.get("has_hallucination", False),
        check.get("has_missing_info", False),
        can_retry,
        feedback[:100],
    )

    if can_retry:
        # 不通过 → 重新生成回复（带上反思反馈作为修正指令）
        return {
            "reflection_passed": False,
            "reflection_count": new_count,
            "reflection_feedback": feedback,
            "stage": "GENERATE",
        }
    else:
        # 超过最大重试次数：用人工客服引导替换
        return {
            "reflection_passed": False,
            "reflection_count": new_count,
            "reflection_feedback": feedback,
            "stage": "FINALIZE",
        }
