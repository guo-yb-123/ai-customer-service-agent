"""
输入验证和清洗工具
"""
import re
from fastapi import HTTPException, status


# 最大输入长度
MAX_QUESTION_LENGTH = 2000
MAX_SESSION_ID_LENGTH = 100
MAX_USER_ID_LENGTH = 50


def sanitize_text(text: str, max_length: int = MAX_QUESTION_LENGTH) -> str:
    """
    清洗用户输入文本：
    - 截断超长文本
    - 去除控制字符
    - 统一空白符
    """
    if not text:
        return ""

    # 截断
    if len(text) > max_length:
        text = text[:max_length]

    # 去除控制字符（保留换行和制表符）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 统一空白符
    text = re.sub(r"\s+", " ", text).strip()

    return text


def validate_session_id(session_id: str) -> str:
    """校验 session_id 格式"""
    if not session_id or not session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "session_id 不能为空"},
        )
    sid = session_id.strip()
    if len(sid) > MAX_SESSION_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": f"session_id 长度不能超过 {MAX_SESSION_ID_LENGTH}"},
        )
    # 只允许字母、数字、下划线、连字符
    if not re.match(r"^[a-zA-Z0-9_-]+$", sid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "session_id 包含非法字符"},
        )
    return sid


def validate_user_id(user_id: str) -> str:
    """校验 user_id 格式"""
    if not user_id or not user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "user_id 不能为空"},
        )
    uid = user_id.strip()
    if len(uid) > MAX_USER_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": f"user_id 长度不能超过 {MAX_USER_ID_LENGTH}"},
        )
    if not re.match(r"^[a-zA-Z0-9_-]+$", uid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "user_id 包含非法字符"},
        )
    return uid


def validate_question(question: str) -> str:
    """校验并清洗用户问题"""
    if not question or not question.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "question 不能为空"},
        )
    # 清洗
    cleaned = sanitize_text(question)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "question 清洗后为空"},
        )
    return cleaned
