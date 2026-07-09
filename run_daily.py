import sys
import os

# Thêm thư mục hiện tại vào python path
sys.path.append(os.getcwd())

from src.notifier import send_daily_report_to_telegram

if __name__ == "__main__":
    print("=== ĐANG CHẠY BÁO CÁO HÀNG NGÀY VN-WAVETRADER ===")
    success = send_daily_report_to_telegram()
    if success:
        print(">>> GỬI BÁO CÁO TELEGRAM THÀNH CÔNG!")
    else:
        print(">>> GỬI BÁO CÁO THẤT BẠI. Vui lòng kiểm tra lại cấu hình Telegram Bot Token hoặc ID Chat.")
