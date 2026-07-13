# TÀI LIỆU ĐẶC TẢ CHI TIẾT DỰ ÁN VN-WAVETRADER
*(Tài liệu chuẩn hóa dùng để đưa vào Google AI Studio để tái cấu trúc hoặc nâng cấp dự án)*

---

## 1. TỔNG QUAN DỰ ÁN (OVERVIEW)
**VN-WaveTrader** là hệ thống hỗ trợ đầu tư lướt sóng (swing trading) ngắn hạn tự động hóa hoàn toàn cho thị trường chứng khoán Việt Nam. 
Hệ thống được thiết kế ở chế độ **Headless (không giao diện)**, giao tiếp và vận hành hai chiều 100% qua ứng dụng nhắn tin **Telegram (Chatbot & Callbacks)** nhằm tối ưu hóa tài nguyên server và giảm chi phí vận hành.

---

## 2. KIẾN TRÚC HỆ THỐNG & SƠ ĐỒ THƯ MỤC
Dự án được xây dựng bằng **Python 3.11** và cấu trúc thành các module độc lập:

```text
dau_tu/
│
├── .env                         # Cấu hình khóa bảo mật (Gemini API, Telegram Bot, DB URL)
├── config.py                    # Cấu hình danh mục cổ phiếu & tham số chỉ báo kỹ thuật
├── requirements.txt             # Khai báo các thư viện Python cần thiết
│
├── src/
│   ├── __init__.py              # Khởi tạo gói Python
│   ├── data_fetcher.py          # Module tải dữ liệu chứng khoán lịch sử & real-time
│   ├── indicators.py            # Module tính toán các chỉ báo kỹ thuật (RSI, MACD, BB, SuperTrend...)
│   ├── portfolio.py             # Module tối ưu hóa tỷ trọng vốn (PyPortfolioOpt)
│   ├── llm_analyzer.py          # Giao tiếp với AI Gemini phân tích tin tức & đồ thị
│   ├── notifier.py              # Xây dựng báo cáo định dạng Markdown & gửi về Telegram Bot
│   ├── paper_trader.py          # Quản lý ví ảo, lệnh giao dịch ảo & điểm chốt chặn Kelley/ATR
│   └── database.py              # Lưu trữ dữ liệu danh mục ảo qua PostgreSQL (hoặc File JSON dự phòng)
│
├── run_daily.py                 # Script chạy định kỳ EOD lúc 15:15 để quét và gửi báo cáo
└── monitor_portfolio.py         # Tiến trình chạy nền 24/7 đón nhận Bot tương tác và giám sát real-time
```

---

## 3. THÔNG TIN CHI TIẾT TỪNG MODULE & FILE NGUỒN

### 3.1. Cấu hình hệ thống ([config.py](file:///d:/DuAn/dau_tu/config.py))
* **Mục đích**: Lưu trữ các tham số cài đặt tĩnh của hệ thống.
* **Các tham số chính**:
  * `DEFAULT_WATCHLIST`: Danh sách mã cổ phiếu theo dõi mặc định (thường là các mã thuộc rổ VN30 có thanh khoản tốt: FPT, HPG, SSI, TCB, MBB, MWG...).
  * `INDICATOR_PARAMS`: Tham số mặc định cho các chỉ báo kỹ thuật (RSI 14, MACD 12/26/9, Bollinger Bands 20/2, EMA Short 20, EMA Long 50, ATR 14).
  * `GEMINI_CONFIG`: Thiết lập mô hình AI (mặc định dùng `gemini-2.0-flash`, `temperature=0.2`).
  * `MY_PORTFOLIO`: Danh mục cổ phiếu thực tế của người dùng để giám sát real-time (Mã, Giá mua, Cắt lỗ cố định).

### 3.2. Kết nối cơ sở dữ liệu ([src/database.py](file:///d:/DuAn/dau_tu/src/database.py))
* **Mục đích**: Quản lý lưu trữ trạng thái danh mục ví ảo (ví dụ: số dư tiền mặt, các vị thế mua ảo, lịch sử giao dịch).
* **Cơ chế**:
  * Ưu tiên kết nối cơ sở dữ liệu **PostgreSQL** (thông qua Supabase hoặc dịch vụ đám mây khác) bằng thư viện `psycopg2` thông qua biến môi trường `DATABASE_URL`.
  * Nếu không có kết nối Database, tự động chuyển về chế độ dự phòng ghi đọc tệp tin cục bộ **`virtual_portfolio.json`**.
  * Chứa hàm khởi tạo bảng tự động `init_db()` và hàm tải/lưu dữ liệu: `load_portfolio_data()`, `save_portfolio_data()`.

### 3.3. Tải dữ liệu chứng khoán ([src/data_fetcher.py](file:///d:/DuAn/dau_tu/src/data_fetcher.py))
* **Mục đích**: Tải dữ liệu tài chính thông qua thư viện **`vnstock`** (phiên bản v4+).
* **Các hàm chính**:
  * `get_stock_ohlcv(symbol, length, interval)`: Tải dữ liệu lịch sử giá OHLCV (Mặc định 1D, có hỗ trợ khung tuần 1W). Chuẩn hóa các cột và sắp xếp theo ngày tăng dần.
  * `get_company_info(symbol)`: Lấy thông tin cơ bản giới thiệu doanh nghiệp.
  * `get_company_ratios(symbol)`: Lấy chỉ số tài chính (P/E, P/B, ROE, ROA...).
  * `get_vn30_symbols()`: Lấy danh sách các mã cổ phiếu trong rổ VN30.
  * `get_stock_news(symbol, limit)`: Lấy tin tức cập nhật mới nhất của doanh nghiệp.

### 3.4. Phân tích chỉ báo kỹ thuật ([src/indicators.py](file:///d:/DuAn/dau_tu/src/indicators.py))
* **Mục đích**: Sử dụng thư viện `ta` (pandas technical analysis) để tính toán các tín hiệu kỹ thuật.
* **Các chỉ báo hỗ trợ**:
  * **RSI**: Xác định vùng quá mua/quá bán.
  * **MACD**: Xác định điểm giao cắt xu hướng.
  * **Bollinger Bands**: Đo lường biến động và độ lệch giá.
  * **EMA (Short/Long)**: Bộ lọc xu hướng giá trung/ngắn hạn.
  * **Stochastic Oscillator**: Điểm đảo chiều động lượng.
  * **ATR (Average True Range)**: Tính biên độ biến động để thiết lập điểm dừng lỗ/chốt lời động.
  * **Volume SMA20**: Lọc bùng nổ thanh khoản (Volume breakout confirmation - tối thiểu gấp 1.5 lần trung bình).
  * **SuperTrend**: Xác định xu hướng mua/bán chính.
  * **Hỗ trợ / Kháng cự**: Hàm tự động tìm đỉnh/đáy lịch sử trong 60 phiên gần nhất.
* **Hàm chính**:
  * `calculate_indicators(df, symbol)`: Trả về DataFrame chứa đầy đủ các cột chỉ báo.
  * `check_swing_signals(df, symbol)`: Chạy thuật toán chấm điểm kỹ thuật từ `-5` (rất xấu) đến `+5` (rất tốt) để đưa ra đề xuất hành động `BUY` / `SELL` / `NEUTRAL`.

### 3.5. Tối ưu hóa tỷ trọng danh mục ([src/portfolio.py](file:///d:/DuAn/dau_tu/src/portfolio.py))
* **Mục đích**: Phân bổ tỷ trọng dòng vốn tối ưu giữa các mã cổ phiếu trong danh sách tiềm năng mua.
* **Thư viện sử dụng**: `PyPortfolioOpt`.
* **Thuật toán hỗ trợ**:
  * **HRP (Hierarchical Risk Parity)**: Phân bổ rủi ro phân tầng (Khuyên dùng cho lướt sóng do không bị phụ thuộc vào tính toán lợi nhuận kỳ vọng dài hạn).
  * **Minimum Volatility**: Tối thiểu hóa biến động của danh mục.
  * **Max Sharpe Ratio**: Tối ưu hóa tỷ lệ Sharpe dựa trên lợi nhuận kỳ vọng lịch sử.

### 3.6. Trợ lý Phân tích AI ([src/llm_analyzer.py](file:///d:/DuAn/dau_tu/src/llm_analyzer.py))
* **Mục đích**: Kết nối với mô hình ngôn ngữ lớn Google Gemini để phân tích sâu tin tức và đồ thị.
* **Chức năng**:
  * Gửi dữ liệu chỉ báo kỹ thuật kết hợp cùng tin tức mới nhất của doanh nghiệp cho Gemini để đưa ra đánh giá khách quan về cơ hội đầu tư.
  * Đánh giá sentiment (sắc thái tiêu cực/tích cực) của các tiêu đề tin tức theo thang điểm từ `-1.0` đến `+1.0`.

### 3.7. Bộ soạn thông báo Telegram ([src/notifier.py](file:///d:/DuAn/dau_tu/src/notifier.py))
* **Mục đích**: Tổng hợp dữ liệu thành báo cáo hoàn chỉnh dưới định dạng Telegram Markdown.
* **Nội dung báo cáo hàng ngày (EOD) bao gồm**:
  1. **Độ rộng thị trường VN30 (Market Breadth Filter)**: % số mã nằm trên EMA20. Nếu dưới 40%, tự động chuyển sang chế độ phòng thủ rủi ro chung (không mở vị thế mua mới).
  2. **Tín hiệu MUA tiềm năng**: Danh sách các mã có bùng nổ kỹ thuật cùng thanh khoản vượt trội.
  3. **Tín hiệu BÁN cảnh báo**: Các mã vi phạm xu hướng kỹ thuật hoặc SuperTrend.
  4. **Tích hợp Nút bấm tương tác nhanh (Inline Keyboard)**: Đính kèm nút bấm dạng `[💼 Xác nhận Mua & Giám sát [Mã]]` dưới mỗi tín hiệu mua để người dùng bấm trực tiếp từ điện thoại.

### 3.8. Giao dịch ví ảo ([src/paper_trader.py](file:///d:/DuAn/dau_tu/src/paper_trader.py))
* **Mục đích**: Giả lập việc mua/bán cổ phiếu thực tế để theo dõi và huấn luyện mô hình.
* **Cơ chế**:
  * Cho phép mua ảo với số dư khởi tạo 100 triệu VNĐ.
  * Tự động đặt mức dừng lỗ (Stop Loss - SL) và chốt lời (Take Profit - TP) động theo biến động ATR thực tế của mã đó khi xác nhận mua (mặc định SL = Giá mua - 2*ATR, TP = Giá mua + 4*ATR).
  * Hàm `check_and_execute_auto_orders(current_prices)` sẽ so sánh giá khớp hiện tại trong phiên để tự động kích hoạt lệnh SL/TP ảo và gửi tin nhắn thông báo về Telegram.

---

## 4. LUỒNG VẬN HÀNH CHÍNH (EXECUTION FLOWS)

### Luồng 1: Báo cáo quét tự động EOD (`run_daily.py`)
* Được kích hoạt tự động vào cuối ngày giao dịch (ví dụ 15:15) từ Thứ 2 đến Thứ 5.
* Tiến trình chạy:
  1. Quét 15 mã VN30 lớn nhất để tính độ rộng thị trường.
  2. Quét các mã trong `DEFAULT_WATCHLIST` để phát hiện tín hiệu lướt sóng.
  3. Sử dụng Gemini để phân tích nhận định thị trường vĩ mô và tin tức nóng của mã tốt nhất trong phiên.
  4. Tạo tin nhắn và gửi về Telegram của người dùng.

### Luồng 2: Giám sát Realtime & Bot tương tác (`monitor_portfolio.py`)
* Là một dịch vụ chạy nền liên tục (Daemon Service).
* Khởi chạy đồng thời 3 luồng (Threads):
  1. **Luồng Telegram Polling**: Liên tục lắng nghe sự kiện nút bấm từ người dùng trên Telegram (ví dụ: bấm nút "Xác nhận Mua"). Khi nhận được, luồng này sẽ thêm vị thế vào ví ảo (`paper_trader`).
  2. **Luồng Scheduler Báo cáo**: Chạy vòng lặp kiểm tra giờ. Khi đến 15:15 từ Thứ 2 đến Thứ 6, nó sẽ tự động kích hoạt tiến trình gửi báo cáo ngày tương tự như `run_daily.py`.
  3. **Luồng Giám sát chính**: Chạy vòng lặp liên tục trong giờ giao dịch (9:00 - 11:30 và 13:00 - 14:45 từ Thứ 2 - Thứ 6). Cứ mỗi 2 phút, nó lấy giá thời gian thực của các mã trong danh mục nắm giữ. Nếu giá chạm ngưỡng dừng lỗ/chốt lời hoặc thủng mốc hỗ trợ kỹ thuật sàn, nó lập tức gửi cảnh báo khẩn cấp lên Telegram và tự động chốt lệnh ảo.

---

## 5. THAM SỐ CẤU HÌNH BIẾN MÔI TRƯỜNG (`.env`)
```env
# API Key của Google Gemini AI (để kích hoạt Trợ lý ảo nhận định)
GEMINI_API_KEY=your_gemini_api_key_here

# Token của Telegram Bot tự tạo qua @BotFather
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# ID Chat của bạn lấy qua @userinfobot
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# URL kết nối PostgreSQL (Ví dụ: Supabase PostgreSQL Connection String)
DATABASE_URL=postgresql://user:password@host:port/database
```

---

## 6. CÁC ĐIỂM YẾU HIỆN TẠI & ĐỀ XUẤT NÂNG CẤP KHI LÀM LẠI
Khi đưa dự án này cho Google Studio xây dựng lại, hãy yêu cầu giải quyết các vấn đề sau:

1. **Nâng cấp SDK Gemini**: 
   * *Hiện tại*: Đang dùng thư viện đã lỗi thời `google-generativeai` (`google.generativeai`).
   * *Yêu cầu*: Chuyển đổi hoàn toàn sang bộ thư viện hiện đại **`google-genai`** (`google.genai`) để đảm bảo tính ổn định và tương thích lâu dài.

2. **Khắc phục lỗi mã hóa Tiếng Việt trên Windows Terminal (`UnicodeEncodeError`)**:
   * *Hiện tại*: Các câu lệnh in ra màn hình hoặc log của hệ thống chứa tiếng Việt có dấu sẽ bị crash ngay lập tức nếu chạy trên Windows Command Prompt/PowerShell mặc định.
   * *Yêu cầu*: Tự động cấu hình `sys.stdout` sử dụng mã hóa `utf-8` khi khởi tạo ứng dụng, hoặc cấu hình xử lý ngoại lệ encoding an toàn để hệ thống không bị crash đột ngột.

3. **Cơ chế Khởi chạy ngầm & Quản lý tiến trình (Process Daemon)**:
   * *Hiện tại*: Chưa có cơ chế quản lý tự động bật lại khi server khởi động lại hoặc khi script bị lỗi đột ngột.
   * *Yêu cầu*: Viết các file script cấu hình Docker, Systemd Service (cho Linux) hoặc hướng dẫn cấu hình chi tiết cho Windows Task Scheduler/NSSM để đảm bảo tiến trình `monitor_portfolio.py` luôn tự khởi chạy ngầm 24/7.

4. **Tối ưu hóa API Rate Limit**:
   * *Hiện tại*: Việc quét nhiều mã cùng lúc bằng Vnstock và Gemini có thể gây ra lỗi giới hạn tần suất gọi API (429 Rate Limit).
   * *Yêu cầu*: Thiết lập hàng đợi (Queue) có giãn cách thời gian (rate-limiting delay) động và cơ chế tự động thử lại (Retry with Exponential Backoff) khi gặp lỗi 429.
