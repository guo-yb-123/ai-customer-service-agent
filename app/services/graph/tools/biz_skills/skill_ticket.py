import requests
import config
from sqlalchemy.orm import Session
from app.db.crud import create_service_ticket
from app.services.skill.base import BaseSkill, query_all_aftersale_info, query_single_aftersale_info
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class TicketSkill(BaseSkill):
    name = "submit_ticket"
    desc = """
    [创建售后工单] 用户提供了订单号和问题描述, 明确要提交售后/报修/投诉时使用。
    参数: order_no(订单号)、problem_desc(问题描述), user_id和session_id系统自动注入。
    约束: 必须同时有订单号和问题描述才能调用; 如果用户只是咨询售后政策, 请调用 query_knowledge_base。
    """
    def run(self, db: Session, user_id: str, session_id: str, order_no: str, problem_desc: str, **kwargs):
        return create_service_ticket(db=db, user_id=user_id, session_id=session_id, order_no=order_no, problem_desc=problem_desc)


class AllAfterSaleSkill(BaseSkill):
    name = "query_all_aftersale"
    desc = """
    [强制触发] 用户询问: 我的所有售后、售后记录、退货单、退款进度、工单列表时, 必须调用本工具。
    功能: 根据user_id一次性查询该用户名下全部售后工单(含工单号、订单号、状态、创建时间)。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入。
    约束: 拿到售后数据后直接汇总回答; 如果用户问的是售后政策而非个人记录, 请调用 query_knowledge_base。
    """

    def run(self, user_id: str, **kwargs):
        logger.info("=====进入批量查询全部售后工单 run(同步) =====")
        result = query_all_aftersale_info(user_id=user_id)
        return result


class SingleAfterSaleSkill(BaseSkill):
    name = "query_single_aftersale"
    desc = """
    [强制触发] 用户提供售后单号、查询某一条售后详情、查售后单号xxx时, 调用本工具。
    功能: 根据user_id + 售后单号查询单条售后工单详情。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入;
        aftersale_no: 用户提供的售后单号, 必须传入。
    约束: 必须拿到用户给出的售后单号才能调用, 缺少单号则引导用户提供。
    """

    def run(self, user_id: str, aftersale_no: str, **kwargs):
        logger.info("查询单条售后: aftersale_no=%s", aftersale_no)
        res_json = query_single_aftersale_info(user_id=user_id, aftersale_no=aftersale_no)
        logger.info("单售后接口返回: success=%s", res_json.get("success"))
        return {
            "text": res_json.get("text", "查询失败, 无返回信息"),
            "aftersale_detail": res_json.get("data", {})
        }


class ReturnByGoodsSkill(BaseSkill):
    name = "initiate_return_by_goods"
    desc = """
    [按商品退货] 用户说: 我要退xxx商品、申请退款退东西、想退掉xxx, 且没有提供订单号时, 必须调用本工具。
    功能: 根据user_id和商品名称, 自动查找该商品所属的订单并提交退货工单。
    参数说明:
        user_id: 系统自动注入;
        goods_name: 用户描述要退货的商品名称。
    约束: 如果查到多个同名商品订单, 列出让用户选择; 如果只查到一个, 直接提交退货申请。
    """

    def run(self, user_id: str, goods_name: str, **kwargs):
        logger.info("按商品退货: goods_name=%s", goods_name)
        url = f"{config.INNER_ORDER_API}/api/order/query_by_goods"

        try:
            resp = requests.get(url=url, params={"user_id": user_id, "goods_name": goods_name}, timeout=5)
            if resp.status_code != 200:
                return {"text": f"查询订单异常, 接口返回状态码: {resp.status_code}"}

            res_json = resp.json()
            order_list = res_json.get("data", [])
            order_count = len(order_list)
            logger.info("找到 %s 笔包含 '%s' 的订单", order_count, goods_name)

            if order_count == 0:
                return {
                    "text": f"我这里没查到您买过「{goods_name}」的记录哦。可能是商品名有微小差异, 您方便把对应的订单号发给我吗?",
                    "reply": f"我这里没查到您买过「{goods_name}」的记录哦。可能是商品名有微小差异, 您方便把对应的订单号发给我吗?"
                }

            if order_count == 1:
                target_order = order_list[0]
                order_no = target_order.get("order_no")
                create_url = f"{config.INNER_ORDER_API}/api/ticket/create"
                create_res = requests.post(
                    url=create_url,
                    json={
                        "user_id": user_id,
                        "session_id": kwargs.get("session_id", ""),
                        "order_no": order_no,
                        "problem_desc": f"用户通过商品名发起退货, 商品: {goods_name}"
                    }
                )
                if create_res.status_code == 200:
                    create_json = create_res.json()
                    if create_json.get("success"):
                        return {
                            "text": f"查到您只有一笔包含「{goods_name}」的订单({order_no}), 已经直接帮您提交了退货申请!",
                            "reply": f"查到您只有一笔包含「{goods_name}」的订单({order_no}), 已经直接帮您提交了退货申请!"
                        }
                    else:
                        return {
                            "text": f"找到订单了, 但售后系统拒绝了请求: {create_json.get('error_msg', '未知错误')}。您可以稍后再试。",
                            "reply": f"找到订单了, 但售后系统拒绝了请求: {create_json.get('error_msg', '未知错误')}。您可以稍后再试。"
                        }
                else:
                    return {
                        "text": f"找到订单了, 但连接售后系统时遇到了网络故障(状态码 {create_res.status_code}), 您可以稍后再试。",
                        "reply": f"找到订单了, 但连接售后系统时遇到了网络故障(状态码 {create_res.status_code}), 您可以稍后再试。"
                    }

            if order_count > 1:
                order_nums = ", ".join([item.get("order_no", "") for item in order_list])
                return {
                    "text": f"我查到您有多个订单都包含了「{goods_name}」这个商品哦(订单号分别是: {order_nums})。为了避免弄错, 方便告诉我您具体要退的是哪一个订单吗?",
                    "reply": f"我查到您有多个订单都包含了「{goods_name}」这个商品哦(订单号分别是: {order_nums})。为了避免弄错, 方便告诉我您具体要退的是哪一个订单吗?"
                }

        except Exception as e:
            logger.exception("按商品退货异常: %s", e)
            return {
                "text": "系统在处理请求时发生了异常, 请稍后重试。",
                "reply": "系统在处理请求时发生了异常, 请稍后重试。"
            }
