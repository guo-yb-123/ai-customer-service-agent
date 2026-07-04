from sqlalchemy import Column, Integer, String,DateTime,Text,Float,func,BigInteger
from sqlalchemy.dialects.postgresql import JSONB,ARRAY
from datetime import datetime
from app.db.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id = Column(Integer, primary_key=True, autoincrement=True,index=True)
    filename = Column(String(255),comment="上传文档名称")
    chunk_text = Column(Text,comment="文本片段")
    embedding = Column(ARRAY(Float), comment="1536维嵌入向量")
    create_time = Column(DateTime,default=datetime.now)


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True,index=True)
    session_id = Column(String(100),index=True,comment="会话唯一ID")
    chat_messages = Column(JSONB,comment = "多轮对话数组")
    create_time = Column(DateTime,default=datetime.now)
    update_time = Column(DateTime,default=datetime.now,onupdate=datetime.now)

class ServiceTicket(Base):
    __tablename__ = "service_ticket"
    ticket_id = Column(Integer, primary_key=True, autoincrement=True,index=True,comment="工单唯一id")
    user_id = Column(String(255),nullable=False,comment="客户用户id")
    session_id = Column(String(255),nullable=False,comment="对话会话id")
    content = Column(Text,nullable=False,comment="用户诉求内容")
    create_time = Column(DateTime,default=datetime.now,comment = "工单创建时间")
    status = Column(String(32),default="待处理",comment="工单处理状态")

class SessionArchive(Base):
    __tablename__ = "t_session_archive"
    id = Column(BigInteger,primary_key=True,autoincrement=True,comment="归档主键")
    session_id = Column(String(64),nullable=False,index=True,comment="会话唯一标识")
    user_id = Column(Text,nullable=False,index=True,comment="操作用户ID")
    chat_full_json = Column(Text,nullable=False,comment="完整对话历史json数组")
    last_graph_state = Column(Text,comment="会话创建时间")
    create_time = Column(DateTime,default=datetime.now,comment="会话创建时间")
    finish_time = Column(DateTime,nullable=True,comment="会话时间结束")





















