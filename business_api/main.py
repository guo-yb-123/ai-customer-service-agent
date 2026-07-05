import os
import logging
from typing import List, Dict

from fastapi.responses import JSONResponse
from fastapi import FastAPI
import uvicorn
import pymysql
import json
from pydantic import BaseModel

logger = logging.getLogger("business_api")
app = FastAPI(title="企业业务模拟微服务", description="订单、CRM、物流只读查询接口",default_response_class=JSONResponse)


@app.get("/health")
def health_check():
    """存活检查"""
    return JSONResponse({"status": "ok", "service": "business_api"})


@app.get("/ready")
def readiness_check():
    """就绪检查：MySQL 是否可连接"""
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        conn.ping()
        conn.close()
        return JSONResponse({"status": "ok", "checks": {"mysql": "ok"}})
    except Exception as e:
        return JSONResponse(
            {"status": "degraded", "checks": {"mysql": f"error: {e}"}},
            status_code=503,
        )

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "mysql"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "database": os.getenv("MYSQL_DATABASE", "business_db"),
    "charset": "utf8mb4"
}

#封装数据库查询工具
# 封装数据库查询工具
def mysql_query(sql: str, args: tuple = ()) -> List[Dict]:
    conn = None
    cursor = None
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute(sql, args)

        # 判断是否为查询语句（SELECT/SHOW/DESC）
        sql_upper = sql.strip().upper()
        if sql_upper.startswith(("SELECT", "SHOW", "DESC")):
            # 查询逻辑，转字典列表（完美规避 Docker 下 DictCursor 乱码 BUG）
            if cursor.description:
                col_names = [desc[0] for desc in cursor.description]
                res = [dict(zip(col_names, row)) for row in cursor.fetchall()]
            else:
                res = []
        else:
            # 写操作（INSERT/UPDATE/DELETE）：提交事务，返回空列表
            conn.commit()
            res = []

        return res

    except Exception as e:
        # 写操作异常回滚，避免脏数据
        if conn:
            conn.rollback()
        logger.error("数据库处理异常: %s, SQL: %s, args: %s", str(e), sql, args)
        return []

    finally:
        # 统一安全关闭
        if cursor:
            cursor.close()
        if conn:
            conn.close()
#订单查询接口
@app.get("/api/order/query")
def query_order(order_no: str, user_id: str):
    sql = "select * from t_order where order_no = %s and user_id = %s"
    data = mysql_query(sql, (order_no, user_id))
    if data:
        return data[0]
    return {"error": "订单不存在", "order_no": order_no, "user_id": user_id}
#客户信息查询接口
@app.get("/api/crm/customer")
def query_customer(user_id: str):
    sql = "select * from t_customer where user_id = %s"
    data = mysql_query(sql, (user_id,))
    if data :
        return data[0]
    return {
        "user_id": user_id,
        "member_level": "未注册",
        "total_order_count": 0,
        "has_unfinished_aftersale": False,
        "points": 0,
        "register_time": "暂无",
        "phone": "已隐藏"
    }
#物流轨迹查询接口
@app.get("/api/logistics/track")
def query_logistics(tracking_no: str):
    sql = "select * from t_logistics where tracking_no = %s"
    data = mysql_query(sql, (tracking_no,))
    if data:
        row = data[0]
        return {
            "tracking_no": row["tracking_no"],
            "track_list":json.loads(row["track_list"]),
        }
    return {
        "tracking_no": tracking_no,
        "track_list": ["暂无该物流单号轨迹信息"]}

@app.get("/api/order/get_tracking")
def get_tracking_by_order(order_no: str, user_id: str):
    sql = "select * from t_order where order_no = %s and user_id = %s"
    order_data = mysql_query(sql,args=(order_no, user_id))
    if not order_data:
        return{
            "success": False,
            "error_msg":"该订单不存在"
        }
    order = order_data[0]
    goods_name = order["goods_name"]
    order_status = order["order_status"]
    tracking_no = order.get("tracking_no", "")

    track_info = "暂无物流轨迹信息"
    if tracking_no:
        track_sql = "select * from t_logistics where tracking_no = %s"
        track_data = mysql_query(track_sql, args=(tracking_no,))
        if track_data:
            track_info = track_data[0]

    return {
        "success": True,
        "data": {
            "order_no": order_no,
            "goods_name": goods_name,
            "order_status": order_status,
            "tracking_no": tracking_no,
            "track_info": track_info
        }
    }


# 根据用户id查询全部订单+物流
@app.get("/api/order/list_by_user")
def list_order_by_user(user_id: str):
    sql = "select * from t_order where user_id = %s"
    order_list = mysql_query(sql, args=(user_id,))
    if not order_list:
        return {"success": False, "data": [], "msg": "未查询到该用户任何订单"}

    result = []
    for order in order_list:
        order_no = order["order_no"]
        goods_name = order["goods_name"]
        order_status = order["order_status"]
        tracking_no = order.get("tracking_no", "")

        track_info = "暂无物流轨迹信息"
        if tracking_no:
            track_sql = "select * from t_logistics where tracking_no = %s"
            track_data = mysql_query(track_sql, args=(tracking_no,))
            if track_data:
                track_info = track_data[0]

        item = {
            "order_no": order_no,
            "goods_name": goods_name,
            "order_status": order_status,
            "tracking_no": tracking_no,
            "track_info": track_info
        }
        result.append(item)
    return {"success": True, "data": result}


class TicketCreateReq(BaseModel):
    user_id: str
    session_id: str
    order_no: str
    problem_desc: str

@app.post("/api/ticket/create")
def create_ticket(req: TicketCreateReq):
    sql = """
    INSERT INTO t_aftersale_ticket(user_id,session_id,order_no,problem_desc,ticket_status,create_time,update_time)
    VALUES (%s,%s,%s,%s,'pending',NOW(),NOW())
    """
    conn = None
    cursor = None
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute(sql, (req.user_id, req.session_id, req.order_no, req.problem_desc))
        conn.commit()
        ticket_id = cursor.lastrowid
        return {
            "success": True,
            "data": {"ticket_id": ticket_id},
            "error_msg": ""
        }
    except Exception as e:
        return {
            "success": False,
            "data": {},
            "error_msg": str(e)
        }
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# 根据用户id查询全部售后工单
@app.get("/api/order/aftersale/list_by_user")
def list_aftersale_by_user(user_id: str):
    sql = """
    select 
        id as aftersale_no, 
        order_no, 
        problem_desc, 
        ticket_status as status, 
        create_time 
    from t_aftersale_ticket 
    where user_id = %s 
    order by create_time desc
    """
    aftersale_list = mysql_query(sql, args=(user_id,))

    if not aftersale_list:
        return {
            "success": True,
            "data": []
        }

    return {"success": True, "data": aftersale_list}


# ================= 关键修复：按商品名模糊查询订单接口 =================
# ================= 关键修复：按商品名模糊查询订单接口 =================
@app.get("/api/order/query_by_goods")
def query_order_by_goods(user_id: str, goods_name: str = None):
    # 【新增 1】打印原始参数，使用 repr() 暴露所有不可见字符（如空格、换行）
    logger.debug("入参: user_id=%s, goods_name=%s", repr(user_id), repr(goods_name))

    # 【新增 2】防御性编程：清理大模型可能传入的幽灵字符
    if goods_name:
        goods_name = goods_name.strip()  # 去除首尾空格和换行
        # 如果大模型传了类似 `智能电饭煲` (带markdown反引号)，这里可以进一步清理
        goods_name = goods_name.strip('`').strip('"').strip("'")

    data = []

    # 1. 传了商品名称 → 模糊匹配（%% 是 pymysql 的 % 转义）
    if goods_name:
        sql = """
            SELECT order_no, goods_name
            FROM t_order
            WHERE user_id = %s AND goods_name LIKE CONCAT('%%', %s, '%%')
        """
        data = mysql_query(sql, args=(user_id, goods_name))
        logger.debug("SQL查询结果: %s", data)

    # 2. 没查到 / 没传关键词 → 拉取该用户全部订单
    if not data:
        all_orders = mysql_query(
            "SELECT order_no, goods_name FROM t_order WHERE user_id = %s",
            (user_id,)
        )
        logger.debug("全量查询结果: %s", all_orders)

        # 3. 内存兜底过滤（解决 MySQL 字符集排序坑）
        if goods_name:
            # 【新增 3】详细打印内存比对过程，一眼看穿为什么过滤失败
            for item in all_orders:
                db_name = item["goods_name"]
                is_match = goods_name in db_name
                logger.debug("内存比对: 传入=%s, DB=%s, 匹配=%s", repr(goods_name), repr(db_name), is_match)

            data = [item for item in all_orders if goods_name in item["goods_name"]]
        else:
            data = all_orders

    logger.debug("最终返回 data: %s", data)
    return {"success": True, "data": data}


# 查询单条售后接口
@app.get("/api/order/aftersale/detail")
def detail_aftersale(user_id: str, aftersale_no: str):
    try:
        aftersale_id = int(aftersale_no)
    except ValueError:
        return {"success": False, "data": {}, "error_msg": "售后单号格式错误"}

    sql = """
    select 
        id as aftersale_no, 
        order_no, 
        problem_desc as `desc`, 
        ticket_status as status, 
        create_time 
    from t_aftersale_ticket 
    where id = %s and user_id = %s
    """
    data = mysql_query(sql, args=(aftersale_id, user_id))

    if not data:
        return {"success": False, "data": {}, "error_msg": "未查询到工单"}

    return {"success": True, "data": data[0]}


# 根据用户ID+快递单号，查询单条订单及物流详情
@app.get("/api/order/logistics/detail")
def detail_logistics_by_tracking(user_id: str, tracking_no: str):
    sql = """
    select 
        o.order_no, 
        o.goods_name, 
        o.tracking_no, 
        l.track_list as track_info,
        '运输中' as logistics_status 
    from t_order o
    left join t_logistics l on o.tracking_no = l.tracking_no
    where o.user_id = %s and o.tracking_no = %s
    """
    data = mysql_query(sql, args=(user_id, tracking_no))

    if not data:
        return {"success": False, "data": {}, "error_msg": "未查询到该快递单号关联的订单"}

    return {"success": True, "data": data[0]}


# 根据用户id查询该用户购买过的商品列表
@app.get("/api/order/goods/list_by_user")
def list_goods_by_user(user_id: str):
    sql = """
    select
        g.goods_id,
        g.goods_name,
        g.price,
        g.origin_price,
        g.spec,
        g.stock,
        g.`desc`
    from t_order o
    inner join t_goods g on o.goods_name = g.goods_name
    where o.user_id = %s
    """
    goods_list = mysql_query(sql, args=(user_id,))

    if not goods_list:
        return {"success": True, "data": []}

    return {"success": True, "data": goods_list}


# 根据商品ID查询商品详情
@app.get("/api/order/goods/detail")
def detail_goods(goods_id: str):
    sql = """
    select 
        goods_id, 
        goods_name, 
        price, 
        origin_price, 
        spec, 
        stock, 
        `desc` 
    from t_goods 
    where goods_id = %s
    """
    data = mysql_query(sql, args=(goods_id,))
    if not data:
        return {"success": False, "data": {}, "error_msg": "未查询到该商品信息"}
    return {"success": True, "data": data[0]}


if __name__ == "__main__":
    # 【修复】Docker 容器内必须使用 0.0.0.0 监听所有网卡，否则其他容器无法访问
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
