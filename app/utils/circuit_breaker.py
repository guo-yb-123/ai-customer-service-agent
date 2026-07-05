"""
外部服务熔断器 + 重试机制
"""
import time
import functools
import threading
from enum import Enum
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"          # 正常
    OPEN = "open"              # 熔断
    HALF_OPEN = "half_open"    # 半开（探测恢复）


class CircuitBreaker:
    """
    熔断器：连续失败达到阈值后熔断，一段时间后尝试半开探测。

    使用方式：
        cb = CircuitBreaker("llm_api", failure_threshold=3, timeout=30)

        @cb
        def call_external_api():
            ...
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        half_open_max: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_count = 0
                    logger.info("熔断器 [%s] 进入半开状态", self.name)
            return self._state

    def success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_count += 1
                if self._half_open_count >= self.half_open_max:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info("熔断器 [%s] 恢复关闭", self.name)
            else:
                self._failure_count = 0

    def failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("熔断器 [%s] 打开（连续失败 %s 次）", self.name, self._failure_count)

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if self.state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"服务 [{self.name}] 已熔断，请稍后再试"
                )
            try:
                result = func(*args, **kwargs)
                self.success()
                return result
            except Exception as e:
                self.failure()
                raise e
        return wrapper


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出的异常"""
    pass


def retry_on_failure(
    max_retries: int = 3,
    backoff: float = 1.0,
    exceptions: tuple = (Exception,),
):
    """
    重试装饰器：指数退避重试

    Args:
        max_retries: 最大重试次数
        backoff: 初始退避秒数（每次翻倍）
        exceptions: 触发重试的异常类型

    使用方式：
        @retry_on_failure(max_retries=3, backoff=0.5)
        def call_api():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        wait = backoff * (2 ** attempt)
                        logger.warning(
                            "%s 第 %s/%s 次失败，%ss 后重试: %s",
                            func.__name__, attempt + 1, max_retries, wait, e,
                        )
                        time.sleep(wait)
            raise last_exc  # type: ignore
        return wrapper
    return decorator
