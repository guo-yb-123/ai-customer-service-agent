"""
人工客服工作台 API
功能：工单列表 / 认领 / 回复 / 关闭 / 查看对话历史 / 审批管理
"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional
from langgraph.types import Command

from app.db.database import get_db
from app.db.models import ServiceTicket, SessionArchive
from app.services.graph.tools.agent_memory import AgentExternalMemory
from app.services.graph import get_compiled_graph
from app.utils.redis_client import redis_client
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["客服工作台"])


# ===== Pydantic Models =====

class TicketResponse(BaseModel):
    ticket_id: int
    user_id: str
    session_id: str
    content: str
    status: str
    create_time: str
    agent_reply: Optional[str] = None

    class Config:
        from_attributes = True


class AgentReplyRequest(BaseModel):
    agent_name: str
    reply: str


class ClaimRequest(BaseModel):
    agent_name: str


# ===== 工单管理 =====

@router.get("/tickets", response_model=list[TicketResponse])
def list_tickets(
    status_filter: str = "all",
    db: Session = Depends(get_db),
):
    """获取工单列表"""
    query = db.query(ServiceTicket)
    if status_filter == "pending":
        query = query.filter(ServiceTicket.status == "待处理")
    elif status_filter == "active":
        query = query.filter(ServiceTicket.status.in_(["待处理", "处理中"]))
    elif status_filter == "closed":
        query = query.filter(ServiceTicket.status == "已完成")

    tickets = query.order_by(desc(ServiceTicket.create_time)).limit(100).all()
    return [
        {
            "ticket_id": t.ticket_id,
            "user_id": t.user_id,
            "session_id": t.session_id,
            "content": t.content,
            "status": t.status,
            "create_time": t.create_time.strftime("%Y-%m-%d %H:%M:%S") if t.create_time else "",
            "agent_reply": getattr(t, "agent_reply", None),
        }
        for t in tickets
    ]


@router.get("/tickets/{ticket_id}")
def get_ticket_detail(ticket_id: int, db: Session = Depends(get_db)):
    """获取单个工单详情 + 对话历史"""
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 获取对话历史
    chat_history = []
    archive = db.query(SessionArchive).filter(
        SessionArchive.session_id == ticket.session_id
    ).first()
    if archive and archive.chat_full_json:
        import json
        try:
            chat_history = json.loads(archive.chat_full_json)
        except json.JSONDecodeError:
            pass

    # 也尝试从 Redis 读取
    redis_history = AgentExternalMemory.get_chat_history(ticket.session_id)
    if redis_history:
        chat_history = redis_history

    return {
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "user_id": ticket.user_id,
            "session_id": ticket.session_id,
            "content": ticket.content,
            "status": ticket.status,
            "create_time": ticket.create_time.strftime("%Y-%m-%d %H:%M:%S") if ticket.create_time else "",
        },
        "chat_history": chat_history,
    }


@router.post("/tickets/{ticket_id}/claim")
def claim_ticket(ticket_id: int, req: ClaimRequest, db: Session = Depends(get_db)):
    """认领工单，开始处理"""
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    if ticket.status == "处理中":
        raise HTTPException(status_code=400, detail="工单已被认领")

    ticket.status = "处理中"
    db.commit()

    logger.info("工单 %s 被 %s 认领", ticket_id, req.agent_name)
    return {"success": True, "message": f"工单 {ticket_id} 已认领"}


@router.post("/tickets/{ticket_id}/reply")
def agent_reply(ticket_id: int, req: AgentReplyRequest, db: Session = Depends(get_db)):
    """客服回复并写入会话记忆"""
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 格式化回复
    reply_content = f"【人工客服-{req.agent_name}】{req.reply}"

    # 写入会话记忆（Redis）
    AgentExternalMemory.append_chat(
        session_id=ticket.session_id,
        role="assistant",
        content=reply_content,
    )

    logger.info("客服 %s 回复工单 %s: %s", req.agent_name, ticket_id, req.reply[:50])
    return {"success": True, "message": "回复已发送", "reply": reply_content}


@router.post("/tickets/{ticket_id}/close")
def close_ticket(ticket_id: int, db: Session = Depends(get_db)):
    """关闭工单"""
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    ticket.status = "已完成"
    db.commit()

    logger.info("工单 %s 已关闭", ticket_id)
    return {"success": True, "message": "工单已关闭"}


@router.get("/stats")
def ticket_stats(db: Session = Depends(get_db)):
    """工单统计概览"""
    total = db.query(ServiceTicket).count()
    pending = db.query(ServiceTicket).filter(ServiceTicket.status == "待处理").count()
    active = db.query(ServiceTicket).filter(ServiceTicket.status == "处理中").count()
    closed = db.query(ServiceTicket).filter(ServiceTicket.status == "已完成").count()

    return {
        "total": total,
        "pending": pending,
        "active": active,
        "closed": closed,
    }


# ===== 审批管理（LangGraph Human-in-the-Loop）=====

class ApprovalResponse(BaseModel):
    reason: str = ""


@router.get("/approvals")
def list_pending_approvals():
    """
    列出所有待审批的操作。

    从 Redis 扫描 approval:* 键，返回状态为 pending 的记录。
    """
    approvals = []
    try:
        for key in redis_client.scan_iter("approval:*"):
            data = redis_client.get(key)
            if data:
                try:
                    record = json.loads(data)
                    if record.get("status") == "pending":
                        approvals.append(record)
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning("扫描审批记录失败: %s", e)

    # 按创建时间倒序排列
    approvals.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"approvals": approvals, "total": len(approvals)}


@router.post("/approvals/{approval_id}/approve")
def approve_action(approval_id: str, body: ApprovalResponse = ApprovalResponse()):
    """
    批准指定的待审批操作。

    批准后，对应的 LangGraph graph 会从 interrupt 点恢复执行。
    """
    redis_key = f"approval:{approval_id}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(status_code=404, detail="审批记录不存在或已过期")

    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="审批记录格式错误")

    if record.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"审批记录状态为 {record.get('status')}，无法操作",
        )

    session_id = record.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="审批记录缺少 session_id")

    # 更新 Redis 记录
    from datetime import datetime
    record["status"] = "approved"
    record["approved_at"] = datetime.now().isoformat()
    redis_client.setex(redis_key, 3600, json.dumps(record, ensure_ascii=False))

    # 恢复 graph 执行
    try:
        graph = get_compiled_graph()
        graph_config = {"configurable": {"thread_id": session_id}}
        result = graph.invoke(Command(resume={"approved": True}), graph_config)

        logger.info(
            "审批通过: approval_id=%s, session=%s, final_stage=%s",
            approval_id, session_id, result.get("stage", "?"),
        )
    except Exception as e:
        logger.exception("恢复 graph 执行失败: %s", e)
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {str(e)}")

    return {"success": True, "message": "操作已批准，Agent 已继续执行"}


@router.post("/approvals/{approval_id}/reject")
def reject_action(approval_id: str, body: ApprovalResponse = ApprovalResponse()):
    """
    拒绝指定的待审批操作。

    拒绝后，graph 会恢复执行并生成拒绝回复。
    """
    redis_key = f"approval:{approval_id}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(status_code=404, detail="审批记录不存在或已过期")

    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="审批记录格式错误")

    if record.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"审批记录状态为 {record.get('status')}，无法操作",
        )

    session_id = record.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="审批记录缺少 session_id")

    # 更新 Redis 记录
    from datetime import datetime
    record["status"] = "rejected"
    record["approved_at"] = datetime.now().isoformat()
    record["reject_reason"] = body.reason
    redis_client.setex(redis_key, 3600, json.dumps(record, ensure_ascii=False))

    # 恢复 graph 执行（拒绝）
    try:
        graph = get_compiled_graph()
        graph_config = {"configurable": {"thread_id": session_id}}
        resume_value = {"approved": False, "reason": body.reason}
        result = graph.invoke(Command(resume=resume_value), graph_config)

        logger.info(
            "审批拒绝: approval_id=%s, session=%s, reason=%s",
            approval_id, session_id, body.reason,
        )
    except Exception as e:
        logger.exception("恢复 graph 执行失败: %s", e)
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {str(e)}")

    return {"success": True, "message": "操作已拒绝"}
