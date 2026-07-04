"""
基于 Redis 的滑动窗口限流中间件
"""
import time
import os
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.utils.redis_client import redis_client
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# 默认限流配置：每窗口最大请求数
DEFAULT_LIMITS = {
    "chat": int(os.getenv("RATELIMIT_CHAT", "30")),
    "stream": int(os.getenv("RATELIMIT_STREAM", "10")),
    "general": int(os.getenv("RATELIMIT_GENERAL", "60")),
}

WINDOW_SECONDS = int(os.getenv("RATELIMIT_WINDOW", "60"))

# 不限流的路径
PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_limit_for_path(path: str) -> int:
    if "/chat/stream" in path:
        return DEFAULT_LIMITS["stream"]
    elif "/chat" in path:
        return DEFAULT_LIMITS["chat"]
    return DEFAULT_LIMITS["general"]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis 滑动窗口限流中间件"""

    async def dispatch(self, request: Request, call_next):
        # 公开端点不限流
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        try:
            ip = _get_client_ip(request)
            max_requests = _get_limit_for_path(request.url.path)
            now = time.time()
            window_start = now - WINDOW_SECONDS

            key = f"ratelimit:{ip}:{request.url.path}"

            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, WINDOW_SECONDS + 10)
            _, current_count, _, _ = pipe.execute()

            if current_count and int(current_count) >= max_requests:
                logger.warning("rate limit exceeded: ip=%s count=%s limit=%s", ip, current_count, max_requests)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": True,
                        "error_msg": "请求过于频繁，请稍后再试",
                        "retry_after_seconds": WINDOW_SECONDS,
                    },
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )
        except Exception as e:
            logger.error("rate limiter check failed: %s", e)

        return await call_next(request)
