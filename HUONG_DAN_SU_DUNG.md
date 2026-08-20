# HƯỚNG DẪN SỬ DỤNG & KIỂM THỬ VN-WAVETRADER TỪ A-Z (HEADLESS & TELEGRAM ONLY)

Chào mừng bạn đến với **VN-WaveTrader** - hệ thống hỗ trợ đầu tư lướt sóng (swing trading) ngắn hạn tự động hóa hoàn toàn 100% qua **Telegram** cho thị trường chứng khoán Việt Nam. Hệ thống hoạt động ở chế độ không giao diện (Headless) giúp tối ưu hóa 100% tài nguyên server và tiết kiệm chi phí đám mây.

---

## PHẦN 1: CẤU TRÚC HỆ THỐNG & FILE NGUỒN

Thư mục dự án sau khi tối giản hóa giao diện:

```
dau_tu/
│
├── .env                     # File cấu hình API Keys (Không chia sẻ cho người khác)
├── config.py                # Cấu hình danh mục theo dõi & tham số kỹ thuật
├── requirements.txt         # Khai báo các thư viện Python phụ thuộc
│
├── src/
│   ├── data_fetcher.py      # Tải dữ liệu lịch sử, khớp lệnh trong phiên & tin tức
│   ├── indicators.py        # Tính toán chỉ báo cốt lõi, SuperTrend, Hỗ trợ/Kháng cự
│   ├── portfolio.py         # Chạy thuật toán tối ưu hóa tỷ trọng vốn (PyPortfolioOpt)
│   ├── llm_analyzer.py      # Giao tiếp với AI Gemini phân tích kỹ thuật & tin tức
│   ├── notifier.py          # Soạn báo cáo và gửi về Telegram Bot
│   └── paper_trader.py      # Quản lý ví ảo, lệnh mua/bán và chặn lãi động Kelly
│
├── run_daily.py             # Script tự động quét EOD và gửi Telegram hàng ngày
├── monitor_portfolio.py     # Tiến trình nền 24/7 đón nhận Bot tương tác và giám sát
├── test_vnstock.py          # Script kiểm thử tích hợp nhanh
└── virtual_portfolio.json   # Lưu trữ danh mục ví ảo hiện tại
```

---

## PHẦN 2: HƯỚNG DẪN CẤU HÌNH BAN ĐẦU (SETUP)

### 1. Đăng ký API Key Vnstock (Tăng giới hạn lên 60 req/phút)
*   **Bước 1**: Truy cập **[vnstocks.com](https://vnstocks.com)** và đăng ký tài khoản miễn phí.
*   **Bước 2**: Nhấp vào ảnh đại diện, chọn **Tài khoản** để sao chép **API Key**.
*   **Bước 3**: Mở terminal Git Bash và chạy lệnh cấu hình:
    ```bash
    ./venv/Scripts/python -m vnstock_installer
    ```
    Nhập số `1` và dán API Key vào để lưu lại cấu hình.

### 2. Thiết lập các khóa bảo mật trong file `.env`
Mở file `.env` và điền các tham số:
```env
# API Key của Gemini AI (để kích hoạt Trợ lý ảo nhận định)
GEMINI_API_KEY=your_gemini_api_key_here

# Token của Telegram Bot tự tạo qua @BotFather
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# ID Chat của bạn lấy qua @userinfobot
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

---

## PHẦN 3: KIỂM THỬ TỰ ĐỘNG & XÁC MINH (TESTING)

Trước khi khởi chạy trên server, bạn cần kiểm tra độ thông suốt của dữ liệu và API:
```bash
$env:PYTHONIOENCODING='utf-8'; ./venv/Scripts/python test_vnstock.py
```
*(Trên Linux/Git Bash chỉ cần chạy: `PYTHONIOENCODING=utf-8 ./venv/Scripts/python test_vnstock.py`)*

Màn hình hiển thị 6 bước kiểm tra thành công:
*   **Bước 1 (VN30 list)**: Trả về danh sách mã thuộc rổ VN30.
*   **Bước 2 (Tin tức)**: Tải thành công tin tức lịch sử của mã FPT.
*   **Bước 3 (Dòng tiền khớp lệnh)**: Thống kê thành công lượng mua/bán chủ động và lệnh lớn cá mập.
*   **Bước 4 (Chỉ báo & SuperTrend)**: Đã tính toán các cột `rsi`, `macd`, `supertrend`.
*   **Bước 5 (Hỗ trợ/Kháng cự)**: Xác định rõ mốc giá hỗ trợ sàn và kháng cự trần.
*   **Bước 6 (Quét tín hiệu)**: Đưa ra trạng thái đề xuất (BUY/SELL) và danh sách lý do kỹ thuật.

---

## PHẦN 4: HƯỚNG DẪN VẬN HÀNH 100% QUA TELEGRAM BOT

Hệ thống được thiết kế vận hành hoàn toàn tự động 2 chiều thông qua Chatbot Telegram của bạn.

### 1. Nhận báo cáo quét tín hiệu và phân tích sâu AI cuối ngày (EOD)
Vào cuối ngày giao dịch (sau 15:15), hệ thống sẽ quét toàn bộ danh mục theo dõi và gửi tin nhắn:
```bash
./venv/Scripts/python run_daily.py
```
*(Bạn có thể đưa lệnh này vào Cron Job trên Linux hoặc Windows Task Scheduler để chạy tự động lúc 15:15 từ Thứ 2 - Thứ 5)*

**Nội dung bản tin bạn nhận được trên điện thoại:**
1.  **📊 Độ rộng thị trường VN30**: Tỷ lệ mã nằm trên EMA20. Nếu dưới 40%, hệ thống tự động kích hoạt trạng thái phòng vệ, vô hiệu hóa các nút Mua mới để tránh sụt giảm chung vĩ mô.
2.  **🟢 Các mã tiềm năng MUA**: Tín hiệu bùng nổ kỹ thuật thỏa mãn bộ lọc volume lớn gấp 1.5 lần trung bình và khung tuần 1W không Downtrend.
3.  **⚠️ Các mã cảnh báo BÁN**: Các mã suy yếu kỹ thuật hoặc vi phạm đường SuperTrend ngắn hạn.
4.  **🤖 Nhận định chuyên sâu AI**: Gemini phân tích toàn diện tin tức nóng và biểu đồ của mã tốt nhất ngày.

### 2. Kích hoạt Giám sát Vị thế bằng 1-Click
Dưới mỗi thẻ tín hiệu Mua gửi về Telegram, hệ thống sẽ đính kèm nút:
👉 **`💼 Xác nhận Mua & Giám sát [Mã]`**
*   **Mức đi vốn tối ưu Kelly**: Thẻ tin nhắn sẽ gợi ý % vốn cụ thể nên phân bổ cho lệnh này dựa trên xác suất thắng lịch sử.
*   **Thao tác**: Sau khi bạn tự đặt lệnh thực tế trên app của CTCK, bạn chỉ cần bấm nút này trên Telegram.
*   **Hoạt động ngầm**: Server nhận tín hiệu, tự động thêm cổ phiếu vào ví ảo, tính toán mốc **SL/TP động theo ATR** (SL = Mua - 2*ATR, TP = Mua + 4*ATR) và bắt đầu theo dõi thời gian thực.

### 3. Vận hành Giám sát Real-time & Chặn lãi động
Tiến trình giám sát nền sẽ chạy liên tục trong phiên giao dịch:
```bash
./venv/Scripts/python monitor_portfolio.py
```
*   **Tần suất quét**: 2 phút/lần gọi API cập nhật giá. Tự nghỉ ngoài giờ giao dịch và ngày cuối tuần để tiết kiệm dung lượng.
*   **🔄 Chốt chặn lãi động (Trailing Stop)**: Khi giá cổ phiếu tăng tạo đỉnh mới, hệ thống tự kéo SL lên theo đà tăng (cách đỉnh 5.0%) giúp khóa chặt lợi nhuận.
*   **🚀 Chốt lời từng phần (Scaling Out)**: Khi giá chạm TP kiến nghị, hệ thống tự động bán ảo 50% để bảo toàn lợi nhuận, đồng thời nâng SL của 50% còn lại về đúng giá vốn (Break-even) và để chạy lãi tối đa bằng Trailing Stop.
*   **📊 Tối ưu tỷ lệ Lãi/Lỗ động (Dynamic R:R)**: Tự động điều chỉnh khoảng TP/SL (TP = 5*ATR khi Uptrend vĩ mô; hoặc TP = 3*ATR khi Sideways) dựa trên chỉ báo độ rộng thị trường.
*   **📐 Gợi ý lượng mua rủi ro 2% và Kelly**: Hệ thống hiển thị số lượng cổ phiếu chính xác cần mua trên thẻ Telegram sao cho nếu chạm SL chỉ lỗ tối đa 2% tổng tài sản.
*   **🌐 Bộ lọc đồng thuận sóng ngành (Sector Strength)**: Chặn mọi tín hiệu mua breakout cô độc khi nhóm ngành chung của cổ phiếu đó đang trong xu hướng giảm (ít hơn 50% cổ phiếu trong ngành nằm trên EMA20).
*   **🚨 Cảnh báo tin tức nóng khẩn cấp**: Nếu cào được tin tức cực xấu (lãnh đạo bị bắt, gian lận tài chính...) trên Cafef/Vietstock liên quan đến các mã đang nắm giữ, Gemini AI sẽ cảnh báo ngay qua Telegram để bạn bán sớm.
*   **Cơ chế chống spam**: Mỗi loại cảnh báo của từng mã chỉ gửi Telegram tối đa 1 lần/ngày.

---

## PHẦN 5: TRIỂN KHAI LÊN ĐÁM MÂY (DEPLOY TO CLOUD)

Hệ thống đã được tối ưu hóa sẵn sàng cho việc deploy lên máy chủ Google Cloud bằng container Docker và kết nối Database.

### 1. Cấu hình Database PostgreSQL (Ví dụ: Supabase)
Để đảm bảo danh mục ví ảo không bị mất khi container khởi động lại:
1. Tạo một project PostgreSQL miễn phí trên **[Supabase](https://supabase.com)** hoặc **[Render](https://render.com)**.
2. Sao chép chuỗi kết nối **URI Connection String** (dạng `postgresql://postgres:password@db-host:5432/postgres`).
3. Khai báo biến môi trường này vào file `.env` cục bộ hoặc cấu hình Environment Variable trên Google Cloud:
   ```env
   DATABASE_URL=postgresql://postgres:mypassword@db.supabase.co:5432/postgres
   ```
*Hệ thống tự động phát hiện Database, khởi tạo bảng dữ liệu và đồng bộ lưu trữ. Nếu không khai báo, hệ thống sẽ tự động sử dụng file JSON cục bộ.*

### 2. Triển khai bằng Docker
Xây dựng và chạy Docker container trên server của bạn:
1. **Build Docker Image**:
   ```bash
   docker build -t vn-wavetrader .
   ```
2. **Chạy Container**:
   ```bash
   docker run -d --name wavetrader-monitor --env-file .env vn-wavetrader
   ```

---

## PHẦN 6: XỬ LÝ LỖI THƯỜNG GẶP (TROUBLESHOOTING)

| Lỗi | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| **ModuleNotFoundError** | Chưa chạy Python trong môi trường ảo | Chạy lệnh bằng cách thêm tiền tố `./venv/Scripts/python` trước file chạy. |
| **Rate Limit Exceeded** | Quét quá nhiều mã vượt quá giới hạn 20 request/phút | Đợi 10 giây rồi thử lại, hoặc cấu hình API Key chính thức của vnstock qua `python -m vnstock_installer`. |
| **UnicodeEncodeError** | Terminal CMD Windows không hỗ trợ font tiếng Việt | Dùng Git Bash để chạy lệnh, hoặc thêm tiền tố thiết lập mã hóa đầu ra: `$env:PYTHONIOENCODING='utf-8'`. |
| **Chạm hạn mức Gemini 429** | Tài khoản Gemini miễn phí bị quá tải số lượng câu hỏi/phút | Hệ thống đã tích hợp sẵn cơ chế thử lại (exponential backoff). Tiến trình sẽ tự động chờ từ 6-24 giây để gửi lại yêu cầu một cách an toàn mà không sập app. |
