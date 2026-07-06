from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api.chat import router as chat_router
from app.api.task import router as task_router
from app.api.ws import router as ws_router
from app.api.admin import router as admin_router
from app.api.graph import router as graph_router
from prometheus_fastapi_instrumentator import Instrumentator
from app.utils.logging_config import setup_logging, set_trace_id, get_logger, get_trace_id
import redis
import config
import uuid
import time
import os

# 初始化日志
setup_logging(level="DEBUG" if config.DOCKER_ENV else "INFO", json_output=config.DOCKER_ENV)
logger = get_logger(__name__)

app = FastAPI(title="企业售后客服LangGraph服务")

# ===== CORS 跨域配置 =====
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS.split(",") if CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 限流中间件（每 IP 每端点独立限流，公开端点自动跳过）
from app.utils.rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Token 鉴权（未设 API_TOKEN 时自动跳过）
from app.utils.auth import TokenAuthMiddleware
app.add_middleware(TokenAuthMiddleware)


@app.middleware("http")
async def trace_request(request: Request, call_next):
    """为每个 HTTP 请求注入 trace_id 并记录耗时"""
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:12])
    set_trace_id(trace_id)
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    logger.info(
        "%s %s → %s (%.3fs)",
        request.method, request.url.path, response.status_code, elapsed,
    )
    response.headers["X-Trace-ID"] = trace_id
    return response
# API 版本化：所有业务路由统一加 /api/v1 前缀
app.include_router(chat_router, prefix="/api/v1")
app.include_router(task_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(graph_router, prefix="/api/v1")

# 静态文件（客服工作台）
_static_dir = Path(__file__).parent / "app" / "static"
if _static_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(_static_dir), html=True), name="static")
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


# ===== 统一异常处理 =====
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "error_msg": exc.detail,
            "status_code": exc.status_code,
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "error_msg": "请求参数校验失败",
            "detail": exc.errors(),
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "error_msg": "服务器内部错误",
            "trace_id": get_trace_id(),
        },
    )


@app.get("/health")
def health_check():
    """存活检查：进程是否活着"""
    return JSONResponse({"status": "ok", "service": "agent_api"})


@app.get("/ready")
def readiness_check():
    """就绪检查：依赖服务是否可用"""
    checks = {}
    # 检查 Redis
    try:
        r = redis.Redis(
            host=config.REDIS_CONFIG["host"],
            port=config.REDIS_CONFIG["port"],
            db=config.REDIS_CONFIG["db"],
            password=config.REDIS_CONFIG.get("password", "") or None,
            socket_connect_timeout=2,
        )
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=status_code,
    )


# ===== 优雅关闭 =====
import signal
import sys

def _graceful_shutdown(signum, frame):
    """处理 SIGTERM / SIGINT，drain 连接后退出"""
    logger.warning("收到信号 %s，开始优雅关闭...", signum)
    # Celery worker 会自行处理自己的关闭
    # 这里确保 uvicorn 收到的连接处理完再退出
    sys.exit(0)

signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        timeout_graceful_shutdown=30,
    )