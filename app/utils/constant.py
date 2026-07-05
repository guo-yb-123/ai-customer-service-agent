# Redis会话缓存配置
SESSION_EXPIRE_SEC: int = 12 * 3600
REDIS_KEY_SESSION_PREFIX: str = "agent:session:"
REDIS_KEY_TASK_STATE_PREFIX: str = "agent:task_state:"