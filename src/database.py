"""
Module quản lý kết nối và lưu trữ dữ liệu danh mục ảo.

Cải tiến v2:
- Connection Pool (ThreadedConnectionPool) thay vì tạo kết nối mới mỗi lần
- threading.Lock bảo vệ toàn bộ I/O (fix race condition)
- Không còn gọi init_db() khi import (bỏ side-effect)
- Schema validation cơ bản trước khi lưu
- Hỗ trợ fallback 2 lớp: PostgreSQL → file JSON cục bộ
"""
import os
import json
import logging
import threading

logger = logging.getLogger(__name__)

# ==============================================================
# PostgreSQL Connection Pool
# ==============================================================
try:
    import psycopg2
    from psycopg2.extras import Json
    from psycopg2.pool import ThreadedConnectionPool
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

LOCAL_JSON_FILE = "virtual_portfolio.json"

# Connection pool singleton và lock bảo vệ I/O
_pool: "ThreadedConnectionPool | None" = None
_pool_lock = threading.Lock()
_portfolio_lock = threading.Lock()  # Lock cho mọi thao tác read/write portfolio

# Schema validation
_PORTFOLIO_REQUIRED_KEYS = {"cash", "positions", "history"}
_POSITION_REQUIRED_KEYS = {"symbol", "buy_price", "quantity", "buy_date", "stop_loss", "take_profit"}


def _validate_portfolio(data: dict) -> bool:
    """Kiểm tra sơ bộ cấu trúc portfolio trước khi lưu."""
    if not isinstance(data, dict):
        return False
    if not _PORTFOLIO_REQUIRED_KEYS.issubset(data.keys()):
        return False
    if not isinstance(data.get("cash"), (int, float)):
        return False
    if not isinstance(data.get("positions"), list):
        return False
    if not isinstance(data.get("history"), list):
        return False
    return True


def _get_pool() -> "ThreadedConnectionPool | None":
    """Khởi tạo hoặc trả về connection pool đang tồn tại (lazy init, thread-safe)."""
    global _pool
    if not HAS_POSTGRES:
        return None

    db_url = os.getenv("DATABASE_URL")
    if not db_url or db_url == "your_database_url_here":
        return None

    with _pool_lock:
        if _pool is None:
            try:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    dsn=db_url
                )
                logger.info("PostgreSQL Connection Pool khởi tạo thành công (1-5 connections).")
            except Exception as e:
                logger.error(f"Không thể khởi tạo PostgreSQL Connection Pool: {e}")
                _pool = None
        return _pool


def init_db() -> bool:
    """
    Khởi tạo bảng virtual_portfolios trong Database nếu chưa tồn tại.
    Gọi explicit từ entrypoint — không tự động chạy khi import.
    """
    pool = _get_pool()
    if pool is None:
        logger.info("Sử dụng chế độ lưu trữ File JSON cục bộ (không có PostgreSQL).")
        return False

    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS virtual_portfolios (
                    id VARCHAR(50) PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
        logger.info("Khởi tạo bảng virtual_portfolios trên PostgreSQL thành công.")
        return True
    except Exception as e:
        logger.error(f"Lỗi khởi tạo bảng PostgreSQL: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            pool.putconn(conn)


def load_portfolio_data() -> dict:
    """
    Tải dữ liệu danh mục ảo (thread-safe).
    Ưu tiên: PostgreSQL → file JSON cục bộ → default trống.
    """
    default_data = {"cash": 100_000_000.0, "positions": [], "history": []}

    with _portfolio_lock:
        pool = _get_pool()

        # --- Fallback: đọc file JSON ---
        if pool is None:
            if os.path.exists(LOCAL_JSON_FILE):
                try:
                    with open(LOCAL_JSON_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if _validate_portfolio(data):
                        return data
                    else:
                        logger.warning("File JSON danh mục có cấu trúc không hợp lệ, dùng dữ liệu mặc định.")
                except Exception as e:
                    logger.error(f"Lỗi đọc file JSON danh mục: {e}")
            return default_data.copy()

        # --- PostgreSQL ---
        conn = None
        try:
            conn = pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM virtual_portfolios WHERE id = 'default'")
                row = cur.fetchone()
                if row:
                    return row[0]
                else:
                    # Khởi tạo record mặc định
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "INSERT INTO virtual_portfolios (id, data) VALUES ('default', %s)",
                            [Json(default_data)]
                        )
                    conn.commit()
                    return default_data.copy()
        except Exception as e:
            logger.error(f"Lỗi tải danh mục từ PostgreSQL, fallback về JSON: {e}")
            if conn:
                conn.rollback()
            # Fallback về file JSON
            if os.path.exists(LOCAL_JSON_FILE):
                try:
                    with open(LOCAL_JSON_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return default_data.copy()
        finally:
            if conn:
                pool.putconn(conn)


def save_portfolio_data(portfolio: dict) -> bool:
    """
    Lưu dữ liệu danh mục ảo (thread-safe).
    Luôn lưu vào file JSON trước (backup cục bộ), sau đó sync lên PostgreSQL nếu có.
    """
    if not _validate_portfolio(portfolio):
        logger.error("Từ chối lưu: dữ liệu portfolio không hợp lệ (thiếu key hoặc kiểu dữ liệu sai).")
        return False

    with _portfolio_lock:
        # --- Luôn lưu vào file JSON cục bộ (backup 2 lớp) ---
        try:
            with open(LOCAL_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(portfolio, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Lỗi ghi file JSON dự phòng cục bộ: {e}")

        pool = _get_pool()
        if pool is None:
            return True  # Đã lưu thành công vào file JSON

        # --- Sync lên PostgreSQL ---
        conn = None
        try:
            conn = pool.getconn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO virtual_portfolios (id, data, updated_at)
                    VALUES ('default', %s, NOW())
                    ON CONFLICT (id)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                """, [Json(portfolio)])
            conn.commit()
            logger.debug("Đã đồng bộ danh mục ảo lên PostgreSQL.")
            return True
        except Exception as e:
            logger.error(f"Lỗi lưu danh mục lên PostgreSQL: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                pool.putconn(conn)


def close_pool() -> None:
    """Đóng connection pool khi ứng dụng shutdown (graceful shutdown)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
                logger.info("PostgreSQL Connection Pool đã được đóng.")
            except Exception as e:
                logger.error(f"Lỗi khi đóng connection pool: {e}")
            finally:
                _pool = None
