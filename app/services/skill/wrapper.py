from .base import query_logistics,query_crm_data,query_order_info,query_all_order_info
from functools import wraps
def wrap_skill_call(func,**kwargs) ->dict:
    try:
        raw = func(**kwargs)
        if isinstance(raw,dict):
            return {"success":True,"error_msg":"","data":raw}
        elif isinstance(raw,str):
            return {"success":True,"error_msg":"","data":{"text":raw}}
        else:
            return {"success":False,"error_msg":f"不支持的数据类型:{type(raw)}","data":{}}
    except Exception as e:
        return {"success":False,"error_msg":f"技能调用异常:{type(e)}","data":{}}

#查询订单
def get_order(order_no:str,user_id:str):
    return wrap_skill_call(query_order_info,order_no=order_no,user_id=user_id)
#查询多个订单
def get_all_order_by_user(user_id:str):
    return wrap_skill_call(query_all_order_info, user_id=user_id)
#查询物流
def get_logistics(tracking_no:str):
    return wrap_skill_call(query_logistics,tracking_no=tracking_no)
#查询用户信息
def get_crm(user_id:str):
    return wrap_skill_call(query_crm_data,user_id=user_id)
