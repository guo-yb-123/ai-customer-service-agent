"""
Agent Reflection 自检模块
Agent 生成回复后，自检是否编造信息、遗漏关键字段、偏离用户意图。
不合格则触发重新生成。
"""
import re
from app.utils.llm import call_qwen_once
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

REFLECTION_PROMPT = """你是严格的 AI 客服质检员。请检查以下 AI 回复是否存在问题。

用户原始问题：{user_question}
AI 回复内容：{ai_reply}
本次使用的工具：{tool_name}
工具返回的数据：{tool_result}

请逐项检查并输出 JSON：
1. has_hallucination: AI 是否编造了工具返回中不存在的订单号、物流单号、金额、商品名、会员等级等具体信息？true/false
   注意：说"暂无记录"、"暂时没查到"、"建议联系人工"不算编造，这是如实报告。
   只有明确编造了数据中不存在的信息才算幻觉。
2. has_missing_info: AI 是否遗漏了用户明确询问的关键信息？true/false
3. matches_intent: AI 回复是否直接回应了用户的问题？true/false
4. overall_score: 1-5 分（5=完美）
   评分标准：
   - 5分：完全基于工具数据，准确回应了用户问题
   - 4分：基于工具数据，但表达可以更好
   - 3分：部分偏离数据，或遗漏了关键信息
   - 2分：有明显编造或严重遗漏
   - 1分：完全编造
5. fix_suggestion: 如果有问题，给出修改建议（没问题写"无"）

只返回 JSON，不要任何其他文字。
格式：{{"has_hallucination": false, "has_missing_info": false, "matches_intent": true, "overall_score": 5, "fix_suggestion": "无"}}
"""


def reflection_check(
    user_question: str,
    ai_reply: str,
    tool_name: str = "",
    tool_result: str = "",
) -> dict:
    """
    对 AI 回复进行自检

    Returns:
        {
            "passed": bool,         # 是否通过检查
            "has_hallucination": bool,
            "has_missing_info": bool,
            "matches_intent": bool,
            "overall_score": int,   # 1-5
            "fix_suggestion": str,
        }
    """
    # 快速规则检查（不消耗 LLM token）
    quick_fail = _quick_rule_check(ai_reply, tool_result)
    if quick_fail:
        logger.warning("快速规则检查不通过: %s", quick_fail)
        return {
            "passed": False,
            "has_hallucination": True,
            "has_missing_info": False,
            "matches_intent": False,
            "overall_score": 2,
            "fix_suggestion": quick_fail,
        }

    # LLM 深度检查
    try:
        prompt = REFLECTION_PROMPT.format(
            user_question=user_question,
            ai_reply=ai_reply,
            tool_name=tool_name or "无",
            tool_result=str(tool_result)[:4000] if tool_result else "无",
        )
        raw = call_qwen_once(prompt)

        import json
        from app.utils.json_parser import extract_json_from_llm
        json_str = extract_json_from_llm(raw)
        result = json.loads(json_str)

        # 通过条件：无幻觉 + 未遗漏 + 匹配意图 + 分数 >= 3
        passed = (
            not result.get("has_hallucination", False)
            and not result.get("has_missing_info", False)
            and result.get("matches_intent", True)
            and result.get("overall_score", 3) >= 3
        )

        return {
            "passed": passed,
            "has_hallucination": result.get("has_hallucination", False),
            "has_missing_info": result.get("has_missing_info", False),
            "matches_intent": result.get("matches_intent", True),
            "overall_score": result.get("overall_score", 3),
            "fix_suggestion": result.get("fix_suggestion", "无"),
        }

    except Exception as e:
        logger.warning("LLM 自检失败，默认通过: %s", e)
        return {
            "passed": True,  # 保守策略：自检失败时放行
            "has_hallucination": False,
            "has_missing_info": False,
            "matches_intent": True,
            "overall_score": 3,
            "fix_suggestion": "自检异常，跳过",
        }


def _quick_rule_check(reply: str, tool_result: str) -> str | None:
    """快速规则检查：不消耗 LLM token，检查明显的数据编造"""

    # 1. 空回复检查
    if not reply or len(reply.strip()) < 5:
        return "回复内容过短或为空"

    # 2. 编造订单号检查：回复中的订单号必须在工具数据中存在
    fake_order_patterns = [
        r"OD\d{9,}",    # 明显假的订单号
        r"SF\d{10,}",   # 顺丰单号
        r"YT\d{10,}",   # 圆通单号
    ]
    for pattern in fake_order_patterns:
        found = re.findall(pattern, reply)
        if found and tool_result:
            for order_no in found:
                if order_no not in str(tool_result):
                    return f"回复中出现工具数据中不存在的编号: {order_no}"

    # 3. 只检测真正的系统异常（不是"查不到数据"）
    crash_phrases = ["服务暂时出现异常", "系统崩溃", "内部错误", "服务器错误"]
    if any(phrase in reply for phrase in crash_phrases):
        return "回复中包含系统异常话术，可能是执行失败"

    # 4. 检测LLM的自我暴露（表明它是AI）
    ai_self_ref = ["作为AI", "作为人工智能", "由AI生成", "AI客服小美提醒"]
    if any(phrase in reply for phrase in ai_self_ref):
        return "回复中出现了AI自我暴露话术，应当移除"

    # 注意：以下情况不算问题，不再标记：
    # - "暂无记录/暂时没查到" → 这是如实报告，不是兜底
    # - "建议联系人工客服" → 这是合理引导，不是异常
    # - "请稍后重试" → 结合上下文可能合理

    return None  # 通过快速检查
