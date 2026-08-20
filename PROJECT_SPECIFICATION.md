# TÀI LIỆU ĐẶC TẢ KỸ THUẬT TOÀN DIỆN DỰ ÁN VN-WAVETRADER
**Hệ Thống Giao Dịch Thuật Toán Lướt Sóng & Cố Vấn Quản Trị Rủi Ro Tự Động Hóa Cho Thị Trường Chứng Khoán Việt Nam**
*Phiên bản tài liệu: 2.5.0 (Cập nhật kiến trúc chuẩn hóa v2.0+)*

---

## 1. TỔNG QUAN DỰ ÁN (EXECUTIVE SUMMARY & SYSTEM OBJECTIVES)

### 1.1. Giới thiệu
**VN-WaveTrader** là hệ thống giao dịch thuật toán (Algorithmic Trading) và cố vấn đầu tư lướt sóng (Swing Trading) ngắn hạn tự động hóa hoàn toàn cho thị trường chứng khoán Việt Nam (HOSE, HNX, UPCoM, trọng tâm rổ VN30).

Hệ thống được thiết kế theo kiến trúc **100% Headless Daemon Service (không giao diện web cồng kềnh)**, tương tác và điều khiển 2 chiều độc quyền qua ứng dụng tin nhắn **Telegram (Bot Commands, Persistent Reply Keyboard & Inline Callback Buttons)**. Mô hình này giúp loại bỏ hoàn toàn chi phí duy trì Web Server/Front-end UI, tối ưu hóa tài nguyên phần cứng (chỉ cần 256MB - 512MB RAM), đảm bảo tính phản hồi tức thì và khả năng vận hành liên tục 24/7 trên các máy chủ đám mây giá rẻ hoặc container Docker.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 VN-WAVETRADER V2.0+ ARCHITECTURE                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
          ┌────────────────────────────────┴────────────────────────────────┐
          ▼                                                                 ▼
 ┌───────────────────┐                                            ┌───────────────────┐
 │   DATA INGESTION  │                                            │  REALTIME DAEMON  │
 │  • vnstock (v4+)  │                                            │  • 2-min Poller   │
 │  • Cafef/VnExpress│                                            │  • Dynamic SL/TP  │
 │  • Quotes/Trades  │                                            │  • Emergency News │
 └─────────┬─────────┘                                            └─────────┬─────────┘
           │                                                                │
           ▼                                                                ▼
 ┌───────────────────┐      ┌──────────────────────────────┐      ┌───────────────────┐
 │ TECHNICAL ENGINE  │      │    FUNDAMENTAL & CANSLIM     │      │   PAPER TRADING   │
 │ • 10+ Indicators  │─────▶│ • 100-pt Minervini / CANSLIM │◀────▶│ • 100M VND Wallet │
 │ • Scoring (-5..+5)│      │ • Quarterly / Annual YoY     │      │ • ATR Trailing SL │
 │ • Multi-stage Gate│      │ • RS 60d vs VN-Index         │      │ • 2% Risk & Kelly │
 └─────────┬─────────┘      └──────────────┬───────────────┘      └─────────┬─────────┘
           │                               │                                │
           ▼                               ▼                                ▼
 ┌───────────────────┐      ┌──────────────────────────────┐      ┌───────────────────┐
 │   AI & LLM (Groq) │      │      CHART GENERATOR         │      │   TELEGRAM BOT    │
 │ • LLaMA 3.3 70B   │─────▶│ • Matplotlib Dark Theme      │─────▶│ • 2-way Polling   │
 │ • Sentiment Anal. │      │ • Candlestick + EMA + Volume │      │ • 1-Click Buy BTN │
 │ • Macro Executive │      │ • Auto sendPhoto API         │      │ • Rich Dashboards │
 └───────────────────┘      └──────────────────────────────┘      └───────────────────┘
```

### 1.2. Các mục tiêu kỹ thuật cốt lõi
1. **Quét và lọc tín hiệu lướt sóng đa tầng (Multi-Stage Signal Filtering Pipeline)**:
   - *Bộ lọc kỹ thuật nâng cao*: Kết hợp RSI, MACD, EMA 20/50, Bollinger Bands, Stochastic Oscillator (%K, %D), ATR, Volume SMA20 (Breakout gấp 1.5 lần), ADX (Đo xung lực xu hướng, trừ điểm sideway) và SuperTrend.
   - *Hỗ trợ / Kháng cự tự động*: Sử dụng thuật toán tìm cực trị hình học `scipy.signal.argrelextrema` trên chuỗi giá 60 phiên gần nhất.
   - *Bộ lọc bảo vệ vốn vĩ mô (Hard Gate)*: Đối chiếu độ rộng thị trường VN30 với đường EMA20. Tự động vô hiệu hóa toàn bộ tín hiệu Mua mới khi thị trường rơi vào xu hướng giảm chung.
   - *Bộ lọc sóng ngành (Sector Strength Filter)*: Phân tích tỷ lệ cổ phiếu nằm trên EMA20 trong 7 nhóm ngành cốt lõi (Ngân hàng, Thép, Chứng khoán, Bán lẻ, Công nghệ, Bất động sản, Tiêu dùng).
   - *Bộ lọc xu hướng trung hạn (Weekly Trend Filter)*: Xác thực xu hướng trên biểu đồ tuần (1W) EMA10w vs EMA30w.
2. **Chấm điểm cơ bản & Chất lượng tăng trưởng CANSLIM / Minervini (100 điểm)**:
   - Tự động bóc tách báo cáo tài chính quý/năm, tính toán tăng trưởng LNST quý YoY (C), tăng trưởng năm & ROE (A), khoảng cách đỉnh 52 tuần (N), đột biến khối lượng (S), sức mạnh giá tương đối so với VN-Index trong 60 phiên (L), và giao dịch gom ròng khối ngoại kèm Beta (I).
3. **Phân tích trí tuệ nhân tạo (AI & LLM Engine)**:
   - Tích hợp Groq API SDK (LLaMA 3.3 70B Versatile & LLaMA 3.1 8B Instant) với cơ chế điều tiết Token Bucket Rate Limiter và Exponential Backoff Retrier.
   - Tự động sinh báo cáo phân tích chiến lược, tóm tắt vĩ mô và đo lường chỉ số tâm lý đám đông (Fear & Greed Index) từ RSS News (VnExpress Kinh doanh / Cafef).
4. **Quản trị danh mục & Giao dịch ví ảo (Quantitative Risk Management & Paper Trading)**:
   - Mô phỏng danh mục vốn ảo 100,000,000 VNĐ, quản lý lịch sử giao dịch và định giá tài sản ròng (Net Worth) theo thời gian thực.
   - Định cỡ vị thế chuẩn toán học: **Half-Kelly Criterion** (tối đa 25%/mã) và **Định cỡ cố định rủi ro 2% tài sản** (`calculate_fixed_risk_qty`).
   - Thiết lập điểm dừng lỗ (Stop Loss - SL) và chốt lời (Take Profit - TP) động theo biến động giá thực tế (ATR).
   - Cơ chế bảo vệ vị thế trong phiên: **Chặn lãi động (Trailing Stop-loss)** kéo mốc SL theo đỉnh mới và **Chốt lời từng phần (Scaling Out)** bán 50% vị thế tại TP1 và dời SL của 50% còn lại về giá vốn (Break-even).
5. **Giám sát thời gian thực & Lập lịch tự động 24/7**:
   - Vòng lặp giám sát quét giá mỗi 2 phút trong các khung giờ giao dịch Việt Nam (09:00 - 11:30 & 13:00 - 14:45 từ Thứ 2 đến Thứ 6).
   - Lập lịch thông minh bằng `APScheduler` gửi 3 bản tin tự động: 08:30 (Báo cáo tâm lý sáng), 14:45 (Quét tín hiệu intraday), 16:30 (Tổng kết ngày & PnL).
   - Cảnh báo khẩn cấp tin tức tiêu cực (Negative News Alert) nếu AI chấm điểm sắc thái $\le -0.6$.

---

## 2. CẤU TRÚC THƯ MỤC & SƠ ĐỒ MÃ NGUỒN

```text
dau_tu/
├── .env                              # Cấu hình biến môi trường bảo mật (Tokens, API Keys, Database URL)
├── .env.example                      # File mẫu biến môi trường phục vụ cấu hình
├── .gitignore                        # Cấu hình bỏ qua file tạm, cache và dữ liệu nhạy cảm
├── .dockerignore                     # Tối ưu hóa dung lượng build Docker Image
├── config.py                         # Cấu hình danh mục theo dõi mặc định & tham số chỉ báo kỹ thuật
├── requirements.txt                  # Danh sách thư viện phụ thuộc Python
├── Dockerfile                        # Docker containerization tối ưu với uv và Linux slim
├── docker-compose.yml                # Cấu hình triển khai production với log rotation & resource limits
├── main.py                           # Điểm khởi chạy chính duy nhất của toàn bộ hệ thống (Entrypoint)
├── optimized_params.json             # Lưu trữ bộ tham số kỹ thuật tối ưu hóa riêng cho từng mã (Grid Search)
├── virtual_portfolio.json            # Cơ sở dữ liệu JSON cục bộ lưu trữ danh mục ví ảo (Fallback)
├── processed_news.json               # Bộ nhớ đệm (Cache) URL các tin tức đã xử lý để tránh spam cảnh báo
├── portfolio_monitor.log             # File log vận hành hệ thống có cơ chế Rotation (5MB x 3)
├── test_monitor.py                   # Bộ kiểm thử Unit Test toàn diện bằng pytest (11 test cases)
├── test_vnstock.py                   # Script kiểm thử tích hợp dữ liệu nhanh từ vnstock
│
├── .github/
│   └── workflows/
│       └── ci.yml                    # CI Pipeline tự động compile, chạy pytest và build Docker Image
│
├── temp_charts/                      # Thư mục chứa các ảnh biểu đồ nến kỹ thuật sinh tự động
│   └── *.png                         # File ảnh chart candlestick gửi qua Telegram
│
└── src/
    ├── __init__.py                   # Định danh Python Package
    ├── logger.py                     # Cấu hình Logging tập trung (UTF-8, RotatingFileHandler, Clean Stdout)
    ├── rate_limiter.py               # Module Token Bucket Rate Limiter & Exponential Backoff Retrier
    ├── database.py                   # Quản trị cơ sở dữ liệu PostgreSQL (Connection Pool) & JSON Fallback
    ├── data_fetcher.py               # Tải dữ liệu OHLCV, BCTC, tin tức, khớp lệnh cá mập (vnstock v4+)
    ├── indicators.py                 # Tính toán 10+ chỉ báo kỹ thuật, SuperTrend, Hỗ trợ/Kháng cự, Swing Score
    ├── portfolio.py                  # Thuật toán tối ưu hóa tỷ trọng phân bổ vốn (PyPortfolioOpt HRP / Min Vol)
    ├── llm_analyzer.py               # Trợ lý AI kết nối Groq SDK (LLaMA 3.3 70B / 3.1 8B) sinh báo cáo chuyên sâu
    ├── sentiment_analyzer.py         # Cào tin tức VnExpress/Cafef RSS & chấm điểm tâm lý thị trường
    ├── fundamental_screener.py       # Hệ thống chấm điểm sức khỏe tài chính & tiêu chuẩn CANSLIM (100 điểm)
    ├── chart_generator.py            # Vẽ đồ thị nến Candlestick + Volume + Chỉ báo dạng Dark Theme (Matplotlib)
    ├── backtest.py                   # Động cơ kiểm thử chiến lược giao dịch lịch sử (Backtesting.py)
    ├── parameter_tuning.py           # Thuật toán Grid Search tìm kiếm tham số tối ưu per-ticker
    ├── paper_trader.py               # Quản lý ví ảo 100M, định cỡ Half-Kelly, rủi ro 2%, Trailing SL & Scaling Out
    ├── notifier.py                   # Pipeline lọc đa tầng, tổng hợp báo cáo Telegram & tạo nút 1-Click Buy
    ├── realtime_monitor.py           # Daemon giám sát real-time giá, chạm SL/TP, thủng hỗ trợ & tin tức tiêu cực
    ├── scheduler.py                  # Bộ lập lịch tự động APScheduler (Bản tin 08:30 / 14:45 / 16:30)
    └── telegram_bot.py               # Quản trị tương tác Bot 2 chiều, Menu bàn phím, Commands & Callbacks
```

---

## 3. CHI TIẾT ĐẶC TẢ TỪNG MODULE TRONG HỆ THỐNG

### 3.1. Điểm Khởi Chạy Hệ Thống ([main.py](file:///d:/DuAn/dau_tu/main.py))
* **Mục đích**: Là Controller/Orchestrator trung tâm quản lý toàn bộ vòng đời khởi động, vận hành đồng thời các luồng và thực hiện quy trình tắt an toàn (Graceful Shutdown).
* **Kiến trúc vận hành**:
  1. **Khởi tạo môi trường & Logging**: Tải `.env` qua `dotenv`, thiết lập logger toàn cục với UTF-8 và rotation qua `src.logger.setup_logging()`.
  2. **Khởi tạo Database Explicit**: Gọi `src.database.init_db()` để tạo bảng PostgreSQL nếu có (không chạy side-effects ngầm khi import).
  3. **Đăng ký Signal Handlers**: Đăng ký `signal.SIGTERM` và `signal.SIGINT` trỏ về `_shutdown_handler` để Docker/Systemd có thể yêu cầu dừng container sạch sẽ mà không làm hỏng dữ liệu I/O danh mục.
  4. **Khởi chạy luồng Telegram Polling (Daemon Thread)**: Khởi tạo `threading.Thread(target=telegram_polling_loop, name="TelegramPollingThread", daemon=True)`.
  5. **Khởi chạy Scheduler (Background Process)**: Kích hoạt `src.scheduler.start_scheduler()` để quản lý 3 mốc lập lịch tự động.
  6. **Vòng lặp giám sát Real-time (Main Thread Blocking)**: Chạy `src.realtime_monitor.run_portfolio_monitor()` tại luồng chính để giám sát giá và chốt lệnh.

---

### 3.2. Logging Tập Trung ([src/logger.py](file:///d:/DuAn/dau_tu/src/logger.py))
* **Mục đích**: Đảm bảo toàn bộ log được định dạng chuẩn, ghi nhận chi tiết, an toàn tuyệt đối với font tiếng Việt trên terminal Windows.
* **Cơ chế**:
  * `setup_logging(log_file="portfolio_monitor.log", level=logging.INFO)`:
    - **RotatingFileHandler**: Ghi log vào file với kích thước tối đa 5MB, lưu trữ tối đa 3 file backup (`portfolio_monitor.log.1`, `portfolio_monitor.log.2`, `portfolio_monitor.log.3`), bảng mã `utf-8`.
    - **StreamHandler**: Reconfigure `sys.stdout` với `encoding='utf-8', errors='replace'` giúp khắc phục triệt để lỗi crash hệ thống `UnicodeEncodeError` thường gặp trên CMD/PowerShell Windows.
    - **Noise Filter**: Tự động tăng log level lên `WARNING` cho các thư viện bên thứ ba có độ ồn cao (`urllib3`, `httpx`, `httpcore`, `vnstock`).

---

### 3.3. Bộ Điều Tiết Tần Suất & Khả Năng Chống Lỗi ([src/rate_limiter.py](file:///d:/DuAn/dau_tu/src/rate_limiter.py))
* **Mục đích**: Thay thế toàn bộ các lệnh `time.sleep()` tùy tiện bằng cơ chế Token Bucket Rate Limiter và Exponential Backoff Retrier tập trung, bảo vệ hệ thống khỏi việc bị khóa IP hoặc gặp lỗi HTTP 429 Too Many Requests.
* **Các thành phần cốt lõi**:
  * `TokenBucketRateLimiter(max_calls, period_seconds, name)`:
    - Thread-safe thông qua `threading.Lock`.
    - Tự động tính toán cửa sổ trượt (sliding window), giải phóng lock trong lúc sleep để không chặn các worker thread khác.
    - Hỗ trợ cả Context Manager (`with vnstock_limiter:`) và Decorator (`@vnstock_limiter.throttle`).
  * `ExponentialBackoffRetrier(max_retries=3, base_delay=5.0, max_delay=60.0)`:
    - Tự động bắt lỗi ngoại lệ, chờ với thời gian tăng theo cấp số nhân ($5s \rightarrow 10s \rightarrow 20s$) trước khi retry.
  * **Các thực thể cấu hình cụ thể**:
    - `vnstock_limiter`: Giới hạn 15 requests / 60 giây (tài khoản Guest vnstock).
    - `groq_limiter`: Giới hạn 20 requests / 60 giây (Groq Free Tier).
    - `telegram_limiter`: Giới hạn 20 messages / 1 giây.
    - `api_retrier`: Tối đa 3 lần thử lại, độ trễ cơ sở 5.0 giây.

---

### 3.4. Quản Lý Cơ Sở Dữ Liệu 2 Lớp ([src/database.py](file:///d:/DuAn/dau_tu/src/database.py))
* **Mục đích**: Lưu trữ bền vững thông tin danh mục ví ảo, số dư tiền mặt, các vị thế mở và lịch sử chốt lệnh.
* **Cơ chế Fallback 2 lớp**:
  1. **Lớp 1 - Đám mây PostgreSQL (Supabase / Neon / Render)**:
     - Sử dụng `psycopg2.pool.ThreadedConnectionPool` (kết nối từ 1 đến 5 connections) tối ưu hiệu năng và quản lý tài nguyên connection.
     - Tự động khởi tạo bảng:
       ```sql
       CREATE TABLE IF NOT EXISTS virtual_portfolios (
           id VARCHAR(50) PRIMARY KEY,
           data JSONB NOT NULL,
           updated_at TIMESTAMPTZ DEFAULT NOW()
       );
       ```
     - Dữ liệu được lưu trữ dưới dạng `JSONB` với id khóa chính là `'default'`.
  2. **Lớp 2 - File Cục Bộ (JSON Backup)**:
     - Tự động đọc/ghi file `virtual_portfolio.json` trên ổ đĩa.
     - Khi lưu, hệ thống luôn ghi file JSON cục bộ trước (Local persistence), sau đó mới đồng bộ lên PostgreSQL (Cloud persistence). Nếu mất mạng hoặc PostgreSQL gặp sự cố, hệ thống tự động fallback đọc file JSON mà không làm gián đoạn luồng thực thi.
  3. **Thread Safety & Schema Validation**:
     - Sử dụng `_portfolio_lock = threading.Lock()` bao bọc toàn bộ thao tác read/write.
     - Hàm `_validate_portfolio(data)` kiểm tra tính toàn vẹn của schema (bắt buộc có `cash`, `positions`, `history` với đúng kiểu dữ liệu) trước khi ghi.

---

### 3.5. Trích Xuất Dữ Liệu Thị Trường ([src/data_fetcher.py](file:///d:/DuAn/dau_tu/src/data_fetcher.py))
* **Mục đích**: Giao tiếp với API chứng khoán `vnstock` (phiên bản v4+), xử lý chuẩn hóa dữ liệu, bọc cache và bảo vệ timeout chống treo mạng.
* **Các chức năng chính**:
  * `get_stock_ohlcv(symbol, length=365, interval="1D")`:
    - Tải dữ liệu lịch sử giá qua `Market().equity(symbol).ohlcv()`.
    - Chuẩn hóa cột: Đổi tên `'time'` sang `'Date'`, đặt làm Index, chuẩn hóa kiểu số cho `'open'`, `'high'`, `'low'`, `'close'`, `'volume'`, sắp xếp thời gian tăng dần.
    - **Bộ nhớ đệm (In-memory Cache)**: Lưu trữ kết quả thành công trong 30 phút (`CACHE_DURATION_SECONDS = 1800`).
    - **Negative Cache**: Nếu mã lỗi hoặc API không có dữ liệu, chỉ cache lỗi 5 phút (`300s`) để tránh gọi API lặp lại liên tục gây quá tải.
    - **Thread Watchdog Protection**: Thực thi lệnh tải trong Thread riêng có `thread.join(timeout=25.0)` kết hợp `socket.setdefaulttimeout(30)` để triệt tiêu tình trạng treo socket vĩnh viễn.
    - Tích hợp cơ chế tự động thử lại (Retry) 3 lần với exponential backoff.
  * `get_company_info(symbol)`: Trích xuất thông tin giới thiệu, ngành nghề, vốn điều lệ từ `Reference().company(symbol).info()`.
  * `get_company_ratios(symbol)`: Trích xuất các chỉ số tài chính P/E, P/B, ROE, ROA, Net Margin từ `Fundamental().equity(symbol).ratio()`.
  * `get_vn30_symbols()`: Lấy danh sách 30 mã VN30 từ `Reference().equity.list_by_group("VN30")`. Có danh sách tĩnh 30 mã dự phòng cứng nếu API bị timeout 15s.
  * `get_stock_news(symbol, limit=5)`: Trích xuất danh sách tin tức doanh nghiệp mới nhất kèm tiêu đề, thời gian xuất bản và liên kết URL.
  * `get_intraday_flow(symbol)`: Phân tích sổ lệnh khớp trong phiên (`Market().equity(symbol).trades()`), tính toán:
    - Tổng khối lượng mua chủ động vs bán chủ động.
    - Phát hiện lệnh lớn dòng tiền cá mập (định nghĩa: lệnh có giá trị $\ge 50,000,000$ VNĐ), tính số lượng lệnh và tỷ trọng dòng tiền cá mập chiếm trên tổng khối lượng giao dịch.

---

### 3.6. Phân Tích Kỹ Thuật & Chấm Điểm Tín Hiệu ([src/indicators.py](file:///d:/DuAn/dau_tu/src/indicators.py))
* **Mục đích**: Tính toán toàn bộ các chỉ báo kỹ thuật cốt lõi và thực hiện thuật toán chấm điểm động từ `-5.0` đến `+5.0`.
* **Danh mục chỉ báo tính toán (`calculate_indicators`)**:
  1. **RSI (Relative Strength Index)**: Đo động lượng mua/bán (chu kỳ 14 hoặc tham số tối ưu per-ticker).
  2. **MACD (Moving Average Convergence Divergence)**: Đường MACD, Signal Line (12/26/9) và Histogram Diff.
  3. **Bollinger Bands**: Dải trên, dải dưới, dải giữa (20 nến, độ lệch chuẩn 2.0) và chỉ số vị trí giá `%B` (`bb_percent`).
  4. **EMA (Exponential Moving Average)**: EMA ngắn hạn (20 phiên) và EMA dài hạn (50 phiên).
  5. **Stochastic Oscillator**: Đường `%K` và `%D` (14, 3, 3) phát hiện điểm giao cắt động lượng tại vùng cực trị.
  6. **ATR (Average True Range)**: Đo lường biên độ biến động thực tế (14 phiên) phục vụ tính SL/TP động.
  7. **Volume SMA20**: Khối lượng trung bình 20 phiên xác nhận bùng nổ thanh khoản.
  8. **ADX (Average Directional Index)**: Đo cường độ xu hướng (chu kỳ 14) cùng đường `+DI` và `-DI`.
  9. **SuperTrend**: Tính toán dải biên trên/dưới dựa trên ATR (chu kỳ 10, hệ số nhân 3.0), xác định xu hướng chính `supertrend_dir` (+1: Tăng, -1: Giảm).
  10. **Hỗ trợ / Kháng cự tự động (`find_support_resistance`)**: Áp dụng thuật toán `scipy.signal.argrelextrema` trên chuỗi giá đóng cửa 60 phiên để bóc tách các mức đáy/đỉnh cục bộ gần nhất.

* **Thuật toán Chấm điểm Tín hiệu Swing (`check_swing_signals`)**:

| Chỉ báo kỹ thuật | Điều kiện kích hoạt | Điểm số tác động |
| :--- | :--- | :---: |
| **Xu hướng EMA** | Giá > EMA20 > EMA50 (Uptrend) | `+1.0` |
| | Giá < EMA20 < EMA50 (Downtrend) | `-1.0` |
| **Giao cắt EMA** | Xuất hiện Golden Cross mới (EMA20 cắt lên EMA50) | `+2.0` |
| | Xuất hiện Death Cross mới (EMA20 cắt xuống EMA50) | `-2.0` |
| **SuperTrend** | SuperTrend đảo chiều từ Giảm sang TĂNG | `+2.5` |
| | SuperTrend đảo chiều từ Tăng sang GIẢM | `-2.5` |
| **Giao cắt MACD** | MACD cắt lên Signal Line (Golden Cross) | `+2.0` |
| | MACD cắt xuống Signal Line (Death Cross) | `-2.0` |
| **Vùng RSI** | RSI cắt lên từ vùng Quá bán ($< 30$) | `+2.0` |
| | RSI cắt xuống từ vùng Quá mua ($> 70$) | `-2.0` |
| **Bollinger Bands** | Giá đóng cửa thủng biên dưới ($%B < 0$) - Kỳ vọng hồi quy | `+1.5` |
| | Giá đóng cửa vượt biên trên ($%B > 1$) - Nguy cơ quá đà | `-1.5` |
| **Volume Breakout** | Khối lượng $> 1.5 \times \text{SMA20}$ đồng thuận với nến xanh tăng giá | `+1.5` |
| **Stochastic** | `%K` cắt lên `%D` tại vùng quá bán ($< 25$) | `+1.5` |
| | `%K` cắt xuống `%D` tại vùng quá mua ($> 75$) | `-1.5` |
| **Cường độ ADX** | $\text{ADX} \ge 25$ và $+DI > -DI$ (Xu hướng tăng mạnh) | `+0.5` |
| | $\text{ADX} \ge 25$ và $-DI > +DI$ (Xu hướng giảm mạnh) | `-0.5` |
| | $\text{ADX} < 20$ (Thị trường không có xu hướng / Sideway) | $\text{Score} \times 0.7$ (Giảm 30%) |

* **Quy tắc phân loại trạng thái hành động (Status Mapping)**:
  - $\text{Score} \ge +3.0$: **`STRONG BUY`** (Mua mạnh)
  - $+1.0 \le \text{Score} < +3.0$: **`BUY`** (Mua)
  - $-1.0 < \text{Score} < +1.0$: **`NEUTRAL`** (Trung tính / Theo dõi)
  - $-3.0 < \text{Score} \le -1.0$: **`SELL`** (Bán)
  - $\text{Score} \le -3.0$: **`STRONG SELL`** (Bán mạnh / Thoát vị thế)

---

### 3.7. Tối Ưu Hóa Tỷ Trọng Danh Mục ([src/portfolio.py](file:///d:/DuAn/dau_tu/src/portfolio.py))
* **Mục đích**: Phân bổ tỷ trọng phân bổ vốn khoa học giữa các mã cổ phiếu xuất hiện tín hiệu MUA trong cùng phiên quét bằng thư viện `PyPortfolioOpt`.
* **Các phương pháp hỗ trợ**:
  1. **Hierarchical Risk Parity (HRP)** (*Phương pháp khuyên dùng*): Sử dụng kỹ thuật phân cụm ma trận hiệp biến lợi nhuận hàng ngày. Không yêu cầu tính ma trận đảo hoặc kỳ vọng lợi nhuận lịch sử, hoạt động cực kỳ ổn định cho giao dịch ngắn hạn.
  2. **Minimum Volatility**: Tối thiểu hóa phương sai danh mục dựa trên ma trận hiệp biến mẫu `sample_cov`.
  3. **Max Sharpe Ratio**: Tối ưu hóa tỷ lệ lợi nhuận / rủi ro dựa trên dữ liệu giá quá khứ (tự động fallback về HRP nếu ma trận không xác định dương).

---

### 3.8. Trí Tuệ Nhân Tạo & Báo Cáo Chuyên Sâu ([src/llm_analyzer.py](file:///d:/DuAn/dau_tu/src/llm_analyzer.py))
* **Mục đích**: Tích hợp mô hình ngôn ngữ lớn (LLM) thông qua **Groq SDK** chính thức để phân tích tổng hợp dữ liệu định lượng và định tính.
* **Cấu hình mô hình**:
  - Model chính: `llama-3.3-70b-versatile` (hoặc `llama-3.1-8b-instant`).
  - Temperature: `0.1` (Tối ưu tính nhất quán và tính toán logic).
  - Rate limiter & retry: Áp dụng `@groq_limiter.throttle` và `@api_retrier.retry`.
* **Nội dung sinh báo cáo AI (`analyze_stock_with_ai`)**:
  1. Đánh giá xu hướng ngắn hạn (EMA, MACD, RSI, ADX, SuperTrend, Volume).
  2. Phân tích tài chính cơ bản & Điểm số chất lượng CANSLIM & Tin tức nóng mới nhất.
  3. Xây dựng kế hoạch giao dịch (Khuyến nghị, Vùng giá mua, Target chốt lời, Điểm cắt lỗ cứng).
  4. Cảnh báo các rủi ro tiềm ẩn đối với mã cổ phiếu và thị trường chung.
  *Hệ thống tích hợp sẵn chế độ sinh báo cáo Demo dự phòng khi người dùng chưa cấu hình `GROQ_API_KEY`.*

---

### 3.9. Phân Tích Tâm Lý Thị Trường & Tin Tức ([src/sentiment_analyzer.py](file:///d:/DuAn/dau_tu/src/sentiment_analyzer.py))
* **Mục đích**: Đo lường sắc thái tâm lý đám đông toàn thị trường và từng cổ phiếu.
* **Cơ chế**:
  * `fetch_cafef_rss_news()`: Cào 15 tin tức thị trường kinh doanh mới nhất từ RSS feed VnExpress/Cafef bằng Regex.
  * `evaluate_sentiment_with_ai(news_list)`: Gửi toàn bộ danh sách tiêu đề tin tức cho LLM phân tích theo lô (Batch Processing) để tiết kiệm token và tránh rate limit.
  * LLM trả về danh sách điểm số từ `-1.0` (Cực kỳ tiêu cực) đến `+1.0` (Cực kỳ tích cực).
  * **Phân loại tâm lý vĩ mô**:
    - Điểm $\ge +0.40$: *HƯNG PHẤN TỘT ĐỘ (Extreme Greed)*
    - $+0.15 \le \text{Điểm} < +0.40$: *LẠC QUAN (Greed)*
    - $-0.15 < \text{Điểm} < +0.15$: *TRUNG TÍNH (Neutral)*
    - $-0.40 < \text{Điểm} \le -0.15$: *BI QUAN (Fear)*
    - $\text{Điểm} \le -0.40$: *HOẢNG LOẠN TỘT ĐỘ (Extreme Fear)*

---

### 3.10. Chấm Điểm Cơ Bản & CANSLIM / Minervini ([src/fundamental_screener.py](file:///d:/DuAn/dau_tu/src/fundamental_screener.py))
* **Mục đích**: Đánh giá chất lượng cổ phiếu trên thang điểm 100 theo phương pháp CANSLIM của William O'Neil và Mark Minervini.
* **Cơ cấu thang điểm chi tiết (100 điểm)**:

| Thành phần | Tiêu chí đánh giá | Trọng số tối đa | Điều kiện đạt điểm tối đa |
| :---: | :--- | :---: | :--- |
| **C** | Tăng trưởng lợi nhuận Quý gần nhất YoY | **20 điểm** | Net Profit tăng trưởng $\ge 25\%$ so với cùng kỳ năm trước |
| **A** | Tăng trưởng lợi nhuận Năm & Chỉ số ROE | **20 điểm** | $\text{ROE} \ge 15\%$ (10đ) và LNST năm tăng $\ge 15\%$ (10đ) |
| **N** | Giá cổ phiếu so với Đỉnh 52 tuần | **15 điểm** | Giá hiện tại nằm sát đỉnh 52 tuần (cách đỉnh $\le 15\%$) |
| **S** | Cung - Cầu thanh khoản giao dịch | **15 điểm** | Khối lượng phiên gần nhất $\ge 1.5 \times \text{SMA20}$ |
| **L** | Cổ phiếu dẫn dắt (RS vs VN-Index 60 phiên) | **15 điểm** | Hiệu suất 3 tháng qua vượt trội VN-Index $\ge 15\%$ |
| **I** | Bảo trợ tổ chức & Khối ngoại gom ròng | **15 điểm** | Khối ngoại mua ròng $\ge 5\%$ tổng KLGD và $0.7 \le \text{Beta} \le 1.5$ |

* **Xếp loại chất lượng CANSLIM**:
  - $\ge 80$ điểm: **SUPERB** (Cực kỳ xuất sắc)
  - $70 - 79$ điểm: **STRONG** (Rất tốt)
  - $55 - 69$ điểm: **NEUTRAL** (Trung bình)
  - $< 55$ điểm: **WEAK** (Yếu - Cần thận trọng tránh mua)

---

### 3.11. Trình Tạo Đồ Thị Nến Kỹ Thuật ([src/chart_generator.py](file:///d:/DuAn/dau_tu/src/chart_generator.py))
* **Mục đích**: Tự động kết xuất ảnh biểu đồ nến kỹ thuật dark theme chất lượng cao gửi trực tiếp qua Telegram `sendPhoto` khi người dùng yêu cầu phân tích chi tiết.
* **Đặc điểm kỹ thuật**:
  - Sử dụng thư viện `matplotlib` với backend không giao diện `matplotlib.use('Agg')` chạy ngầm an toàn trên máy chủ.
  - Bảng màu hiện đại: Background `#1a1a2e` / `#16213e`, nến tăng xanh `#26de81`, nến giảm đỏ `#ff6b6b`.
  - Khung trên: Vẽ Candlestick 60 phiên gần nhất, đường EMA20 (vàng `#ffd93d`), EMA50 (tím `#6c5ce7`), dải Bollinger Bands phủ bóng mờ và ghim nhãn mũi tên **▲ MUA** hoặc **▼ BÁN**.
  - Khung dưới: Cột Volume phân màu theo phiên và đường Volume SMA20.
  - Lưu ảnh vào `temp_charts/{symbol}_chart.png` và gửi tự động qua Telegram API.

---

### 3.12. Backtesting & Tối Ưu Tham Số ([src/backtest.py](file:///d:/DuAn/dau_tu/src/backtest.py) & [src/parameter_tuning.py](file:///d:/DuAn/dau_tu/src/parameter_tuning.py))
* **Mục đích**: Kiểm chứng hiệu suất chiến lược trên dữ liệu quá khứ và tự động tinh chỉnh tham số (Hyperparameter Tuning) theo đặc tính từng mã cổ phiếu.
* **Chiến lược kiểm thử**:
  1. `EmaCrossStrategy`: Mua khi EMA ngắn cắt lên EMA dài, bán khi cắt xuống.
  2. `RsiReversionStrategy`: Mua khi RSI cắt lên từ vùng quá bán, bán khi cắt xuống từ quá mua.
* **Thuật toán Grid Search per-ticker**:
  - Quét 12 tổ hợp EMA (Short: 10, 15, 20, 25; Long: 30, 45, 50, 60) và 18 tổ hợp RSI.
  - Sử dụng phương thức tạo dynamic subclass để khắc phục triệt để lỗi `PicklingError` của multiprocessing trên môi trường Windows.
  - Lưu cấu hình tham số có Return cao nhất vào file `optimized_params.json` để hệ thống tự động nạp khi tính toán chỉ báo cho mã đó.

---

### 3.13. Quản Trị Danh Mục Ảo & Quản Trị Vốn ([src/paper_trader.py](file:///d:/DuAn/dau_tu/src/paper_trader.py))
* **Mục đích**: Mô phỏng giao dịch thực tế, bảo vệ tài sản và quản trị tỷ lệ rủi ro nghiêm ngặt.
* **Các thuật toán định cỡ & vận hành**:
  1. **Định cỡ vị thế theo Rủi ro cố định 2% Net Worth (`calculate_fixed_risk_qty`)**:
     $$\text{Số lượng CP} = \left\lfloor \frac{\text{Net Worth} \times 2\%}{(\text{Giá Mua} - \text{Giá Cắt Lỗ}) \times 1000} \right\rfloor_{\text{Lô 100}}$$
     Đảm bảo nếu lệnh chạm điểm cắt lỗ, tổng mức thiệt hại của tài khoản không bao giờ vượt quá 2% tổng tài sản ròng.
  2. **Định cỡ theo công thức Half-Kelly (`calculate_kelly_sizing`)**:
     $$f^* = p - \frac{1 - p}{b}, \quad \text{Tỷ trọng đi vốn} = \min\left(25\%, \frac{f^*}{2}\right)$$
     Với $p$ là Win Rate lịch sử và $b$ là tỷ lệ Lãi TB / Lỗ TB. Giới hạn tối đa không quá 25% tổng vốn cho 1 mã.
  3. **Cơ chế Chặn lãi động (Trailing Stop-loss)**:
     Khi giá tạo đỉnh mới trong phiên, mốc dừng lỗ được tự động nâng lên theo công thức $\text{SL mới} = \text{Đỉnh mới} - 2 \times \text{ATR}$.
  4. **Cơ chế Chốt lời từng phần (Scaling Out TP1)**:
     Khi giá chạm mốc Take Profit, hệ thống tự động bán 50% khối lượng để hiện thực hóa lợi nhuận. 50% khối lượng còn lại được nâng mốc SL về đúng giá vốn (Break-even hòa vốn) và bật Trailing Stop để gồng lãi tối đa.

---

### 3.14. Bộ Soạn Báo Cáo & Pipeline Lọc Đa Tầng ([src/notifier.py](file:///d:/DuAn/dau_tu/src/notifier.py))
* **Mục đích**: Tổng hợp dữ liệu phân tích thành bản tin Telegram Markdown hoàn chỉnh và xuất bản nút tương tác 1-Click Buy.
* **Pipeline lọc tín hiệu đa tầng trước khi xuất bản**:
  ```
  [Tín hiệu Kỹ thuật Gốc: BUY / STRONG BUY]
                   │
                   ▼
  [1. Market Breadth Gate (VN30 vs EMA20)] ──▶ Nếu < 40% ──▶ CHẶN TOÀN BỘ MUA MỚI (Về NEUTRAL)
                   │ (Nếu Đạt)
                   ▼
  [2. Weekly Trend 1W Filter] ──────────────▶ Nếu EMA10w < EMA30w ──▶ Phạt Score -1.5đ
                   │
                   ▼
  [3. Sector Strength Filter] ──────────────▶ Nếu Ngành < 50% Uptrend ──▶ Phạt Score -0.5đ
                   │
                   ▼
  [4. Volume Confirmation] ─────────────────▶ Xác nhận Volume ≥ 1.5x SMA20
                   │
                   ▼
  [5. Tính Mức Độ Tin Cậy (Confidence)] ────▶ Đạt 3/3: CAO 🟢 | 2/3: TRUNG BÌNH 🟡 | <2: THẤP 🔴
  ```
* **Nút bấm tương tác nhanh (Inline Keyboard)**:
  Đính kèm nút `[💼 Xác nhận Mua & Giám sát [Mã]]` (Callback data: `buy_{sym}_{price}`) dưới mỗi thẻ tín hiệu Mua đạt chuẩn. Khi người dùng bấm từ điện thoại, server tự động thêm vào ví ảo và kích hoạt giám sát real-time.

---

### 3.15. Daemon Giám Sát Thời Gian Thực ([src/realtime_monitor.py](file:///d:/DuAn/dau_tu/src/realtime_monitor.py))
* **Mục đích**: Tiến trình nền chạy liên tục kiểm tra giá, hỗ trợ kỹ thuật và tin tức bất lợi trong phiên.
* **Quy trình hoạt động**:
  - **Khung giờ giám sát**: Kiểm tra `is_market_hours()` (Thứ 2 - Thứ 6: 09:00 - 11:30 & 13:00 - 14:45). Ngoài giờ giao dịch hoặc cuối tuần, hệ thống tự động nghỉ 15 phút (`sleep 900s`).
  - **Chu kỳ quét trong phiên**: Cứ mỗi 2 phút (`sleep 120s`), lấy bảng giá real-time từ `Market().equity(sym).quote()`.
  - **Chuẩn hóa giá (`_normalize_price`)**: Tự động chuyển đổi đơn vị giá vnstock v4 (VNĐ nguyên bản $> 10,000$) về đơn vị nghìn VNĐ chuẩn.
  - **Cảnh báo vi phạm**:
    1. *Chạm Cắt Lỗ Cứng*: Giá $\le \text{Stop Loss} \rightarrow$ Gửi cảnh báo khẩn cấp.
    2. *Thủng Hỗ Trợ Kỹ Thuật*: Giá $< \text{Support Level} \rightarrow$ Cảnh báo hạ 50% tỷ trọng.
    3. *Suy Yếu Kỹ Thuật Sớm*: Tín hiệu đảo chiều `SELL` / `STRONG SELL` trên vị thế đang giữ $\rightarrow$ Cảnh báo bán sớm.
  - **Khớp lệnh tự động**: Gọi `check_and_execute_auto_orders(current_prices)` tự động chốt lệnh trên ví ảo.
  - **Giám sát tin tức tiêu cực**: Quét tin tức mới liên quan đến các mã đang theo dõi, gọi AI chấm điểm. Nếu sắc thái $\le -0.6$, gửi cảnh báo khẩn cấp lên Telegram kèm link bài viết.
  - **Chống Spam**: Hàm `_is_alert_sent_today()` và `_sent_alerts_lock` đảm bảo mỗi loại cảnh báo của từng mã chỉ gửi tối đa 1 lần/ngày.

---

### 3.16. Bộ Lập Lịch Tự Động ([src/scheduler.py](file:///d:/DuAn/dau_tu/src/scheduler.py))
* **Mục đích**: Thực thi các tác vụ định kỳ tự động bằng `APScheduler` (`BackgroundScheduler`) theo múi giờ Việt Nam (`Asia/Ho_Chi_Minh` / UTC+7).
* **Lịch trình 3 mốc thời gian cố định (Thứ 2 - Thứ 6)**:
  1. **08:30 sáng** (`_send_morning_report`): Quét tin tức đầu ngày, phân tích tâm lý thị trường vĩ mô và gửi báo cáo định hướng trước giờ mở cửa.
  2. **14:45 chiều** (`_send_intraday_scan`): Quét tín hiệu kỹ thuật toàn diện ngay sau khi đóng phiên ATC, gửi bản tin tín hiệu Mua/Bán và các nút 1-Click Buy.
  3. **16:30 chiều** (`_send_eod_report`): Báo cáo tổng kết ngày, thống kê số dư ví ảo, các vị thế đang nắm giữ và tổng kết PnL của các lệnh đã đóng trong ngày.

---

### 3.17. Quản Trị Tương Tác Telegram Bot ([src/telegram_bot.py](file:///d:/DuAn/dau_tu/src/telegram_bot.py))
* **Mục đích**: Lắng nghe và xử lý mọi yêu cầu người dùng gửi qua Telegram thông qua vòng lặp Long Polling `getUpdates`.
* **Hệ thống điều khiển người dùng**:
  * **Persistent Reply Keyboard Menu** (Bàn phím cố định):
    - `[🔮 Xem dự báo]` `[💰 Xem số dư]`
    - `[📜 Lịch sử lệnh]` `[📋 Danh mục]`
    - `[📊 Phân tích mã]` `[❓ Trợ giúp]`
  * **Slash Commands**:
    - `/menu` hoặc `/start`: Kích hoạt bàn phím tương tác nhanh.
    - `/forecast`: Kích hoạt quét tín hiệu toàn diện tức thì (có `_forecast_lock` chống spam đồng thời).
    - `/balance`: Truy vấn số dư tiền mặt, định giá danh mục theo giá live thị trường và tính lãi/lỗ chưa thực hiện.
    - `/history`: Xem 10 giao dịch đã đóng gần nhất kèm tỷ lệ PnL và lý do bán.
    - `/watchlist`: Xem bảng giá trực tiếp của danh sách theo dõi mặc định.
    - `/detail <MÃ>` (Ví dụ: `/detail FPT`): Xem phân tích kỹ thuật chi tiết của mã, xuất ảnh biểu đồ candlestick và kèm nút phân tích CANSLIM / Mua ảo.
    - `/help`: Xem tài liệu hướng dẫn sử dụng bot.
  * **Xử lý Inline Callbacks**:
    - `buy_{symbol}_{price}`: Nhận lệnh xác nhận mua 1-click từ tin nhắn báo cáo.
    - `detail_{symbol}`: Phân tích kỹ thuật chi tiết mã.
    - `canslim_{symbol}`: Phân tích 6 tiêu chuẩn CANSLIM và chấm điểm 100 điểm.
  * **Xác thực Chat ID**: Tự động từ chối và cảnh báo nếu có tương tác từ Chat ID lạ không khớp với `TELEGRAM_CHAT_ID` trong cấu hình.

---

## 4. QUY TRÌNH VẬN HÀNH & SƠ ĐỒ LUỒNG THỰC THI (EXECUTION FLOWS)

### 4.1. Luồng Khởi Động Hệ Thống (Startup Flow)

```mermaid
sequenceDiagram
    autonumber
    actor User as Quản trị viên / Docker
    participant Main as main.py (Main Thread)
    participant Logger as src.logger
    participant DB as src.database (PostgreSQL/JSON)
    participant Bot as src.telegram_bot (Thread)
    participant Sched as src.scheduler (APScheduler)
    participant Monitor as src.realtime_monitor (Loop)

    User->>Main: Khởi chạy python main.py
    Main->>Logger: setup_logging() (UTF-8, Rotation)
    Main->>DB: init_db() (Khởi tạo Connection Pool & Tables)
    Main->>Bot: Start telegram_polling_loop() [Daemon Thread]
    Bot->>Bot: Đăng ký setMyCommands với Telegram API
    Main->>Sched: start_scheduler() (Lên lịch 08:30, 14:45, 16:30)
    Main->>Monitor: run_portfolio_monitor() [Blocking Loop]
    Note over Monitor: Kiểm tra giờ giao dịch & quét giá mỗi 2 phút
```

### 4.2. Luồng Quét Tín Hiệu & Tạo Nút 1-Click Buy (Daily EOD Scan Flow)

```mermaid
sequenceDiagram
    autonumber
    participant Sched as Scheduler (14:45) / User /forecast
    participant Notifier as src.notifier
    participant Fetcher as src.data_fetcher (vnstock)
    participant Ind as src.indicators
    participant Filter as Multi-stage Pipeline
    participant AI as src.llm_analyzer (Groq LLaMA)
    participant TG as Telegram User

    Sched->>Notifier: Kích hoạt send_daily_report_to_telegram()
    Notifier->>Fetcher: Tải OHLCV VN30 Index (Kiểm tra Breadth)
    Notifier->>Fetcher: Tải OHLCV danh sách DEFAULT_WATCHLIST
    Notifier->>Ind: calculate_indicators() & check_swing_signals()
    Notifier->>Filter: Chạy Pipeline: Breadth Gate -> Weekly 1W -> Sector Strength -> Volume
    Filter->>Notifier: Trả về danh sách BUY đã lọc & xếp hạng Confidence (CAO/TB/THẤP)
    Notifier->>AI: analyze_stock_with_ai(Mã tốt nhất ngày + CANSLIM + News)
    Notifier->>TG: Gửi BẢN TIN TỔNG QUAN (Markdown)
    loop Với từng mã BUY
        Notifier->>TG: Gửi Thẻ Tín Hiệu Riêng + Nút [💼 Xác nhận Mua & Giám sát {Mã}]
    end
```

### 4.3. Luồng Giám Sát Real-time & Chốt Lệnh Động Trong Phiên

```mermaid
sequenceDiagram
    autonumber
    participant Monitor as src.realtime_monitor
    participant Fetcher as vnstock Market Quote
    participant Paper as src.paper_trader
    participant AI as Groq News Sentiment
    participant TG as Telegram Bot

    Note over Monitor: Trong giờ giao dịch (Mỗi 2 phút)
    Monitor->>Fetcher: Lấy giá khớp hiện tại (Current Price)
    Monitor->>Paper: check_and_execute_auto_orders(current_prices)
    
    alt Giá chạm Stop Loss
        Paper->>Paper: sell_stock(100% vị thế, reason="CẮT LỖ")
        Paper->>TG: 🚨 Cảnh báo đã tự động BÁN Cắt Lỗ
    else Giá chạm Take Profit (Lần đầu)
        Paper->>Paper: sell_stock(50% vị thế, reason="CHỐT LỜI TP1")
        Paper->>Paper: Nâng SL của 50% còn lại về Giá Vốn (Break-even)
        Paper->>TG: 🚀 Cảnh báo Bán 50% chốt lời & Dời SL về hòa vốn
    else Giá tạo Đỉnh Mới trong phiên
        Paper->>Paper: Nâng Trailing Stop = Đỉnh Mới - 2*ATR
        Paper->>TG: 🔄 Cảnh báo nâng Trailing Stop-loss
    end

    Monitor->>Fetcher: Quét tin tức mới của các mã nắm giữ
    opt Có tin tức mới
        Monitor->>AI: analyze_news_sentiment_realtime(Tiêu đề)
        alt Score <= -0.6 (Tin cực xấu)
            Monitor->>TG: 🚨 CẢNH BÁO TIN XẤU KHẨN CẤP (Khuyên bán sớm)
        end
    end
```

---

## 5. THAM SỐ CẤU HÌNH & BIẾN MÔI TRƯỜNG

### 5.1. File Cấu Hình Tĩnh ([config.py](file:///d:/DuAn/dau_tu/config.py))
```python
# Danh sách mã cổ phiếu theo dõi mặc định (Các mã thanh khoản lớn VN30)
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

# Tham số kỹ thuật mặc định cho chiến lược lướt sóng
INDICATOR_PARAMS = {
    "RSI": {"period": 14, "oversold": 30, "overbought": 70},
    "MACD": {"fast": 12, "slow": 26, "signal": 9},
    "BOLLINGER_BANDS": {"period": 20, "std_dev": 2},
    "EMA_SHORT": 20,
    "EMA_LONG": 50,
    "ATR_PERIOD": 14
}

# Cấu hình AI LLM
GEMINI_CONFIG = {
    "model_name": "llama-3.3-70b-versatile",
    "temperature": 0.1,
    "top_p": 0.9,
    "top_k": 40
}

# Danh mục cổ phiếu thực tế ngoài đời để nhận cảnh báo cắt lỗ khẩn cấp
MY_PORTFOLIO = []
```

### 5.2. Biến Môi Trường ([.env](file:///d:/DuAn/dau_tu/.env))
```env
# API Key của Groq AI (Dùng cho trợ lý phân tích LLaMA 3.3 70B)
GROQ_API_KEY=gsk_your_groq_api_key_here

# Token Telegram Bot tạo qua @BotFather
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Chat ID cá nhân lấy qua @userinfobot (Chống nhận lệnh từ người lạ)
TELEGRAM_CHAT_ID=6354225724

# URL kết nối cơ sở dữ liệu PostgreSQL (Supabase / Neon / Render)
DATABASE_URL=postgresql://postgres:password@db.supabase.co:5432/postgres

# (Tùy chọn) API Key của vnstock để tăng hạn mức lên 60 req/phút
VNSTOCK_API_KEY=your_vnstock_api_key_here
```

---

## 6. HẠ TẦNG TRIỂN KHAI, CONTAINER HÓA & CI/CD

### 6.1. Dockerfile Đa Tầng Tối Ưu Tốc Độ ([Dockerfile](file:///d:/DuAn/dau_tu/Dockerfile))
Hệ thống sử dụng base image `python:3.11-slim` kết hợp trình cài đặt gói siêu tốc `uv`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Cài đặt build tools tối thiểu cho psycopg2 và các thư viện C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt uv để tăng tốc cài package gấp 10-50 lần pip
RUN pip install --no-cache-dir uv

# Copy requirements và cài đặt
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Thiết lập UTF-8 và Timezone Việt Nam
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Ho_Chi_Minh

# Healthcheck định kỳ 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

# Khởi chạy hệ thống
CMD ["python", "main.py"]
```

### 6.2. Docker Compose Production ([docker-compose.yml](file:///d:/DuAn/dau_tu/docker-compose.yml))
```yaml
services:
  wavetrader:
    build:
      context: .
      dockerfile: Dockerfile
    image: vn-wavetrader:latest
    container_name: wavetrader_prod
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          cpus: '0.75'
          memory: 512M
        reservations:
          memory: 128M
    environment:
      - TZ=Asia/Ho_Chi_Minh
```

### 6.3. Triển Khai Dưới Dạng Linux Systemd Service
Để chạy ngầm trực tiếp trên máy chủ Ubuntu/Debian mà không dùng Docker:
1. Tạo file service `/etc/systemd/system/wavetrader.service`:
   ```ini
   [Unit]
   Description=VN-WaveTrader Automated Headless Trading Service
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/dau_tu
   Environment="PYTHONIOENCODING=utf-8"
   Environment="PYTHONUNBUFFERED=1"
   EnvironmentFile=/home/ubuntu/dau_tu/.env
   ExecStart=/home/ubuntu/dau_tu/venv/bin/python main.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
2. Kích hoạt dịch vụ:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable wavetrader
   sudo systemctl start wavetrader
   sudo systemctl status wavetrader
   ```

---

## 7. BẢO MẬT, ĐỘ TIN CẬY & XỬ LÝ LỖI (RELIABILITY & FAULT TOLERANCE)

1. **Xử lý triệt để mã hóa Unicode trên Windows**:
   - Tự động cấu hình `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` trong `logger.py`.
   - File log lưu trữ định dạng UTF-8 với Rotation tránh tràn ổ đĩa.
2. **Chống Rate Limit 429 và Treo Socket**:
   - Token Bucket Rate Limiter giới hạn nghiêm ngặt tần suất gọi `vnstock` ($\le 15$ req/phút) và `groq` ($\le 20$ req/phút).
   - Thiết lập `socket.setdefaulttimeout(30)` và Thread Watchdog (timeout 25s) cho mọi lệnh I/O mạng.
3. **Thread Safety & Race Conditions**:
   - Toàn bộ thao tác I/O trên danh mục ảo và cơ sở dữ liệu đều được bảo vệ bằng `threading.Lock()` (`_portfolio_lock`, `_sent_alerts_lock`, `_forecast_lock`).
   - PostgreSQL sử dụng `ThreadedConnectionPool` chuyên dụng cho môi trường đa luồng.
4. **Bảo mật và Phân quyền Telegram**:
   - Hệ thống so khớp `chat_id` của mọi tin nhắn và callback gửi đến với `TELEGRAM_CHAT_ID` trong cấu hình, từ chối mọi yêu cầu từ người dùng lạ.
5. **Kiểm thử tự động (Test Suite)**:
   - File `test_monitor.py` kiểm thử 11 kịch bản đơn vị (Indicators, Swing Signals, Cache, Support/Resistance, Chart Generator, Scheduler Lifecycle, Confidence Calculation, Status Recalculation) thông qua `pytest`.
   - CI Pipeline tự động chạy qua GitHub Actions trên mỗi commit.

---

## 8. LỘ TRÌNH PHÁT TRIỂN TIẾP THEO (FUTURE ROADMAP)

1. **Telegram Webhook Mode**: Nâng cấp từ Long Polling sang Webhook thông qua FastAPI / Cloudflare Tunnel để giảm tải độ trễ và tiết kiệm băng thông mạng.
2. **Tích hợp API Đặt Lệnh Trực Tiếp (Direct Broker Order Execution)**: Tích hợp với Open API của các công ty chứng khoán (VPS, SSI, VNDirect) để tự động hóa đặt lệnh thật khi người dùng xác nhận Mua/Bán qua Telegram.
3. **Mô hình Machine Learning Candlestick Pattern**: Huấn luyện mô hình LightGBM / XGBoost kết hợp chuỗi dữ liệu nến OHLCV để dự báo xác suất thắng ngắn hạn $T+3$.
4. **Mở rộng Đa Khung Thời Gian (Multi-Timeframe Engine)**: Kết hợp tín hiệu khung 1 giờ (1H) để tìm điểm vào lệnh (Entry Point) tối ưu hơn trong phiên.
