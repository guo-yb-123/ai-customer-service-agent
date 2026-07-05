import requests
import config

from app.services.skill.base import BaseSkill, query_single_logistics_info, query_all_logistics_info
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class AllLogisticsSkill(BaseSkill):
    name = "query_all_logistics"
    desc = """
    [强制触发工具] 用户询问: 全部快递、所有物流、我的包裹、全部物流轨迹、查我所有快递、查我所有包裹, 必须调用本工具。
    功能: 根据user_id一次性查询该用户名下全部物流包裹(含订单号、快递单号、商品名、物流轨迹), 无需快递单号。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入, 无需用户提供。
    约束: 拿到全部物流数据后直接汇总回答, 禁止再调用其他物流/订单工具。
    """

    def run(self, user_id: str, **kwargs):
        logger.info("批量查询全部物流")
        result = query_all_logistics_info(user_id=user_id)
        return result


class SingleLogisticsSkill(BaseSkill):
    name = "query_single_logistics"
    desc = """
    [强制触发工具] 用户提供快递单号、查询某条快递轨迹、查单号xxx物流, 调用本工具。
    功能: 根据user_id + 快递单号查询单条物流详细轨迹。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入;
        tracking_no: 用户提供的快递单号, 必须提取传入。
    约束: 缺少快递单号不调用该工具, 引导用户提供快递单号。
    """

    def run(self, user_id: str, tracking_no: str, **kwargs):
        logger.info("查询单条物流: tracking_no=%s", tracking_no)
        res_json = query_single_logistics_info(user_id=user_id, tracking_no=tracking_no)
        logger.info("单物流接口返回: success=%s", res_json.get("success"))
        return {
            "text": res_json.get("text", "查询失败, 无返回信息"),
            "logistics_detail": res_json.get("data", {})
        }


class LogisticsByGoodsSkill(BaseSkill):
    name = "query_logistics_by_goods"
    desc = """
    [绝对强制命令] 只要用户明确说出"查一下某商品的物流"、"某商品到哪了"、"某商品发货没", 并且没有提供任何订单号或快递单号, 必须调用本工具!
    严禁将此问题交由知识库或兜底工具处理!
    功能: 根据 user_id + 商品名称, 自动从数据库查找该商品对应的订单, 并返回真实物流状态。
    """
    def run(self, user_id: str, goods_name: str, **kwargs):
        logger.info("按商品查物流: goods_name=%s", goods_name)
        url = f"{config.INNER_ORDER_API}/api/order/query_by_goods"
        resp = requests.get(url, params={"user_id": user_id, "goods_name": goods_name}, timeout=5)

        if resp.status_code != 200:
            msg = "查询商品对应订单时网络异常, 您可以尝试直接给我快递单号。"
            return {"text": msg, "reply": msg}

        res_json = resp.json()
        order_list = res_json.get("data", [])
        count = len(order_list)

        if count == 0:
            msg = f"我这里没查到您买过「{goods_name}」的订单哦。可能是商品名有微小差异, 或者您还没有购买过这件商品。您可以尝试直接提供具体的订单号, 我来帮您精准查物流。"
            return {"text": msg, "reply": msg}

        if count == 1:
            item = order_list[0]
            order_no = item.get("order_no")
            detail_url = f"{config.INNER_ORDER_API}/api/order/get_tracking"
            detail_resp = requests.get(detail_url, params={"user_id": user_id, "order_no": order_no}, timeout=5)

            status_text = "目前暂无更新的物流信息, 可能是刚刚发货, 系统还在同步中。"
            if detail_resp.status_code == 200:
                detail_data = detail_resp.json()
                if detail_data.get("success"):
                    order_status = detail_data["data"].get("order_status", "未知")
                    track_info = detail_data["data"].get("track_info", "暂无物流轨迹信息")
                    status_text = f"当前订单状态是「{order_status}」。"
                    if track_info and track_info != "暂无物流轨迹信息":
                        status_text += f" 最新物流轨迹为: {track_info}"

            msg = f"亲, 查到您买过「{goods_name}」, 对应的订单号是 {order_no}。{status_text}\n如果您想查看更详细的物流轨迹, 可以把这个单号发我, 我再帮您深挖一下。"
            return {"text": msg, "reply": msg}

        if count > 1:
            order_nums = ", ".join([item.get("order_no", "") for item in order_list])
            msg = f"我查到您有多个订单都包含「{goods_name}」哦(订单号分别是: {order_nums})。您可以告诉我具体是哪一个单号, 我帮您细查物流。"
            return {"text": msg, "reply": msg}
