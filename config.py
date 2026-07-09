# Cấu hình dự án VN-WaveTrader

# Danh sách cổ phiếu theo dõi mặc định (thường là các mã VN30 có thanh khoản tốt)
DEFAULT_WATCHLIST = [
    "FPT",  # Công nghệ FPT
    "HPG",  # Hòa Phát (Thép)
    "SSI",  # Chứng khoán SSI
    "TCB",  # Techcombank
    "MBB",  # MBBank
    "MWG",  # Thế Giới Di Động
    "ACB",  # Á Châu Bank
    "STB",  # Sacombank
    "VNM",  # Vinamilk
    "VCB",  # Vietcombank
    "VIC",  # Vingroup
    "VHM"   # Vinhomes
]

# Cấu hình tham số chỉ báo kỹ thuật cho chiến lược lướt sóng
INDICATOR_PARAMS = {
    "RSI": {
        "period": 14,
        "oversold": 30,
        "overbought": 70
    },
    "MACD": {
        "fast": 12,
        "slow": 26,
        "signal": 9
    },
    "BOLLINGER_BANDS": {
        "period": 20,
        "std_dev": 2
    },
    "EMA_SHORT": 20,
    "EMA_LONG": 50,
    "ATR_PERIOD": 14
}

# Cấu hình mô hình AI Gemini
GEMINI_CONFIG = {
    "model_name": "gemini-2.0-flash",
    "temperature": 0.2,
    "top_p": 0.9,
    "top_k": 40
}

# Danh mục cổ phiếu thực tế bạn đang nắm giữ để giám sát cắt lỗ thời gian thực
# symbol: Mã cổ phiếu
# entry_price: Giá mua của bạn (Đơn vị: nghìn VNĐ, ví dụ FPT giá 135.5)
# stop_loss: Giá cắt lỗ cố định (Ví dụ: 128.0). Nếu đặt là None, hệ thống tự động đặt -5% so với giá mua.
MY_PORTFOLIO = [
    {"symbol": "FPT", "entry_price": 72.0, "stop_loss": 69.5},
    {"symbol": "HPG", "entry_price": 28.0, "stop_loss": 26.5}
]

