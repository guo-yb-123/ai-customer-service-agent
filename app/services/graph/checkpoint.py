"""
LangGraph 检查点持久化

默认使用 MemorySaver（开发/测试）。
设置环境变量 LANGGRAPH_USE_PG=1 可启用 PostgresSaver（生产）。
"""
import os
from app.utils.logging_config import get_logger
import config

logger = get_logger(__name__)

_checkpointer = None
_pg_context = None  # 保持 PostgresSaver context 存活


def create_checkpointer():
    """
    创建 LangGraph checkpointer。

    当 LANGGRAPH_USE_PG=1 时使用 PostgresSaver，
    否则使用 MemorySaver。
    """
    global _checkpointer, _pg_context

    if _checkpointer is not None:
        return _checkpointer

    use_pg = os.getenv("LANGGRAPH_USE_PG", "0") == "1"

    if use_pg:
        try:
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver

            pg = config.PG_CONFIG
            conn_string = (
                f"postgresql://{pg['user']}:{pg['password']}"
                f"@{pg['host']}:{pg['port']}/{pg['dbname']}"
            )

            # 测试连接
            conn = psycopg.connect(conn_string, connect_timeout=3)
            conn.close()

            # PostgresSaver.from_conn_string 返回 context manager
            # 我们手动进入 context 并保持它直到应用关闭
            _pg_context = PostgresSaver.from_conn_string(conn_string)
            saver = _pg_context.__enter__()
            saver.setup()

            _checkpointer = saver
            logger.info("✅ LangGraph checkpointer: PostgresSaver (host=%s:%s, db=%s)",
                         pg['host'], pg['port'], pg['dbname'])
            return _checkpointer

        except Exception as e:
            logger.warning("PostgresSaver 初始化失败 (%s)，降级为 MemorySaver", e)

    # MemorySaver（默认）
    from langgraph.checkpoint.memory import MemorySaver
    _checkpointer = MemorySaver()
    logger.info("⚠️  LangGraph checkpointer: MemorySaver (内存模式)")
    return _checkpointer


def get_checkpointer():
    """获取当前 checkpointer 实例"""
    global _checkpointer
    if _checkpointer is None:
        return create_checkpointer()
    return _checkpointer


def close_checkpointer():
    """关闭 checkpointer（应用关闭时调用）"""
    global _checkpointer, _pg_context
    if _pg_context is not None:
        try:
            _pg_context.__exit__(None, None, None)
            logger.info("PostgresSaver 已关闭")
        except Exception as e:
            logger.warning("PostgresSaver 关闭异常: %s", e)
    _checkpointer = None
    _pg_context = None
