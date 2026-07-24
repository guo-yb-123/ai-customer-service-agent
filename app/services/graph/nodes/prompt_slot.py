"""
节点：追问用户补充缺失参数

当槽位不完整时，生成自然追问让用户补充参数。
"""
import json
from app.services.graph.state import GraphState
from app.utils.llm import call_qwen_once
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

SLOT_PROMPT_TEMPLATE = """你是AI客服"小美"。用户的问题缺少一些必要信息，请友好地引导用户补充。

用户意图：{intent}
已收集到的信息：{collected_slots}
还需要用户提供：{missing_slots}

意图对应的追问场景：
- initiate_return_by_goods: 用户想退货，需要问"请问您要退哪件商品呢？"
- query_order: 用户想查订单，需要问"请提供一下您的订单编号（OD开头的数字）～"
- query_logistics_by_goods: 用户想查物流，需要问"请问您要查哪个商品的物流呢？"
- query_single_logistics: 用户想查物流，需要问"请提供一下您的快递单号～"
- submit_ticket: 用户想提交工单，需要问"请提供订单编号和问题描述～"
- clarify: 用户意图不明确，引导说出具体需求
- 其他意图：根据 missing_slots 中缺失的参数生成对应追问

请用亲切自然的语气回复。严格要求：
1. 一次只问最关键的 1-2 个信息
2. 绝对不要提及用户ID（user_id）、会员等级等技术信息
3. 语气亲切、简洁，不超过80字
4. 只输出客服回复文本，不要JSON、不要标签
5. 请务必用中文回复

你的回复："""


def prompt_slot_node(state: GraphState) -> dict:
    """
    生成追问用户的自然语言回复。

    返回的 reply_text 将直接返回给客户端。
    graph 执行到此节点后终止，等待用户下一轮输入。
    """
    intent = state.intent or "未知"
    collected = state.collected_slots or {}
    missing = state.missing_slots or []

    # 找到第一个缺失槽位的中文描述
    SLOT_CN_MAP = {
        "order_no": "订单编号",
        "goods_name": "商品名称",
        "tracking_no": "快递单号",
        "problem_desc": "问题描述",
        "aftersale_no": "售后单号",
        "goods_id": "商品ID",
        "intent": "具体需求",
    }
    missing_cn = [SLOT_CN_MAP.get(s, s) for s in missing]

    prompt = SLOT_PROMPT_TEMPLATE.format(
        intent=intent,
        collected_slots=json.dumps(collected, ensure_ascii=False),
        missing_slots=", ".join(missing_cn),
    )

    try:
        reply = call_qwen_once(prompt)
        if not reply or len(reply.strip()) < 5:
            reply = f"好的～为了帮您更好地处理，请问您能提供一下{'、'.join(missing_cn)}吗？"
    except Exception as e:
        logger.warning("槽位追问LLM调用失败: %s", e)
        reply = f"好的～为了帮您更好地处理，请问您能提供一下{'、'.join(missing_cn)}吗？"

    logger.info("槽位追问: missing=%s, reply=%s", missing, reply[:80])

    return {
        "reply_text": reply,
        "stage": "FILL_SLOT",
        "error_msg": "",
    }
