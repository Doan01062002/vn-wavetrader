import sys
import os
import time

# Add project root to path
sys.path.append(os.getcwd())

import monitor_portfolio
from vnstock import Market

print("=== CHƯƠNG TRÌNH KIỂM THỬ GIẢ LẬP CẮT LỖ (MOCK STOP-LOSS TEST) ===")
print("Đang khởi chạy luồng kiểm tra gửi cảnh báo Telegram...")

# 1. Mock dữ liệu danh mục nắm giữ
# Đặt giá mua ảo rất cao (100.0) và stop_loss ảo rất cao (95.0) cho FPT.
# Vì giá FPT hiện tại trên thị trường là quanh 70.0 - 75.0, FPT chắc chắn sẽ vi phạm ngưỡng cắt lỗ!
test_portfolio = [
    {"symbol": "FPT", "entry_price": 100.0, "stop_loss": 95.0}
]

# Ghi đè cấu hình danh mục trong file giám sát bằng danh mục thử nghiệm
monitor_portfolio.MY_PORTFOLIO = test_portfolio

# 2. Mock hàm check giờ giao dịch để luôn trả về True khi chạy test
monitor_portfolio.is_market_hours = lambda: True

# 3. Tính toán mức hỗ trợ động thử nghiệm
monitor_portfolio.calculate_dynamic_supports()

print("\n--- CHẠY 1 VÒNG QUÉT THỬ NGHIỆM ---")
# Lấy mức hỗ trợ được tính toán
support_val = monitor_portfolio.dynamic_supports.get("FPT")
print(f"Hỗ trợ động của FPT tính được: {support_val}")

# Khởi tạo API
m = Market()
try:
    df_quote = m.equity("FPT").quote()
    if not df_quote.empty:
        close_price = df_quote.iloc[0]["close_price"]
        if close_price <= 0:
            close_price = df_quote.iloc[0].get("reference_price", 0)
        print(f"Giá FPT thực tế hiện tại trên sàn: {close_price}")
        print(f"Ngưỡng Cắt Lỗ thử nghiệm: 95.0")
        
        # Chạy kiểm tra
        print("\nBắt đầu chạy quét và so sánh các ngưỡng...")
        
        # Tính tỷ lệ lỗ ảo
        loss_pct = ((close_price - 100.0) / 100.0) * 100
        
        # Gửi tin nhắn mô phỏng trực tiếp nếu giá thực tế trên sàn (quanh 72.0) <= 95.0
        if close_price <= 95.0:
            print("=> PHÁT HIỆN VI PHẠM CẮT LỖ! Đang soạn tin nhắn và gửi về Telegram...")
            
            alert_msg = f"🚨 *[MÔ PHỎNG KIỂM THỬ] CẢNH BÁO CẮT LỖ KHẨN CẤP* 🚨\n\n"
            alert_msg += f"Mã cổ phiếu: **FPT** đã giảm chạm hoặc vượt quá ngưỡng cắt lỗ đặt ra!\n"
            alert_msg += f"───────────────────\n"
            alert_msg += f"- *Giá mua giả lập:* **100.00**\n"
            alert_msg += f"- *Ngưỡng cắt lỗ:* **95.00**\n"
            alert_msg += f"- *Giá khớp thực tế hiện tại:* **{close_price:.2f}** (Thua lỗ: **{loss_pct:.1f}%**)\n"
            alert_msg += f"───────────────────\n"
            alert_msg += f"👉 *Khuyến nghị:* Hãy thực hiện **BÁN NGAY LẬP TỨC** toàn bộ vị thế của mã này để bảo toàn vốn!"
            
            success = monitor_portfolio.send_telegram_message(alert_msg)
            if success:
                print("🟢 THÀNH CÔNG: Đã gửi thông báo cảnh báo cắt lỗ mô phỏng về Telegram!")
            else:
                print("🔴 THẤT BẠI: Lỗi khi kết nối gửi Telegram. Vui lòng kiểm tra lại cấu hình .env.")
        else:
            print("Mức giá hiện tại không vi phạm (Trường hợp hiếm xảy ra trừ khi giá FPT vượt 95.0).")
    else:
        print("🔴 LỖI: Không thể tải bảng giá thời gian thực của FPT để so sánh.")
except Exception as e:
    print(f"🔴 LỖI HỆ THỐNG: {e}")

print("\n=== KẾT THÚC KIỂM THỬ MÔ PHỎNG ===")
