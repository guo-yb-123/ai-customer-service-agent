"""
统一日志配置：支持 trace_id、结构化输出、日志轮转
"""
import logging
import logging.handlers
import json
import os
import uuid
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# 请求级 trace_id，贯穿整个请求生命周期
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """获取当前请求的 trace_id，不存在则生成一个"""
    tid = trace_id_var.get()
    if not tid:
        tid = str(uuid.uuid4())[:12]
        trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    trace_id_var.set(trace_id)


class JSONFormatter(logging.Formatter):
    """JSON 结构化日志格式（生产环境）"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """开发环境彩色控制台格式"""

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    cyan = "\x1b[36;20m"

    FORMATS = {
        logging.DEBUG: grey + "%(asctime)s.%(msecs)03d" + reset + " [%(trace_id)s] %(name)s %(levelname)s %(message)s",
        logging.INFO: cyan + "%(asctime)s.%(msecs)03d" + reset + " [%(trace_id)s] %(name)s %(levelname)s %(message)s",
        logging.WARNING: yellow + "%(asctime)s.%(msecs)03d" + reset + " [%(trace_id)s] %(name)s %(levelname)s %(message)s",
        logging.ERROR: red + "%(asctime)s.%(msecs)03d" + reset + " [%(trace_id)s] %(name)s %(levelname)s %(message)s",
        logging.CRITICAL: bold_red + "%(asctime)s.%(msecs)03d" + reset + " [%(trace_id)s] %(name)s %(levelname)s %(message)s",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.DEBUG])
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        record.trace_id = get_trace_id()
        return formatter.format(record)


def setup_logging(
    level: int = logging.INFO,
    json_output: bool = False,
    log_file: str | None = None,
) -> None:
    """
    初始化全局日志配置

    Args:
        level: 日志级别
        json_output: True=JSON格式（生产）, False=彩色控制台（开发）
        log_file: 日志文件路径，None=只输出到控制台
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler
    root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # 文件轮转 handler
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)

    # 降低第三方库日志噪音
    for lib in ("uvicorn.access", "httpx", "httpcore", "urllib3", "celery"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    root_logger.info("日志系统初始化完成 (json=%s)", json_output)


def get_logger(name: str) -> logging.Logger:
    """获取带 trace_id 的 logger"""
    return logging.getLogger(name)
