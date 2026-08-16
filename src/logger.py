"""
Cấu hình Logging tập trung cho toàn bộ dự án VN-WaveTrader.
Import module này một lần duy nhất ở entrypoint để cấu hình logger toàn cục.
Các module khác chỉ cần: logger = logging.getLogger(__name__)
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

_configured = False


def setup_logging(log_file: str = "portfolio_monitor.log", level: int = logging.INFO) -> None:
    """
    Cấu hình logging toàn cục một lần duy nhất.
    - FileHandler: ghi vào file với rotation (max 5MB × 3 backup files)
    - StreamHandler: ghi ra stdout với UTF-8 encoding an toàn (fix Windows crash)
    """
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # === File Handler với rotation (tránh log phình vô hạn) ===
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB mỗi file
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # === Stream Handler với UTF-8 encoding an toàn cho Windows ===
    # Fix lỗi UnicodeEncodeError khi terminal Windows không hỗ trợ UTF-8
    if sys.stdout is not None:
        try:
            # Python 3.7+: reconfigure encoding an toàn
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            stream_handler = logging.StreamHandler(sys.stdout)
        except Exception:
            stream_handler = logging.StreamHandler()

        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    # Tắt bớt log từ các thư viện bên thứ ba (giảm noise)
    for noisy_lib in ['urllib3', 'httpx', 'httpcore', 'vnstock']:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("Logging đã được khởi tạo thành công (UTF-8, Rotation).")


def get_logger(name: str) -> logging.Logger:
    """
    Trả về logger với tên module. Gọi ở đầu mỗi file:
        from src.logger import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
