"""
LangFuse 可观测性集成 — LLM 调用追踪
使用方式:
  设置环境变量 LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY 启用
  不设置则自动降级为本地日志，不影响业务

追踪内容:
  - 每次 LLM 调用的延迟、Token 用量、模型名称
  - Tool 调用链（哪个 Skill 被触发、耗时多少）
  - 会话维度聚合（同一 session_id 的调用归入一个 trace）
"""
import os
import time
import functools
from contextlib import contextmanager
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# 检查是否配置了 LangFuse
LANGFUSE_ENABLED = bool(
    os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
)

if LANGFUSE_ENABLED:
    try:
        import langfuse  # type: ignore
        _client = langfuse.Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        logger.info("LangFuse 已启用: %s", os.getenv("LANGFUSE_HOST", "cloud.langfuse.com"))
    except ImportError:
        LANGFUSE_ENABLED = False
        _client = None
        logger.warning("langfuse 包未安装，可观测性降级为本地日志")
else:
    _client = None


class TraceContext:
    """追踪上下文 — 同一会话的多次调用归入一个 trace"""

    def __init__(self):
        self._traces: dict[str, dict] = {}  # {session_id: trace_info}

    def start_trace(self, session_id: str, user_id: str, question: str):
        if not LANGFUSE_ENABLED or not _client:
            return None
        try:
            trace = _client.trace(
                name="agent-chat",
                session_id=session_id,
                user_id=user_id,
                metadata={"question": question[:200]},
            )
            self._traces[session_id] = {"trace": trace, "start": time.time()}
            return trace
        except Exception as e:
            logger.warning("LangFuse trace 创建失败: %s", e)
            return None

    def log_tool_call(self, session_id: str, tool_name: str, tool_args: dict, result: dict, latency: float):
        if not LANGFUSE_ENABLED or session_id not in self._traces:
            return
        try:
            trace = self._traces[session_id]["trace"]
            trace.span(
                name=f"tool:{tool_name}",
                input=tool_args,
                output={"success": result.get("success"), "text": str(result.get("text", ""))[:200]},
                metadata={"tool": tool_name, "latency_s": round(latency, 3)},
            )
        except Exception as e:
            logger.warning("LangFuse span 记录失败: %s", e)

    def log_llm_call(self, session_id: str, model: str, messages: list, response: str, latency: float):
        if not LANGFUSE_ENABLED or session_id not in self._traces:
            return
        try:
            trace = self._traces[session_id]["trace"]
            trace.generation(
                name=f"llm:{model}",
                model=model,
                input=messages[-1] if messages else {},
                output=response[:500] if response else "",
                metadata={"model": model, "latency_s": round(latency, 3)},
            )
        except Exception as e:
            logger.warning("LangFuse generation 记录失败: %s", e)

    def end_trace(self, session_id: str, final_reply: str):
        if not LANGFUSE_ENABLED or session_id not in self._traces:
            return
        try:
            trace_info = self._traces.pop(session_id)
            trace_info["trace"].update(
                output=final_reply[:500],
                metadata={"total_latency_s": round(time.time() - trace_info["start"], 2)},
            )
        except Exception as e:
            logger.warning("LangFuse trace 结束失败: %s", e)


# 全局单例
trace_context = TraceContext()


def track_llm(func):
    """装饰器：自动追踪 LLM 调用"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        latency = time.time() - start
        if LANGFUSE_ENABLED:
            logger.info("[LangFuse] LLM call: %s (%.2fs)", func.__name__, latency)
        return result
    return wrapper
