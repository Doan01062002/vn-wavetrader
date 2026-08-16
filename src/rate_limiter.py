"""
Rate Limiter tập trung cho VN-WaveTrader.
Thay thế các time.sleep() rải rác khắp codebase bằng một cơ chế token bucket thống nhất.

Cách dùng:
    from src.rate_limiter import vnstock_limiter, groq_limiter

    # Tự động chờ nếu vượt giới hạn
    with vnstock_limiter:
        df = get_stock_ohlcv("FPT")

    # Hoặc dùng decorator
    @vnstock_limiter.throttle
    def my_api_call():
        ...
"""
import time
import threading
import logging
import functools
from typing import Callable, Any

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Token Bucket Rate Limiter thread-safe.
    
    Cho phép tối đa `max_calls` lời gọi trong mỗi khoảng `period_seconds`.
    Tự động thêm delay nếu bucket cạn kiệt (không block mãi mãi).
    """

    def __init__(self, max_calls: int, period_seconds: float, name: str = "default"):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.name = name
        self._lock = threading.Lock()
        self._calls: list[float] = []  # Timestamps của các lời gọi gần đây

    def wait(self) -> None:
        """Chờ cho đến khi có thể gọi API mà không vượt rate limit."""
        with self._lock:
            now = time.monotonic()
            window_start = now - self.period_seconds

            # Xóa các lần gọi cũ hơn cửa sổ thời gian
            self._calls = [t for t in self._calls if t > window_start]

            if len(self._calls) >= self.max_calls:
                # Tính thời gian phải chờ: khi nào lần gọi cũ nhất ra khỏi cửa sổ
                wait_time = self._calls[0] + self.period_seconds - now
                if wait_time > 0:
                    logger.debug(
                        f"[RateLimiter:{self.name}] Đang chờ {wait_time:.2f}s "
                        f"(đã gọi {len(self._calls)}/{self.max_calls} lần trong {self.period_seconds}s)"
                    )
                    # Release lock khi sleep để không chặn các thread khác
                    self._lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self._lock.acquire()
                    # Làm sạch lại sau khi ngủ
                    now = time.monotonic()
                    window_start = now - self.period_seconds
                    self._calls = [t for t in self._calls if t > window_start]

            self._calls.append(now)

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def throttle(self, func: Callable) -> Callable:
        """Decorator: tự động áp rate limit trước mỗi lần gọi hàm."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            self.wait()
            return func(*args, **kwargs)
        return wrapper

    def __repr__(self) -> str:
        return f"TokenBucketRateLimiter(name={self.name}, max={self.max_calls}/{self.period_seconds}s)"


class ExponentialBackoffRetrier:
    """
    Decorator/Context Manager hỗ trợ tự động retry với Exponential Backoff.
    
    Dùng cho các API call có thể trả về 429 (Rate Limit) hoặc lỗi mạng thoáng qua.
    
    Cách dùng:
        @retrier.retry
        def call_api():
            response = requests.get(url)
            if response.status_code == 429:
                raise Exception("429 Rate Limit")
            return response
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 5.0, max_delay: float = 60.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def retry(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = self.base_delay
            for attempt in range(self.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt >= self.max_retries:
                        logger.error(f"[Retry:{func.__name__}] Đã thử {self.max_retries} lần, thất bại: {e}")
                        raise
                    logger.warning(
                        f"[Retry:{func.__name__}] Lần {attempt + 1}/{self.max_retries} thất bại: {e}. "
                        f"Thử lại sau {delay:.1f}s..."
                    )
                    time.sleep(min(delay, self.max_delay))
                    delay *= 2  # Exponential backoff
        return wrapper


# ============================================================
# Các instance Rate Limiter cụ thể cho từng API
# ============================================================

# vnstock API: tài khoản Guest giới hạn ~20 req/phút
# Đặt 15 req/60s để có biên an toàn
vnstock_limiter = TokenBucketRateLimiter(
    max_calls=15,
    period_seconds=60.0,
    name="vnstock"
)

# Groq API: free tier giới hạn ~30 req/phút cho llama-3.1-8b
# Đặt 20 req/60s
groq_limiter = TokenBucketRateLimiter(
    max_calls=20,
    period_seconds=60.0,
    name="groq"
)

# Telegram Bot API: giới hạn 30 msg/giây cho 1 chat, nhưng tránh spam
telegram_limiter = TokenBucketRateLimiter(
    max_calls=20,
    period_seconds=1.0,
    name="telegram"
)

# Retry chung cho các lời gọi API có thể lỗi
api_retrier = ExponentialBackoffRetrier(
    max_retries=3,
    base_delay=5.0,
    max_delay=30.0
)
