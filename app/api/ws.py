"""
WebSocket 实时推送 — 替代轮询 task_status
客户端连接后，异步任务完成时实时接收结果
管理员连接后可接收审批通知
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

# 管理员工作台连接池
_active_admin_connections: list[WebSocket] = []


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


# ===== 管理员工作台 WebSocket =====

async def notify_approval_required(approval_data: dict):
    """
    向所有连接的 admin 工作台推送待审批通知。

    在 LangGraph approval 节点触发 interrupt 时调用。
    """
    disconnected = []
    for ws in _active_admin_connections:
        try:
            await ws.send_json({
                "type": "approval_required",
                "data": approval_data,
            })
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        if ws in _active_admin_connections:
            _active_admin_connections.remove(ws)

    if disconnected:
        logger.info("清理了 %d 个断开的 admin 连接", len(disconnected))


@router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    """
    管理员工作台 WebSocket 端点。

    连接后实时接收：
    - approval_required: 新的待审批操作
    - heartbeat: 心跳检测

    使用方式（前端）:
        const ws = new WebSocket('ws://localhost:8000/api/v1/ws/admin');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'approval_required') {
                console.log('新审批:', data.data);
            }
        };
    """
    await websocket.accept()
    _active_admin_connections.append(websocket)
    logger.info("Admin WebSocket 已连接，当前在线: %d", len(_active_admin_connections))

    try:
        while True:
            await asyncio.sleep(30)  # 每 30 秒发送心跳
            try:
                await websocket.send_json({"type": "heartbeat"})
            except Exception:
                break
    except WebSocketDisconnect:
        logger.info("Admin WebSocket 已断开")
    finally:
        if websocket in _active_admin_connections:
            _active_admin_connections.remove(websocket)
        logger.info("Admin WebSocket 已清理，当前在线: %d", len(_active_admin_connections))
