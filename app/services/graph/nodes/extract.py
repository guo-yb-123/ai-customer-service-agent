"""
节点：提取用户意图 + 参数槽位

LLM 分析用户输入，识别意图并从对话中提取可用参数。
"""
import json
from app.services.graph.state import GraphState
from app.services.graph.slot_schemas import get_required_slots
from app.utils.llm import call_qwen_once
from app.utils.json_parser import extract_json_from_llm
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

INTENT_EXTRACT_PROMPT = """你是AI客服的意图识别模块。根据用户输入和对话历史，判断用户意图并提取参数。

可用意图列表（含触发场景）：
- query_all_order: 查所有订单（"所有订单/我的订单/全部订单/买过什么/订了什么"）
- query_order: 查单笔订单详情（用户必须提供了 order_no 订单编号）
- query_all_logistics: 查所有物流（"所有快递/全部物流/包裹/快递到哪了/物流到哪了/我的快递" — 没给单号时用这个）
- query_logistics_by_goods: 按商品名查物流（用户提到了具体商品名，如"热水壶到哪了"）
- query_single_logistics: 按快递单号查物流（用户提供了 tracking_no 快递单号）
- initiate_return_by_goods: 按商品名退货（"退货/退款/想退/申请退" 需要 goods_name）
- submit_ticket: 创建售后工单（用户提供了 order_no 和 problem_desc）
- query_all_aftersale: 查所有售后记录（"所有售后/售后记录/退款进度/工单"）
- query_single_aftersale: 查单条售后详情（用户提供了 aftersale_no）
- query_crm: 查会员积分/等级（"积分/会员/等级/我的账户"）
- query_all_goods: 查所有购买过的商品（"买过的商品/全部商品"）
- query_single_goods: 查商品详情（用户提供了 goods_id）
- query_knowledge_base: 政策/规则咨询（"退货政策/保修/怎么退/规则/流程/多久/政策"）
- transfer_human: 转人工/投诉（"转人工/人工客服/投诉/找真人/我要投诉"）
- fallback_query: 问候/闲聊/感谢/道别（"你好/谢谢/再见/能做什么"）
- clarify: 实在无法判断意图时使用（优先匹配上述意图）

已收集到的参数：{collected_slots}
缺失的参数槽位：{missing_slots}
对话历史：{chat_history}
会员等级：{member_level}
用户当前输入：{user_input}

请输出纯JSON（不要markdown包裹）：
{{
  "intent": "意图名称",
  "extracted_params": {{"order_no": "OD2026001", ...}},
  "confidence": "high/medium/low"
}}

判断规则（重要）：
1. "快递/物流到哪了/在哪/到哪里" 没给单号 → intent=query_all_logistics
2. "退货/退款/想退/申请退" 没给商品名 → intent=initiate_return_by_goods, goods_name留空
3. "投诉/我要投诉" → intent=transfer_human
4. "积分/会员/等级/账户" → intent=query_crm
5. 尽量匹配具体意图，不要轻易返回 clarify。只有完全无法判断时才用 clarify。
6. 多轮对话上下文：如果缺失槽位(missing_slots)不为空，说明上一轮AI问了用户一个问题，
   用户这次输入大概率是在回答那个问题。此时应保持上一轮的 intent 不变，
   只从用户输入中提取缺失的参数值补入 extracted_params。
   例如：上一轮AI问"您要退哪件商品？"，用户回复"恒温热水壶"，
   此时 intent 仍应为 initiate_return_by_goods，goods_name="恒温热水壶"。
如果用户这次输入补全了缺失的参数，请在 extracted_params 中体现。
只返回JSON，不要任何其他文字。
请务必用中文输出（JSON的value值用中文）。"""


def extract_intent_node(state: GraphState) -> dict:
    """
    从用户输入中提取意图和参数。

    返回需要更新的 state 字段。
    """
    user_input = state.user_input or state.question
    collected = state.collected_slots or {}
    missing = state.missing_slots or []
    chat_history = state.chat_history or []
    member_level = state.member_level or "普通用户"

    # 构建简化的历史上下文
    history_text = ""
    if chat_history:
        recent = chat_history[-6:]  # 最近 6 轮
        history_text = "\n".join(
            f"{m['role']}: {str(m.get('content', ''))[:200]}"
            for m in recent
        )

    prompt = INTENT_EXTRACT_PROMPT.format(
        collected_slots=json.dumps(collected, ensure_ascii=False),
        missing_slots=json.dumps(missing, ensure_ascii=False),
        chat_history=history_text,
        member_level=member_level,
        user_input=user_input,
    )

    try:
        raw = call_qwen_once(prompt)
        json_str = extract_json_from_llm(raw)
        result = json.loads(json_str)
    except Exception as e:
        logger.warning("意图提取LLM调用失败: %s，兜底为fallback", e)
        return {
            "intent": "fallback_query",
            "collected_slots": collected,
            "missing_slots": [],
            "user_input": user_input,
        }

    intent = result.get("intent", "fallback_query")
    extracted = result.get("extracted_params", {})
    confidence = result.get("confidence", "medium")

    # 合并新提取的参数到 collected_slots
    for k, v in extracted.items():
        if v and v != "未知" and v != "null":
            collected[k] = v

    # 计算仍缺失的槽位
    required = get_required_slots(intent)
    still_missing = [s for s in required if not collected.get(s)]

    logger.info(
        "意图提取: intent=%s, confidence=%s, collected=%s, missing=%s",
        intent, confidence, collected, still_missing,
    )

    return {
        "intent": intent,
        "collected_slots": collected,
        "missing_slots": still_missing,
        "user_input": user_input,
        "stage": "EXTRACT",
    }
