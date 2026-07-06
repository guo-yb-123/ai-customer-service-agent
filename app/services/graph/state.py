from pydantic import BaseModel,Field
from typing import Optional,Literal,List,Dict,Any
class GraphState(BaseModel):
    # ===== 原有字段（保持向后兼容）=====
    question: str = Field("", description="用户原始提问")
    session_id: str = Field("", description="会话唯一ID")

    user_id: Optional[str] = Field(None, description="会员用户ID")
    tracking_no: Optional[str] = Field(None, description="物流单号")
    order_no: Optional[str] = Field(None, description="订单编号")
    problem_desc: Optional[str] = Field(None, description="售后问题描述")
    intent: Optional[str] = Field(None, description="大模型识别意图")

    pending_slot: Optional[str] = Field(None, description="待补充的参数key,无缺失为None")
    stage: str = Field("EXTRACT", description="当前流转阶段：EXTRACT/ROUTE/QUERY/FILL_SLOT/FINISH/APPROVAL")

    reply_text: str = Field("", description="最终返回给用户的完整回答")
    error_msg: str = Field("", description="业务/接口异常提示")

    next_node: Optional[Literal[
        "fill_slot",
        "logistics",
        "crm",
        "order",
        "ticket",
        "kb_chat",
        "__end__"
    ]] = Field(None, description="LangGraph路由标记")
    member_level: Optional[str] = Field(None, description="用户会员等级")
    order_list: Optional[List[Dict[str, Any]]] = Field(None, description="用户全部订单+物流数组")
    chat_history: Optional[List[Dict[str, str]]] = Field(None, description="本次会话历史问答列表")

    # ===== 新增字段：槽位填充 =====
    collected_slots: Dict[str, Any] = Field(default_factory=dict, description="用户已提供的槽位值")
    missing_slots: List[str] = Field(default_factory=list, description="当前仍缺失的必填槽位")
    user_input: str = Field("", description="当前轮次用户输入")

    # ===== 新增字段：工具执行追踪 =====
    tool_name: Optional[str] = Field(None, description="当前要执行的工具名称")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="当前工具调用参数")
    tool_results: List[Dict[str, Any]] = Field(default_factory=list, description="工具调用结果累积")

    # ===== 新增字段：人工审批 =====
    approval_required: bool = Field(False, description="是否需要人工审批")
    approval_id: Optional[str] = Field(None, description="审批记录唯一ID")
    approval_status: Optional[str] = Field(None, description="审批状态：pending/approved/rejected")

    # ===== 新增字段：反思重试 =====
    reflection_count: int = Field(0, description="当前反思重试次数")
    max_reflection_retries: int = Field(2, description="最多反思重试次数")
    reflection_passed: bool = Field(False, description="最近一次反思是否通过")
    reflection_feedback: Optional[str] = Field(None, description="反思反馈/修改建议")

    # ===== 新增字段：操作标记 =====
    action: Optional[str] = Field(None, description="特殊操作标记：async_task_pending/transfer_human/approval_required")
    task_id: Optional[str] = Field(None, description="异步任务ID")
    ticket_id: Optional[str] = Field(None, description="工单ID")

    class Config:
        arbitrary_types_allowed = True