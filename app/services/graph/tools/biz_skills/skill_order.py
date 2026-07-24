from app.services.skill.base import BaseSkill, query_all_order_info
from app.services.skill.wrapper import get_order
from app.utils.logging_config import get_logger

logger = get_logger(__name__)



class OrderSkill(BaseSkill):
    name = "query_order"
    desc = """
    [单号查订单] 只有当用户提供了具体的订单编号(如 OD2026... 这类字母+数字组合)时, 才调用本工具查询详情。
    功能: 根据准确的 order_no 查询该笔订单的精确状态和物流信息。
    参数说明:
        order_no: 用户提供的具体订单编号, 必填;
        user_id: 当前对话用户id, 系统自动传入。
    约束: 必须严格遵守以下规则!
        1. [死命令] 如果用户没有提供具体的订单号, 绝对禁止调用本工具, 且绝对不能编造假单号!
        2. 如果用户问的是"所有订单/全部订单/我的订单/查我的全部", 请调用 query_all_order 工具。
        3. 如果用户问的是"所有快递/全部物流/所有包裹", 请调用 query_all_logistics 工具。
        4. 如果用户只说了商品名(比如"查一下恒温热水壶到哪了"), 请调用 query_logistics_by_goods 工具。
        约束: 绝对禁止将 G 开头的商品 ID 误认为订单 ID!
    """

    def run(self, user_id: str, order_no: str, **kwargs):
        logger.info("======进入订单查询工具 run 方法======")
        return get_order(order_no=order_no, user_id=user_id)


class AllOrderSkill(BaseSkill):
    name = "query_all_order"
    desc = """
    [强制触发工具] 用户询问: 查我的所有订单、全部订单、我的订单、有哪些订单、买过什么、查我全部订单时, 必须调用本工具。
    功能: 根据user_id一次性查询该用户名下全部订单, 返回完整的订单列表(含订单号、商品名、金额、状态)。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入, 无需用户提供。
    约束: 拿到全部订单数据后直接汇总回答, 禁止再调用其他订单工具。
    """

    def run(self, user_id: str, **kwargs):
        logger.info("=====进入批量查询全部订单工具 run(同步) =====")
        result = query_all_order_info(user_id=user_id)
        return result
