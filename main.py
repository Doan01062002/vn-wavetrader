"""
VN-WaveTrader — Main Entrypoint

Khởi chạy đồng thời:
1. Luồng Telegram Bot Polling (lắng nghe tương tác người dùng)
2. Luồng giám sát danh mục thời gian thực (SL/TP, hỗ trợ kỹ thuật, tin tức)
3. Scheduler báo cáo tự động (08:30 / 14:45 / 16:30)

Cải tiến so với monitor_portfolio.py cũ:
- Logging tập trung và nhất quán (UTF-8, rotation)
- Graceful shutdown khi nhận Ctrl+C hoặc SIGTERM
- init_db() gọi explicit ở đây, không phải khi import
- Signal handler cho Docker/Systemd
"""
import os
import sys
import signal
import logging
import threading

from dotenv import load_dotenv

# Tải biến môi trường trước tất cả imports khác
load_dotenv()

# Cấu hình logging tập trung (phải gọi trước mọi logger khác)
from src.logger import setup_logging
setup_logging(log_file="portfolio_monitor.log")

logger = logging.getLogger(__name__)

# Khởi tạo database tables (explicit, không auto-run khi import)
from src.database import init_db, close_pool
init_db()

# Import các module chính
from src.telegram_bot import telegram_polling_loop, stop_polling
from src.realtime_monitor import run_portfolio_monitor
from src.scheduler import start_scheduler, stop_scheduler


def _shutdown_handler(signum, frame):
    """Graceful shutdown khi nhận SIGTERM hoặc SIGINT."""
    logger.info(f"Nhận tín hiệu dừng ({signum}). Đang tắt hệ thống gracefully...")
    stop_polling()
    stop_scheduler()
    close_pool()
    logger.info("Hệ thống đã dừng an toàn.")
    sys.exit(0)


def main():
    logger.info("=" * 60)
    logger.info("   VN-WAVETRADER SYSTEM STARTUP")
    logger.info("=" * 60)
    logger.info(f"Python: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")

    # Đăng ký signal handlers để Docker/Systemd có thể dừng container sạch sẽ
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    # Kiểm tra biến môi trường bắt buộc
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        logger.error("TELEGRAM_BOT_TOKEN chưa được cấu hình trong .env. Bot sẽ chạy ở chế độ im lặng.")
    if not os.getenv("GROQ_API_KEY"):
        logger.warning("GROQ_API_KEY chưa được cấu hình. Báo cáo AI sẽ dùng chế độ demo.")

    # Khởi chạy Telegram Bot polling trong daemon thread
    bot_thread = threading.Thread(
        target=telegram_polling_loop,
        name="TelegramPollingThread",
        daemon=True
    )
    bot_thread.start()
    logger.info("Luồng Telegram Bot đã được khởi động.")

    # Khởi động Scheduler báo cáo tự động (08:30 / 14:45 / 16:30)
    start_scheduler()

    # Chạy vòng lặp giám sát chính (blocking — ở thread chính)
    logger.info("Khởi động vòng lặp giám sát danh mục real-time...")
    try:
        run_portfolio_monitor()
    except KeyboardInterrupt:
        logger.info("Tiến trình bị dừng bởi người dùng (Ctrl+C).")
    finally:
        stop_polling()
        stop_scheduler()
        close_pool()
        logger.info("VN-WaveTrader đã tắt sạch sẽ.")


if __name__ == "__main__":
    main()
