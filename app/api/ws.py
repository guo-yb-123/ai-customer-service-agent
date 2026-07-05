"""
WebSocket 实时推送 — 替代轮询 task_status
客户端连接后，异步任务完成时实时接收结果
"""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.utils.redis_client import redis_client
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["WebSocket"])

# 活跃连接池：{task_id: [ws1, ws2, ...]}
_active_connections: dict[str, list[WebSocket]] = {}


async def notify_task_complete(task_id: str, result: dict):
    """任务完成时向所有等待的 WebSocket 推送结果"""
    if task_id in _active_connections:
        disconnected = []
        for ws in _active_connections[task_id]:
            try:
                await ws.send_json({"type": "task_complete", "task_id": task_id, "data": result})
            except Exception:
                disconnected.append(ws)
        # 清理断开的连接
        for ws in disconnected:
            if ws in _active_connections.get(task_id, []):
                _active_connections[task_id].remove(ws)
        if not _active_connections.get(task_id):
            del _active_connections[task_id]


@router.websocket("/ws/task/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点：等待异步任务结果

    使用方式（前端）:
        const ws = new WebSocket('ws://localhost:8000/api/v1/ws/task/abc123');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'task_complete') {
                console.log('任务完成:', data.data);
            }
        };
    """
    await websocket.accept()
    logger.info("WebSocket connected: task_id=%s", task_id)

    # 注册连接
    if task_id not in _active_connections:
        _active_connections[task_id] = []
    _active_connections[task_id].append(websocket)

    # 先检查 Redis 是否已有结果
    cached = redis_client.get(f"task_status:{task_id}")
    if cached:
        try:
            data = json.loads(cached)
            await websocket.send_json({"type": "task_complete", "task_id": task_id, "data": data})
        except Exception:
            pass

    try:
        # 保持连接，定期检查 Redis（兜底轮询）
        last_check = 0
        while True:
            await asyncio.sleep(1)
            last_check += 1
            if last_check >= 3:  # 每 3 秒检查一次 Redis
                last_check = 0
                cached = redis_client.get(f"task_status:{task_id}")
                if cached:
                    try:
                        data = json.loads(cached)
                        await websocket.send_json({"type": "task_complete", "task_id": task_id, "data": data})
                        break
                    except Exception:
                        pass
            # 心跳
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: task_id=%s", task_id)
    finally:
        if task_id in _active_connections:
            if websocket in _active_connections[task_id]:
                _active_connections[task_id].remove(websocket)
            if not _active_connections[task_id]:
                del _active_connections[task_id]
