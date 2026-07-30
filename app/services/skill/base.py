import requests
import config
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


# ========== 基础 Skill 类定义 ==========
class BaseSkill:
    name = ""
    desc = ""

    def run(self, **kwargs):
        raise NotImplementedError("子类必须实现run方法")

# ========== 1. 查询单笔订单 ==========
def query_order_info(order_no: str, user_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/query"  # 修正路径
        resp = requests.get(url, params={"order_no": order_no, "user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====微服务返回完整json=====")
            logger.info(res)
            logger.info("是否包含error键：", "error" in res)

            if "error" in res:
                err_msg = res.get("error_msg", "订单不存在")
                return {
                    "success": False,
                    "data": {},
                    "error_msg": err_msg,
                    "text": f"订单查询失败：{err_msg}",
                    "reply": f"订单查询失败：{err_msg}"
                }
            data = res
            text = (
                f"订单号：{data.get('order_no', '暂无')}\n"
                f"商品：{data.get('goods_name', '暂无')}\n"
                f"状态：{data.get('order_status', '暂无')}\n"
                f"物流单号：{data.get('tracking_no') if data.get('tracking_no') else '暂无'}\n"
                f"物流轨迹：{data.get('track_info') if data.get('track_info') else '暂无轨迹'}"
            )
            return {
                "success": True,
                "data": data,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"订单查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"订单服务连接异常：{err}"
        }

# ========== 2. 查询物流轨迹 ==========
def query_logistics(tracking_no: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/logistics/track"
        resp = requests.get(url, params={"tracking_no": tracking_no}, timeout=2)
        if resp.status_code == 200:
            res = resp.json()
            if not res.get("success"):
                err_msg = res.get("error_msg", "物流查询失败")
                return {
                    "success": False,
                    "data": {},
                    "error_msg": err_msg,
                    "text": f"物流查询失败：{err_msg}"
                }
            data = res.get("data", {})
            track_list = data.get("track_list", [])
            track_text = "\n".join(track_list)
            text = f"物流单号{tracking_no}\n{track_text}"
            return {
                "success": True,
                "data": data,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"物流查询异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": err_msg
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"物流服务连接异常：{err}"
        }

# ========== 3. 查询 CRM 客户数据 ==========
def query_crm_data(user_id: str) -> dict:
    try:
        url = f"{config.INNER_CRM_API}/customer"
        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            if not res.get("success"):
                err_msg = res.get("error_msg", "客户信息查询失败")
                return {
                    "success": False,
                    "data": {},
                    "error_msg": err_msg,
                    "text": f"客户信息查询失败：{err_msg}"
                }
            data = res.get("data", {})
            text = (
                f"【客户档案】\n"
                f"用户ID：{data.get('user_id', '暂无')}\n"
                f"会员等级：{data.get('member_level', '普通用户')}\n"
                f"历史订单总数：{data.get('total_order_count', 0)}\n"
                f"是否有未处理售后：{data.get('has_unfinished_aftersale', False)}"
            )
            return {
                "success": True,
                "data": data,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"客户信息查询异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": err_msg
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"CRM服务连接异常：{err}"
        }

# ========== 5. 批量查询全部订单 ==========
def query_all_order_info(user_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/list_by_user"
        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====批量订单微服务返回完整json=====")
            logger.info(res)

            if isinstance(res, dict):
                if res.get("success") and isinstance(res.get("data"), list):
                    order_list = res["data"]
                    if not order_list:
                        return {
                            "success": False,
                            "data": {},
                            "error_msg": "暂无任何订单",
                            "text": "您名下暂时没有任何订单包裹",
                            "reply": "您名下暂时没有任何订单包裹"
                        }
                    text_lines = ["您名下所有订单如下："]
                    for item in order_list:
                        line = (
                            f"订单号：{item.get('order_no', '暂无')} | "
                            f"商品：{item.get('goods_name', '暂无')} | "
                            f"金额：{item.get('price', 0)}元 | "
                            f"状态：{item.get('order_status', '暂无')}"
                        )
                        text_lines.append(line)
                    full_text = "\n".join(text_lines)

                    return {
                        "success": True,
                        "data": order_list,
                        "error_msg": "",
                        "text": full_text,
                        "reply": full_text
                    }
                else:
                    error_reason = res.get("msg", "未知错误")
                    return {
                        "success": False,
                        "data": {},
                        "error_msg": error_reason,
                        "text": f"订单服务查询异常：{error_reason}"
                    }
            else:
                return {
                    "success": False,
                    "data": {},
                    "error_msg": "返回数据格式错误",
                    "text": "订单服务返回数据格式异常，请联系管理员"
                }
        err_msg = f"批量订单接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"全部订单查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"订单服务连接异常：{err}"
        }

# ========== 6. 批量查询全部售后 ==========
def query_all_aftersale_info(user_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/aftersale/list_by_user"
        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====批量售后微服务返回完整json=====")
            logger.info(res)

            aftersale_list = []
            if isinstance(res, dict):
                if isinstance(res.get("data"), list):
                    aftersale_list = res["data"]
            elif isinstance(res, list):
                aftersale_list = res

            if not aftersale_list:
                return {
                    "success": True,
                    "data": [],
                    "error_msg": "暂无任何售后工单",
                    "text": "哎呀，系统暂时没查到您的售后信息呢~可能是网络有点小波动，我马上再帮您仔细查一遍，稍等哦！",
                    "reply": "哎呀，系统暂时没查到您的售后信息呢~可能是网络有点小波动，我马上再帮您仔细查一遍，稍等哦！"
                }

            text_lines = ["您名下所有售后工单如下："]
            for item in aftersale_list:
                if isinstance(item, dict):
                    line = (
                        f"售后单号：{item.get('aftersale_no', '暂无')} | "
                        f"对应商品：{item.get('goods_name', '暂无')} | "
                        f"售后类型：{item.get('type', '暂无')} | "
                        f"当前状态：{item.get('status', '暂无')}"
                    )
                    text_lines.append(line)

            full_text = "\n".join(text_lines)
            return {
                "success": True,
                "data": aftersale_list,
                "error_msg": "",
                "text": full_text,
                "reply": full_text
            }
        err_msg = f"售后接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": [],
            "error_msg": err_msg,
            "text": f"售后查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": [],
            "error_msg": err,
            "text": f"售后服务连接异常：{err}"
        }

# ========== 7. 单条查询售后 ==========
def query_single_aftersale_info(user_id: str, aftersale_no: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/aftersale/detail"
        logger.info(f"DEBUG: 查询单个售后请求地址 = {url}")

        resp = requests.get(url, params={"user_id": user_id, "aftersale_no": aftersale_no}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====单个售后微服务返回完整json=====")
            logger.info(res)

            item = None
            if isinstance(res, dict) and res.get("success"):
                data_val = res.get("data")
                if isinstance(data_val, dict):
                    item = data_val

            if not item:
                return {
                    "success": False,
                    "data": {},
                    "error_msg": "未查询到该售后工单",
                    "text": "没有找到对应售后单号的工单，请核对售后单号是否正确",
                    "reply": "没有找到对应售后单号的工单，请核对售后单号是否正确"
                }

            text = (
                f"售后单号：{item.get('aftersale_no', '暂无')}\n"
                f"对应商品：{item.get('goods_name', '暂无')}\n"
                f"售后类型：{item.get('type', '暂无')}\n"
                f"申请时间：{item.get('create_time', '暂无')}\n"
                f"当前状态：{item.get('status', '暂无')}\n"
                f"问题描述：{item.get('desc', '暂无')}"
            )
            return {
                "success": True,
                "data": item,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"单个售后接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"售后详情查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"售后服务连接异常：{err}"
        }

# ========== 8. 批量查询物流（底层复用订单接口） ==========
def query_all_logistics_info(user_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/list_by_user"
        logger.info(f"DEBUG: 批量物流请求地址 = {url}")

        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====批量订单/物流微服务返回完整json=====")
            logger.info(res)

            order_list = []
            if isinstance(res, dict) and res.get("success") and isinstance(res.get("data"), list):
                order_list = res["data"]

            if not order_list:
                return {
                    "success": True,
                    "data": [],
                    "error_msg": "",
                    "text": "您名下暂时没有物流包裹记录",
                    "reply": "您名下暂时没有物流包裹记录"
                }

            text_lines = ["您名下全部物流包裹信息："]
            for item in order_list:
                track_info = item.get('track_info', {})
                real_track_list = "暂无轨迹"
                if isinstance(track_info, dict):
                    track_list_raw = track_info.get('track_list', '')
                    if track_list_raw:
                        # track_list 可能是 JSON 字符串或已解析的 list
                        if isinstance(track_list_raw, str):
                            try:
                                parsed = __import__('json').loads(track_list_raw)
                                real_track_list = " → ".join(parsed) if isinstance(parsed, list) else track_list_raw
                            except (__import__('json').JSONDecodeError, TypeError):
                                real_track_list = track_list_raw
                        elif isinstance(track_list_raw, list):
                            real_track_list = " → ".join(track_list_raw)

                line = (
                    f"订单号：{item.get('order_no', '暂无')} | "
                    f"快递单号：{item.get('tracking_no', '暂无')} | "
                    f"商品：{item.get('goods_name', '暂无')} | "
                    f"物流轨迹：{real_track_list}"
                )
                text_lines.append(line)
            full_text = "\n".join(text_lines)

            return {
                "success": True,
                "data": order_list,
                "error_msg": "",
                "text": full_text,
                "reply": full_text
            }
        err_msg = f"批量订单接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"全部物流查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"物流服务连接异常：{err}"
        }

# ========== 9. 单条查询物流 ==========
def query_single_logistics_info(user_id: str, tracking_no: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/logistics/detail"
        logger.info(f"DEBUG: 单条物流请求地址 = {url}")

        resp = requests.get(url, params={"user_id": user_id, "tracking_no": tracking_no}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====单条物流微服务返回完整json=====")
            logger.info(res)

            item = None
            if isinstance(res, dict) and res.get("success") and isinstance(res.get("data"), dict):
                item = res["data"]

            if not item:
                return {
                    "success": True,
                    "data": {},
                    "error_msg": "",
                    "text": "未找到对应快递单号的物流轨迹，请核对单号",
                    "reply": "未找到对应快递单号的物流轨迹，请核对单号"
                }

            text = (
                f"快递单号：{item.get('tracking_no', '暂无')}\n"
                f"对应订单：{item.get('order_no', '暂无')}\n"
                f"商品名称：{item.get('goods_name', '暂无')}\n"
                f"当前物流状态：{item.get('logistics_status', '暂无')}\n"
                f"完整轨迹：{item.get('track_info', '暂无')}"
            )
            return {
                "success": True,
                "data": item,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"单物流接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"物流详情查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"物流服务连接异常：{err}"
        }

# ========== 10. 查询 CRM 用户信息（积分和手机） ==========
def query_crm_user_info(user_id: str) -> dict:
    try:
        url = f"{config.INNER_CRM_API}/customer"
        logger.info(f"DEBUG: CRM 查询请求地址 = {url}")

        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====CRM用户微服务返回完整json=====")
            logger.info(res)

            user_info = None
            if isinstance(res, dict):
                user_info = res

            if not user_info:
                return {
                    "success": True,
                    "data": {},
                    "error_msg": "",
                    "text": "暂时无法获取您的会员信息，请稍后重试"
                }

            text = (
                f"您的会员信息如下：\n"
                f"用户ID：{user_info.get('user_id', '暂无')}\n"
                f"会员等级：{user_info.get('member_level', '普通用户')}\n"
                f"历史订单数：{user_info.get('total_order_count', '0')}笔\n"
                f"会员积分：{user_info.get('points', '0')}分\n"
                f"注册时间：{user_info.get('register_time', '暂无')}\n"
                f"绑定手机号：{user_info.get('phone', '已隐藏')}"
            )
            return {
                "success": True,
                "data": user_info,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"CRM用户接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"会员信息查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"会员服务连接异常：{err}"
        }

# ========== 11. 批量查询购买过的商品 ==========
def query_all_goods_info(user_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/goods/list_by_user"
        logger.info(f"DEBUG: 批量商品请求地址 = {url}")

        resp = requests.get(url, params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====批量商品微服务返回完整json=====")
            logger.info(res)

            goods_list = []
            if isinstance(res, dict):
                if res.get("success") and "data" in res and isinstance(res["data"], list):
                    goods_list = res["data"]
            elif isinstance(res, list):
                goods_list = res

            if not goods_list:
                return {
                    "success": True,
                    "data": [],
                    "error_msg": "",
                    "text": "您还没有购买过任何商品，暂无商品信息",
                    "reply": "您还没有购买过任何商品，暂无商品信息"
                }

            text_lines = ["您购买过的全部商品："]
            for item in goods_list:
                line = (
                    f"商品ID：{item.get('goods_id', '暂无')} | "
                    f"商品名称：{item.get('goods_name', '暂无')} | "
                    f"售价：{item.get('price', '暂无')}元 | "
                    f"原价：{item.get('origin_price', '暂无')}元 | "
                    f"规格：{item.get('spec', '暂无')} | "
                    f"库存：{item.get('stock', '暂无')} | "
                    f"描述：{item.get('desc', '暂无')}"
                )
                text_lines.append(line)
            full_text = "\n".join(text_lines)

            return {
                "success": True,
                "data": goods_list,
                "error_msg": "",
                "text": full_text,
                "reply": full_text
            }
        err_msg = f"批量商品接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"商品列表查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"商品服务连接异常：{err}"
        }

# ========== 12. 单条查询商品详情 ==========
def query_single_goods_info(goods_id: str) -> dict:
    try:
        url = f"{config.INNER_ORDER_API}/api/order/goods/detail"
        logger.info(f"DEBUG: 单品详情请求地址 = {url}")

        resp = requests.get(url, params={"goods_id": goods_id}, timeout=5)
        if resp.status_code == 200:
            res = resp.json()
            logger.info("=====单品微服务返回完整json=====")
            logger.info(res)

            goods_detail = None
            if isinstance(res, dict) and res.get("success") and isinstance(res.get("data"), dict):
                goods_detail = res["data"]

            if not goods_detail:
                return {
                    "success": True,
                    "data": {},
                    "error_msg": "",
                    "text": f"系统里没有找到商品编号为 {goods_id} 的信息，请核对商品ID",
                    "reply": f"系统里没有找到商品编号为 {goods_id} 的信息，请核对商品ID"
                }

            text = (
                f"您查询的商品详情如下：\n"
                f"商品ID：{goods_detail.get('goods_id', '暂无')}\n"
                f"商品名称：{goods_detail.get('goods_name', '暂无')}\n"
                f"售价：{goods_detail.get('price', '暂无')}元\n"
                f"原价：{goods_detail.get('origin_price', '暂无')}元\n"
                f"规格：{goods_detail.get('spec', '暂无')}\n"
                f"库存：{goods_detail.get('stock', '暂无')}\n"
                f"商品介绍：{goods_detail.get('desc', '暂无')}"
            )

            return {
                "success": True,
                "data": goods_detail,
                "error_msg": "",
                "text": text,
                "reply": text
            }
        err_msg = f"单品接口异常，状态码{resp.status_code}"
        return {
            "success": False,
            "data": {},
            "error_msg": err_msg,
            "text": f"商品详情查询失败：{err_msg}"
        }
    except Exception as e:
        err = str(e)
        return {
            "success": False,
            "data": {},
            "error_msg": err,
            "text": f"商品服务连接异常：{err}"
        }