"""
全局配置入口 — 根据 APP_ENV 加载对应环境的配置，支持环境变量覆盖
"""
import os
import importlib

# ===== 环境模式 =====
APP_ENV = os.getenv("APP_ENV", "dev")
DOCKER_ENV = os.getenv("DOCKER_ENV", "0") == "1"

# ===== 加载环境特定配置 =====
_env_defaults = {}
try:
    _env_module = importlib.import_module(f"config.{APP_ENV}")
    for _key in dir(_env_module):
        if not _key.startswith("_"):
            _env_defaults[_key] = getattr(_env_module, _key)
except ImportError:
    pass  # 环境配置模块不存在时使用下方硬编码默认值

# ===== 鉴权 =====
API_TOKEN = os.getenv("API_TOKEN", _env_defaults.get("API_TOKEN", ""))

# ===== 限流 =====
RATELIMIT_CHAT = int(os.getenv("RATELIMIT_CHAT", _env_defaults.get("RATELIMIT_CHAT", 100)))
RATELIMIT_STREAM = int(os.getenv("RATELIMIT_STREAM", _env_defaults.get("RATELIMIT_STREAM", 30)))
RATELIMIT_GENERAL = int(os.getenv("RATELIMIT_GENERAL", _env_defaults.get("RATELIMIT_GENERAL", 200)))

# ===== 数据库连接池 =====
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", _env_defaults.get("DB_POOL_SIZE", 5)))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", _env_defaults.get("DB_MAX_OVERFLOW", 10)))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", _env_defaults.get("DB_POOL_RECYCLE", 3600)))
# ===== LLM =====
LLM_MODEL = os.getenv("LLM_MODEL", _env_defaults.get("LLM_MODEL", "deepseek-v3"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", _env_defaults.get("LLM_TEMPERATURE", 0.0)))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", _env_defaults.get("LLM_MAX_TOKENS", 2048)))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
TOP_K = int(os.getenv("TOP_K", "3"))

# ===== Agent =====
MAX_CHAT_HISTORY = int(os.getenv("MAX_CHAT_HISTORY", _env_defaults.get("MAX_CHAT_HISTORY", 20)))

# ===== CORS =====
CORS_ORIGINS = os.getenv("CORS_ORIGINS", _env_defaults.get("CORS_ORIGINS", "*"))

# ===== PostgreSQL 会话库 =====
PG_CONFIG = {
    "host": os.getenv("PG_HOST", "postgres_session" if DOCKER_ENV else "localhost"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", "123456"),
    "dbname": os.getenv("PG_DBNAME", "ai_customer"),
}

# ===== PostgreSQL 向量库 =====
VECTOR_PG_CONFIG = {
    "host": os.getenv("VECTOR_PG_HOST", "postgres_vector" if DOCKER_ENV else "localhost"),
    "port": int(os.getenv("VECTOR_PG_PORT", "5432" if DOCKER_ENV else "5433")),
    "user": os.getenv("VECTOR_PG_USER", "postgres"),
    "password": os.getenv("VECTOR_PG_PASSWORD", "123456"),
    "dbname": os.getenv("VECTOR_PG_DBNAME", "ai_customer"),
}

# ===== 数据库连接 URL =====
DB_URL = (
    f"postgresql+psycopg2://{PG_CONFIG['user']}:{PG_CONFIG['password']}"
    f"@{PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['dbname']}"
)

# ===== Redis =====
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "redis" if DOCKER_ENV else "localhost"),
    "port": int(os.getenv("REDIS_PORT", "6379")),
    "db": int(os.getenv("REDIS_DB", "0")),
    "password": os.getenv("REDIS_PASSWORD", ""),
}

# ===== Celery =====
CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    f"redis://{REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}/{REDIS_CONFIG['db']}",
)

# ===== LangGraph =====
ENABLE_LANGGRAPH = os.getenv("ENABLE_LANGGRAPH", "0") == "1"  # 功能开关，默认关闭
MAX_REFLECTION_RETRIES = int(os.getenv("MAX_REFLECTION_RETRIES", "2"))
APPROVAL_TIMEOUT_SEC = int(os.getenv("APPROVAL_TIMEOUT_SEC", "300"))  # 人工审批超时 5 分钟

# ===== 业务微服务 =====
_DEFAULT_BIZ_HOST = "business_api" if DOCKER_ENV else "127.0.0.1"
INNER_ORDER_API = os.getenv("INNER_ORDER_API", f"http://{_DEFAULT_BIZ_HOST}:8001")
INNER_CRM_API = os.getenv("INNER_CRM_API", f"http://{_DEFAULT_BIZ_HOST}:8001/api/crm")
