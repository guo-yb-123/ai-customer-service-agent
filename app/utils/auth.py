"""
API Token 鉴权中间件
"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import config
import secrets


# 不需要鉴权的公开端点
PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """
    Bearer Token 鉴权中间件。

    使用方式：
      设置环境变量 API_TOKEN=your-secret-token
      客户端请求时带 Header: Authorization: Bearer your-secret-token

    如果未设置 API_TOKEN（开发环境），则跳过鉴权。
    """

    async def dispatch(self, request: Request, call_next):
        # 公开端点跳过鉴权
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        # 未配置 Token 则跳过（开发模式）
        if not config.API_TOKEN:
            return await call_next(request)

        # 鉴权
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header. Use: Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]  # "Bearer " 之后的部分
        if not secrets.compare_digest(token, config.API_TOKEN):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
            )

        return await call_next(request)
