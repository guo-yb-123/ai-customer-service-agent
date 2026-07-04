from sqlalchemy.orm import Session
from app.db.models import ServiceTicket


def create_service_ticket(
        db: Session,
        user_id: str,
        session_id: str,
        content: str = "",
        order_no: str = "",
        problem_desc: str = "",
) -> ServiceTicket:
    full_content = content or f"订单号：{order_no}，问题：{problem_desc}"
    new_ticket = ServiceTicket(
        user_id=user_id,
        session_id=session_id,
        content=full_content,
    )
    db.add(new_ticket)
    db.commit()
    db.refresh(new_ticket)
    return new_ticket
