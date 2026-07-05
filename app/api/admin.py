"""
人工客服工作台 API
功能：工单列表 / 认领 / 回复 / 关闭 / 查看对话历史
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.db.models import ServiceTicket, SessionArchive
from app.services.graph.tools.agent_memory import AgentExternalMemory
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
