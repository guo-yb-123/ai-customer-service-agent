from pydantic import BaseModel,Field
from typing import Optional,Literal,List,Dict,Any
class GraphState(BaseModel):
    question:str = Field("",description="用户原始提问")
    session_id:str =  Field("",description="会话唯一ID")

    user_id:Optional[str] = Field(None,description="会员用户ID")
    tracking_no:Optional[str] = Field(None,description="物流单号")
    order_no:Optional[str] = Field(None,description="订单编号")
    problem_desc:Optional[str] = Field(None,description="售后问题描述")
    intent: Optional[str] = Field(None, description="大模型识别意图：query_logistics/query_order/other")

    pending_slot:Optional[str] = Field(None,description="待补充的参数key,无缺失为None")
    stage:str = Field("EXTRACT",description="当前流转阶段：EXTRACT/ROUTE/QUERY/FILL_SLOT/FINISH")

    reply_text:str = Field("",description="最终返回给用户的完整回答")
    error_msg:str = Field("",description="业务/接口异常提示")

    next_node: Optional[Literal[
        "fill_slot",
        "logistics",
        "crm",
        "order",
        "ticket",
        "kb_chat",
        "__end__"
    ]] = Field(None, description="LangGraph路由标记，控制下一个执行的节点")
    member_level: Optional[str] = Field(None, description="用户会员等级：金牌/银牌/钻石/普通用户")
    order_list: Optional[List[Dict[str, Any]]] = Field(None, description="用户全部订单+物流数组，来自业务微服务")
    chat_history: Optional[List[Dict[str, str]]] = Field(None, description="本次会话历史问答列表，[{role,content}]")



    class Config:
        arbitrary_types_allowed = True