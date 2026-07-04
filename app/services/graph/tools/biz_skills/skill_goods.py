from app.services.skill.base import BaseSkill, query_all_goods_info, query_single_goods_info
from app.utils.logging_config import get_logger

logger = get_logger(__name__)



class AllGoodsSkill(BaseSkill):
    name = "query_all_goods"
    desc = """
    [强制触发] 用户询问: 我买过什么、全部购买商品、历史货品、我的所有商品、买了哪些东西, 调用本工具。
    功能: 根据user_id查询当前用户所有下单购买过的商品列表(含商品名、价格、规格、描述), 无需商品ID。
    参数说明:
        user_id: 当前对话用户id, 系统自动注入。
    约束: 只展示本人购买商品, 不查全平台商品; 拿到数据后直接汇总回答。
    """
    def run(self, user_id: str, **kwargs):
        logger.info("=====进入批量查询购买商品 run(同步) =====")
        result = query_all_goods_info(user_id=user_id)
        return result


class SingleGoodsSkill(BaseSkill):
    name = "query_single_goods"
    desc = """
    [最高优先级] 只要用户提供以 G 字母开头的编号(如 G007、G001), 并要求查询商品详情/介绍/参数, 必须调用本工具!
    功能: 根据 goods_id 查询商品主表(价格、规格、库存、介绍)。
    参数说明:
        goods_id: 用户提供的商品编号(例如 G007), 必填。
    约束: 绝对禁止把 G 开头的编号当成订单号! 本工具只负责查商品信息!
    """
    def run(self, goods_id: str, **kwargs):
        logger.info(f"=====进入查询单品详情 run, 商品ID={goods_id} =====")
        res_json = query_single_goods_info(goods_id=goods_id)
        logger.info(f"=====单品接口返回状态: success={res_json.get('success')} =====")
        return {
            "text": res_json.get("text", "查询失败, 无返回信息"),
            "reply": res_json.get("text", "查询失败, 无返回信息"),
            "goods_detail": res_json.get("data", {})
        }
