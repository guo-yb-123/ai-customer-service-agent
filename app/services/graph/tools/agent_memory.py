import json
import os
from datetime import datetime
from typing import Dict
from sqlalchemy.orm import Session
from app.utils.redis_client import redis_client
from app.db.database import SessionLocal
from app.db.models import SessionArchive
from app.services.graph.state import GraphState
from app.utils.constant import SESSION_EXPIRE_SEC,REDIS_KEY_SESSION_PREFIX,REDIS_KEY_TASK_STATE_PREFIX

# 对话历史最大条数（超过则裁剪旧消息，防止 token 无限增长）
MAX_CHAT_HISTORY = int(os.getenv("MAX_CHAT_HISTORY", "20"))

class AgentExternalMemory:
    @staticmethod
    def _get_session_key(session_id: str) -> str:
        return f"{REDIS_KEY_SESSION_PREFIX}{session_id}"

    @staticmethod
    def _get_task_state_key(session_id: str) -> str:
        return f"{REDIS_KEY_TASK_STATE_PREFIX}{session_id}"

    @staticmethod
    def init_session(session_id: str,user_id:str):
        init_meta = {
            "chat_history": [],
            "last_intent":"",
            "extracted_slots":{"user_id":user_id},
        }
        redis_client.setex(
            name=AgentExternalMemory._get_session_key(session_id),
            time=SESSION_EXPIRE_SEC,
            value=json.dumps(init_meta,ensure_ascii=False),
        )
        empty_state = GraphState(
            question="",user_id=user_id,order_no=None,tracking_no = None,
            pending_slot = None,stage = "",reply_text = "",error_msg=""
        )
        AgentExternalMemory.save_task_state(session_id,empty_state)
        db:Session = SessionLocal()
        new_archive = SessionArchive(
            session_id=session_id,
            user_id=user_id,
            chat_full_json = json.dumps([],ensure_ascii=False),
            last_graph_state = json.dumps(empty_state.model_dump(),ensure_ascii=False),
        )
        db.add(new_archive)
        db.commit()
        db.close()

    @staticmethod
    def load_session_meta(session_id:str)->Dict:
        raw = redis_client.get(AgentExternalMemory._get_session_key(session_id))
        if not raw:
            return{"chat_history":[],"last_intent":"","extracted_slots":{}}
        return json.loads(raw)
    @staticmethod
    def append_chat(session_id:str,role:str,content:str):
       meta = AgentExternalMemory.load_session_meta(session_id)
       meta["chat_history"].append({
           "role":role,
           "content":content,
           "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
       })
       # 超出最大条数时，裁剪最早的对话（保留最近 N 条）
       if len(meta["chat_history"]) > MAX_CHAT_HISTORY:
           meta["chat_history"] = meta["chat_history"][-MAX_CHAT_HISTORY:]
       redis_client.setex(
            name=AgentExternalMemory._get_session_key(session_id),
            time=SESSION_EXPIRE_SEC,
            value=json.dumps(meta,ensure_ascii=False),
        )
       db:Session = SessionLocal()
       archive_row = db.query(SessionArchive).filter(SessionArchive.session_id == session_id).first()
       if archive_row:
           archive_row.chat_full_json = json.dumps(meta["chat_history"],ensure_ascii=False)
           db.commit()
       db.close()
    @staticmethod
    def save_task_state(session_id: str, state: GraphState | dict):
        # 新增兼容判断
        if isinstance(state, dict):
            data = state
        else:
            data = state.model_dump()
        state_json = json.dumps(data, ensure_ascii=False)

        redis_client.setex(
            name=AgentExternalMemory._get_task_state_key(session_id),
            time=SESSION_EXPIRE_SEC,
            value=state_json,
        )
        db: Session = SessionLocal()
        archive_row = db.query(SessionArchive).filter(SessionArchive.session_id == session_id).first()
        if archive_row:
            archive_row.last_graph_state = state_json
            db.commit()
        db.close()
    @staticmethod
    def get_chat_history(session_id: str) -> list:
        meta = AgentExternalMemory.load_session_meta(session_id)
        return meta.get("chat_history", [])

