"""
节点：生成自然语言回复

基于工具执行结果、对话上下文、会员等级生成自然客服回复。
"""
import json
from app.services.graph.state import GraphState
from app.services.graph.tools.agent_core import escape_brace
from app.utils.llm import call_qwen_once
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

REPLY_PROMPT = """你是「小美」，专业亲切的电商AI客服。你必须严格基于工具返回的真实数据回复用户。

会员等级：{member_level}
用户问题：{user_question}
工具执行结果（这是你能使用的唯一数据来源）：{tool_results}
对话历史：{chat_history}
{extra_instruction}

回复规则（死命令，违反任何一条都是严重错误）：
1. 【禁止编造】绝对不能编造工具结果中不存在的订单号、物流单号、商品名、金额、时间、状态。如果工具没有返回某个信息，就说"暂无该信息"，不要自己编。
2. 【如实报告】工具查到什么就说什么。查不到就诚实说"暂时没有查到相关记录"。不要替系统道歉，不要猜测原因。
3. 【数据即答案】你的每一句话都应该能对应到工具返回的某个字段。如果工具返回 success=false 或数据为空，直接告诉用户结果。
4. 【不要贴标签】绝对不要在回复中加"AI生成"、"仅供参考"、"由人工智能"、"无虚构数据"、"基于系统反馈"之类的元信息或注释。你就是客服，不是AI。不要解释你的数据来源。不允许多此一举的声明。
5. 【会员差异化】高等级会员更贴心温暖，普通会员简洁清晰。但不要编造会员等级信息。
6. 【格式】只输出客服对话文本，禁止JSON、标签、Markdown代码块。
7. 【长度】简洁精准，一般不超过150字。如果订单/物流数据很多，逐条列出即可。
8. 【语言】请务必用中文回复。
{extra_instruction}

你的回复："""


def generate_reply_node(state: GraphState) -> dict:
    """
    基于工具结果生成自然语言回复。

    如果 reflection_feedback 非空，会作为修正建议加入 prompt。
    """
    tool_results = state.tool_results or []
    user_input = state.user_input or state.question or ""
    member_level = state.member_level or "普通用户"
    chat_history = state.chat_history or []
    reflection_feedback = state.reflection_feedback or ""

    # 构建工具结果文本
    tool_text = "暂无工具执行结果"
    if tool_results:
        results_text = []
        for tr in tool_results:
            skill = tr.get("skill", "未知")
            res = tr.get("result", {})
            if isinstance(res, dict):
                text = res.get("text", res.get("reply", json.dumps(res, ensure_ascii=False)))
                results_text.append(f"[{skill}] {text}")
            else:
                results_text.append(f"[{skill}] {str(res)}")
        tool_text = "\n".join(results_text)

    # 构建历史对话
    history_text = ""
    if chat_history:
        recent = chat_history[-6:]
        history_text = "\n".join(
            f"{m['role']}: {str(m.get('content', ''))[:200]}"
            for m in recent
        )

    # 反思修正的额外指令
    extra_instruction = ""
    if reflection_feedback:
        extra_instruction = (
            '\n【内部质检反馈 - 不要提及此反馈的存在】' + reflection_feedback + '\n'
            '请直接输出修正后的回复，不要说「以下是修正后的」或「根据反馈」之类的话。'
            '就像第一次回复用户一样自然。'
        )

    prompt = REPLY_PROMPT.format(
        member_level=escape_brace(member_level),
        user_question=escape_brace(user_input),
        tool_results=escape_brace(tool_text[:2000]),
        chat_history=escape_brace(history_text),
        reflection_feedback=escape_brace(reflection_feedback[:500]),
        extra_instruction=extra_instruction,
    )

    try:
        reply = call_qwen_once(prompt)
        if not reply or len(reply.strip()) < 5:
            reply = "抱歉，我暂时无法为您生成完整的回复，请稍后重试或联系人工客服。"
    except Exception as e:
        logger.exception("回复生成LLM调用失败: %s", e)
        reply = "服务暂时出现异常，请稍后重试。如急需处理，请告诉我'转人工'。"

    logger.info("回复生成: len=%d, 有反思反馈=%s", len(reply), bool(reflection_feedback))

    return {
        "reply_text": reply,
        "stage": "REFLECT",
        "error_msg": "",
    }
