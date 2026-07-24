from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Any
import config
import psycopg2
from app.utils.llm import call_qwen_once
import json
import redis
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
# 补上这个缺失的 Pydantic 模型定义
class RefineRequest(BaseModel):
    session_id: str
    user_id: str
    raw_data: List[Any]
router = APIRouter(tags=["任务管理"])


redis_client = redis.Redis(
    host=config.REDIS_CONFIG['host'],
    port=config.REDIS_CONFIG['port'],
    db=config.REDIS_CONFIG['db'],
    password=config.REDIS_CONFIG.get('password', '') or None,
    decode_responses=True,
)
@router.get("/task/status/{task_id}")
def get_task_status(task_id: str):
    # 直接从 Redis 读结果，没有任何 Celery 后端调用
    data = redis_client.get(f"task_status:{task_id}")
    if data is None:
        return {"status": "pending"}
    return json.loads(data)


@router.post("/chat/refine")
def refine_text(req: RefineRequest):
    try:
        # 1. 构造提示词让大模型润色
        prompt = f"""
        你是一个亲切的 AI 客服，请把以下的原始订单数据，总结成一段通顺、自然、有语气的话回复给用户。
        数据如下：{req.raw_data}
        要求：
        1. 严禁编造或修改原有订单信息。
        2. 只用自然语言描述，不要用 JSON 格式。
        3. 直接输出你的回复，不要啰嗦。
        """

        # 2. 直接调用大模型润色
        reply_text = call_qwen_once(prompt)

        # 3. 把大模型润色好的最终回复，落地到 5432 的外部记忆库
        conn = psycopg2.connect(**config.PG_CONFIG)
        cur = conn.cursor()

        # 【关键修复】：把 raw_data 转成 JSON 字符串，存入 chat_full_json 列！
        cur.execute("""
                   INSERT INTO t_session_archive (session_id, user_id, chat_full_json, last_graph_state, create_time)
                   VALUES (%s, %s, %s, %s, NOW())
               """, (req.session_id, req.user_id, json.dumps(req.raw_data, ensure_ascii=False), reply_text))
        conn.commit()
        cur.close()
        conn.close()

        return {"reply": reply_text}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"reply": f"润色失败，后端异常信息：{str(e)}"}