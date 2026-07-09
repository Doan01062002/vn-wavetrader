import os
import json
import logging

# Thử import psycopg2 để sử dụng PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import Json
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LOCAL_JSON_FILE = "virtual_portfolio.json"

def get_db_connection():
    """
    Trả về kết nối PostgreSQL nếu DATABASE_URL được cấu hình trong biến môi trường.
    """
    if not HAS_POSTGRES:
        return None
        
    db_url = os.getenv("DATABASE_URL")
    if not db_url or db_url == "your_database_url_here":
        return None
        
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        logging.error(f"Không thể kết nối đến PostgreSQL: {e}")
        return None

def init_db():
    """
    Khởi tạo bảng virtual_portfolios trong Database nếu chưa tồn tại.
    """
    conn = get_db_connection()
    if conn is None:
        logging.info("Sử dụng chế độ lưu trữ File JSON cục bộ.")
        return False
        
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS virtual_portfolios (
                    id VARCHAR(50) PRIMARY KEY,
                    data JSONB
                )
            """)
            conn.commit()
            logging.info("Khởi tạo bảng virtual_portfolios trên PostgreSQL thành công.")
            return True
    except Exception as e:
        logging.error(f"Lỗi khởi tạo bảng PostgreSQL: {e}")
        return False
    finally:
        conn.close()

def load_portfolio_data() -> dict:
    """
    Tải dữ liệu danh mục ảo từ Database PostgreSQL (nếu có) hoặc dự phòng file JSON.
    """
    conn = get_db_connection()
    if conn is None:
        # Fallback về đọc file JSON
        if os.path.exists(LOCAL_JSON_FILE):
            try:
                with open(LOCAL_JSON_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Lỗi đọc file JSON danh mục: {e}")
        return {"cash": 100000000.0, "positions": [], "history": []}
        
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM virtual_portfolios WHERE id = 'default'")
            row = cur.fetchone()
            if row:
                return row[0]
            else:
                # Nếu chưa có, tạo mặc định
                default_data = {"cash": 100000000.0, "positions": [], "history": []}
                cur.execute(
                    "INSERT INTO virtual_portfolios (id, data) VALUES ('default', %s)",
                    [Json(default_data)]
                )
                conn.commit()
                return default_data
    except Exception as e:
        logging.error(f"Lỗi tải danh mục từ PostgreSQL: {e}")
        # Fallback đọc file JSON
        if os.path.exists(LOCAL_JSON_FILE):
            with open(LOCAL_JSON_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"cash": 100000000.0, "positions": [], "history": []}
    finally:
        conn.close()

def save_portfolio_data(portfolio: dict) -> bool:
    """
    Lưu dữ liệu danh mục ảo lên Database PostgreSQL (nếu có) hoặc dự phòng file JSON.
    """
    # Đồng thời lưu vào cả local file JSON để lưu trữ cục bộ dự phòng 2 lớp
    try:
        with open(LOCAL_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Lỗi ghi file JSON dự phòng cục bộ: {e}")
        
    conn = get_db_connection()
    if conn is None:
        return True # Đã lưu thành công vào file JSON
        
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO virtual_portfolios (id, data)
                VALUES ('default', %s)
                ON CONFLICT (id)
                DO UPDATE SET data = EXCLUDED.data
            """, [Json(portfolio)])
            conn.commit()
            logging.info("Đã đồng bộ lưu danh mục ảo lên Database đám mây PostgreSQL.")
            return True
    except Exception as e:
        logging.error(f"Lỗi lưu danh mục lên PostgreSQL: {e}")
        return False
    finally:
        conn.close()

# Khởi tạo bảng ngay khi import module
try:
    init_db()
except Exception:
    pass
