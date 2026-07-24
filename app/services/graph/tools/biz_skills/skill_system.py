from app.services.skill.base import BaseSkill
from app.db.crud import create_service_ticket as create_ticket
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class TransferHumanSkill(BaseSkill):
    name = "transfer_human"
    desc = """
    [强制触发 -- 最高优先级] 用户明确说"转人工"、"找真人"、"人工客服"、"投诉"、"我要投诉"时, 或用户情绪明显激动、反复表达不满时, 必须立即调用本工具。
    功能: 自动创建人工服务工单, 将用户标记为待人工接管状态。
    参数: 无需额外参数, user_id 和 session_id 系统自动注入。
    约束: 只在用户明确要求或情绪激动时触发, 不能替代正常业务查询; 调用后不再调用其他工具。
    """

    def run(self, **kwargs):
        db = kwargs.get("db")
        user_id = kwargs.get("user_id", "unknown")
        session_id = kwargs.get("session_id", "unknown")

        # 自动创建工单
        ticket_id = None
        if db:
            try:
                ticket = create_ticket(
                    db=db,
                    user_id=user_id,
                    session_id=session_id,
                    content="用户请求转人工客服",
                )
                ticket_id = ticket.ticket_id
                logger.info("自动创建工单: ticket_id=%s, user=%s", ticket_id, user_id)
            except Exception as e:
                logger.error("创建工单失败: %s", e)

        return {
            "text": (
                "您的诉求我已经明确记录了, 已为您创建工单(编号: {})。"
                "正在为您呼叫人工客服, 请稍候。由于当前咨询量较大, 可能需要排队几分钟, 请您保持在线, 感谢您的理解。"
            ).format(ticket_id or "待分配"),
            "reply": (
                "您的诉求我已经明确记录了, 已为您创建工单(编号: {})。"
                "正在为您呼叫人工客服, 请稍候。由于当前咨询量较大, 可能需要排队几分钟, 请您保持在线, 感谢您的理解。"
            ).format(ticket_id or "待分配"),
            "action": "transfer_human",
            "ticket_id": ticket_id,
        }


class FallbackSkill(BaseSkill):
    name = "fallback_query"
    desc = """
    [兜底工具 -- 最低优先级] 仅当用户提问不属于任何其他工具的范围时调用(如: 问候、闲聊、自我介绍、感谢、道别等)。
    触发场景: "你好"、"你是谁"、"你能做什么"、"谢谢"、"再见"等。
    功能: 友好回应并介绍自己的能力范围, 引导用户说出具体业务需求。
    参数: 无需额外参数。
    约束: 只要用户意图匹配其他任何工具的触发条件, 就绝对不能调用本工具。
    """

    def run(self, **kwargs):
        return {
            "text": (
                '您好! 我是小美, 您的专属AI客服~ 我可以帮您:\n'
                '- 查询订单状态和物流轨迹\n'
                '- 查看会员等级和积分\n'
                '- 申请退货退款\n'
                '- 查询售后工单进度\n'
                '- 解答退换货政策和保修规则\n\n'
                '如果您需要人工客服, 随时告诉我"转人工"就可以哦~ 请问有什么可以帮您的?'
            ),
            "reply": (
                '您好! 我是小美, 您的专属AI客服~ 我可以帮您:\n'
                '- 查询订单状态和物流轨迹\n'
                '- 查看会员等级和积分\n'
                '- 申请退货退款\n'
                '- 查询售后工单进度\n'
                '- 解答退换货政策和保修规则\n\n'
                '如果您需要人工客服, 随时告诉我"转人工"就可以哦~ 请问有什么可以帮您的?'
            ),
        }
