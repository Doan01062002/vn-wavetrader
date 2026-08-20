# 🌊 VN-WaveTrader

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/Architecture-Headless%20Daemon-purple?style=for-the-badge&logo=docker&logoColor=white" alt="Architecture" />
  <img src="https://img.shields.io/badge/Interface-Telegram%20Bot%202--Way-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" />
  <img src="https://img.shields.io/badge/AI%20Engine-Groq%20LLaMA%203.3%2070B-orange?style=for-the-badge&logo=groq&logoColor=white" alt="Groq AI" />
  <img src="https://img.shields.io/badge/Database-PostgreSQL%20%2F%20Supabase-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Market-Vietnam%20(HOSE%20%2F%20VN30)-red?style=for-the-badge" alt="Vietnam Stock Market" />
</p>

---

## 📖 Giới thiệu (Overview)

**VN-WaveTrader** là hệ thống giao dịch thuật toán (Algorithmic Trading) và cố vấn đầu tư lướt sóng (Swing Trading) ngắn hạn tự động hóa hoàn toàn cho **Thị trường Chứng khoán Việt Nam** (HOSE, HNX, UPCoM — trọng tâm rổ VN30 và cổ phiếu thanh khoản cao).

Hệ thống được thiết kế theo kiến trúc **100% Headless Daemon Service** (không giao diện web cồng kềnh), tương tác và điều khiển 2 chiều độc quyền qua ứng dụng tin nhắn **Telegram (Bot Commands, Persistent Reply Keyboard & Inline Callback Buttons)**. Mô hình này giúp tối ưu hóa tài nguyên phần cứng (chỉ cần 256MB - 512MB RAM), đảm bảo tốc độ phản hồi tức thì và khả năng vận hành liên tục 24/7 trên Docker hoặc VPS đám mây giá rẻ.

---

## 🏛️ Sơ đồ kiến trúc hệ thống (Architecture)

```text
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 VN-WAVETRADER SYSTEM ARCHITECTURE                       │
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

---

## 🚀 Tính năng nổi bật (Key Features)

### 1. 🔍 Bộ lọc tín hiệu kỹ thuật đa tầng (Multi-Stage Technical Filtering)
- **10+ Chỉ báo kết hợp**: RSI(14), MACD(12,26,9), Bollinger Bands, Stochastic Oscillator (%K, %D), ATR(14), ADX (lọc giai đoạn thị trường đi ngang Sideway), SuperTrend và EMA 20/50.
- **Xác định Hỗ trợ / Kháng cự tự động**: Sử dụng thuật toán cực trị hình học `scipy.signal.argrelextrema` trên chuỗi giá 60 phiên.
- **Xác nhận dòng tiền bùng nổ**: Khối lượng khớp lệnh vượt tối thiểu **1.5x** đường trung bình SMA20 Volume.
- **Hệ thống lọc xu hướng mẹ (Hard Gates)**:
  - **Market Breadth Filter**: Tỷ lệ cổ phiếu VN30 nằm trên EMA20. Nếu < 40%, hệ thống tự động khóa tín hiệu mua để phòng vệ thị trường chung.
  - **Sector Strength Filter**: Đo lường sức mạnh 7 nhóm ngành trọng điểm (Ngân hàng, Thép, Chứng khoán, Bất động sản, Bán lẻ, Công nghệ, Tiêu dùng).
  - **Weekly Trend Filter**: Xác thực xu hướng trên nến tuần 1W (EMA10w vs EMA30w).

### 2. 📊 Chấm điểm cơ bản CANSLIM / Minervini (100 điểm)
- Bóc tách tự động BCTC Quý và Năm của doanh nghiệp:
  - **C (Current Quarterly Earnings)**: Tăng trưởng LNST quý gần nhất YoY $\ge 20\%$.
  - **A (Annual Earnings Growth)**: Tăng trưởng lợi nhuận hàng năm & ROE $\ge 15\%$.
  - **N (New Highs / Catalyst)**: Khoảng cách đỉnh 52 tuần $\le 15\%$.
  - **S (Supply & Demand)**: Đột biến thanh khoản và dòng tiền tích lũy.
  - **L (Leader vs Laggard)**: Sức mạnh giá tương đối RS 60 phiên so với VN-Index.
  - **I (Institutional Sponsorship)**: Khối ngoại mua ròng và độ biến động Beta hợp lý.

### 3. 🤖 Phân tích AI & Sắc thái tin tức (Groq AI & Sentiment Analysis)
- Tích hợp **Groq API SDK** với mô hình ngôn ngữ lớn **LLaMA 3.3 70B Versatile** và **LLaMA 3.1 8B Instant**.
- **Cào và phân tích tin tức tự động** từ RSS VnExpress Kinh Doanh và Cafef.
- **Đo lường chỉ số Tâm lý thị trường (Fear & Greed Index)** theo thang điểm -1.0 đến +1.0.
- **Cảnh báo khẩn cấp tin tức tiêu cực (Negative News Emergency Alert)** khi phát hiện tin xấu ảnh hưởng đến cổ phiếu trong danh mục nắm giữ.

### 4. 💼 Quản trị danh mục & Giao dịch ví ảo (Paper Trading & Dynamic Risk Control)
- Khởi tạo ví ảo mặc định **100.000.000 VNĐ**, tự động định giá tài sản ròng (NAV / Net Worth) theo thời gian thực.
- **Định cỡ vị thế khoa học**:
  - **Half-Kelly Criterion**: Tối ưu hóa tỷ trọng phân bổ vốn (tối đa 25%/mã).
  - **Fixed 2% Risk Sizing**: Khống chế mức lỗ tối đa trên mỗi giao dịch ở 2% tổng tài sản.
- **Quản trị lệnh động theo ATR**:
  - Stop Loss khởi tạo: $\text{Giá mua} - 2 \times \text{ATR}$.
  - Take Profit 1: $\text{Giá mua} + 2 \times \text{ATR}$, Take Profit 2: $\text{Giá mua} + 4 \times \text{ATR}$.
  - **Trailing Stop-loss**: Kéo nâng mốc chặn lãi khi giá thiết lập đỉnh mới.
  - **Chốt lời từng phần (Scaling Out)**: Bán 50% vị thế khi chạm TP1 và dời điểm Stop Loss của 50% còn lại về giá hòa vốn (Break-even).

### 5. 📱 Tương tác 2 chiều 100% qua Telegram Bot
- **Nút bấm 1-Click Buy & Giám sát**: Xác nhận mở vị thế ngay trên tin nhắn tín hiệu Telegram.
- **Bàn phím tương tác nhanh (Persistent Reply Keyboard)**:
  - 📊 `Danh mục` — Xem trạng thái nắm giữ, PnL, mốc SL/TP hiện tại.
  - 🔍 `Quét tín hiệu` — Kích hoạt quét toàn diện thị trường ngay lập tức.
  - 📈 `Độ rộng TT` — Xem tỷ lệ mã trên EMA20 và sức mạnh sóng ngành.
  - 🤖 `Nhận định AI` — Yêu cầu AI tổng hợp chiến lược phiên.
  - 💰 `Ví ảo` — Tra cứu số dư tiền mặt, NAV và lịch sử giao dịch.
  - 📰 `Tin tức` — Đọc tổng hợp tin tức nóng và chỉ số cảm xúc thị trường.
  - ⚙️ `Cài đặt` / ❓ `Trợ giúp`.
- **Tự động gửi biểu đồ kỹ thuật Dark Theme (sendPhoto)** với nến Candlestick, EMA20/50, RSI, MACD và Volume.

### 6. ⏰ Lập lịch tự động 24/7 (APScheduler)
- **08:30 (Sáng)**: Bản tin tâm lý thị trường & Điểm tin vĩ mô đầu ngày.
- **14:45 (Chiều)**: Bản tin quét tín hiệu bùng nổ cuối phiên (Intraday Scanner).
- **16:30 (Cuối ngày)**: Báo cáo tổng kết danh mục, cập nhật PnL và nhận định chiến lược AI.
- **Quét 2 phút/lần trong giờ giao dịch**: Giám sát vi phạm SL/TP hoặc cảnh báo tin tức khẩn cấp.

---

## 📁 Cấu trúc thư mục (Directory Structure)

```text
dau_tu/
├── .env.example                # File mẫu cấu hình biến môi trường
├── config.py                   # Cấu hình danh mục theo dõi & tham số kỹ thuật
├── requirements.txt            # Danh sách thư viện Python phụ thuộc
├── Dockerfile                  # Docker container build script (Python 3.11-slim)
├── docker-compose.yml          # Cấu hình triển khai Docker Compose
├── main.py                     # Entrypoint khởi chạy toàn bộ hệ thống
├── test_monitor.py             # Script kiểm thử hệ thống giám sát & Telegram
├── test_vnstock.py             # Script kiểm thử kết nối API Vnstock
│
├── src/                        # Thư mục mã nguồn chính
│   ├── __init__.py
│   ├── data_fetcher.py         # Lấy dữ liệu nến, khớp lệnh và tin tức (vnstock)
│   ├── indicators.py           # Tính toán 10+ chỉ báo kỹ thuật & Hỗ trợ/Kháng cự
│   ├── fundamental_screener.py # Lọc cổ phiếu cơ bản theo tiêu chuẩn CANSLIM / Minervini
│   ├── sentiment_analyzer.py   # Phân tích sắc thái tin tức & Fear/Greed Index
│   ├── llm_analyzer.py         # Tương tác với Groq AI (LLaMA 3.3 70B)
│   ├── chart_generator.py      # Vẽ biểu đồ kỹ thuật Dark Theme bằng Matplotlib
│   ├── portfolio.py            # Tối ưu hóa tỷ trọng danh mục (PyPortfolioOpt)
│   ├── paper_trader.py         # Quản lý ví ảo, định cỡ Kelly, SL/TP động
│   ├── realtime_monitor.py     # Daemon quét giá thời gian thực mỗi 2 phút
│   ├── scheduler.py            # Quản lý lịch phát báo cáo tự động (APScheduler)
│   ├── telegram_bot.py         # Xử lý lệnh Telegram Bot 2 chiều & Callback Query
│   ├── notifier.py             # Định dạng và gửi thông báo Telegram
│   ├── database.py             # Kết nối PostgreSQL / Supabase Connection Pool
│   ├── rate_limiter.py         # Token Bucket & Exponential Backoff cho APIs
│   ├── logger.py               # Hệ thống ghi log xoay vòng (Rotating File Handler)
│   ├── backtest.py             # Kiểm thử chiến lược lịch sử (Backtesting Engine)
│   └── parameter_tuning.py     # Tối ưu tham số chiến lược (Grid Search / Optimization)
│
├── PROJECT_SPECIFICATION.md    # Tài liệu đặc tả kỹ thuật chi tiết v2.5.0
└── HUONG_DAN_SU_DUNG.md        # Hướng dẫn sử dụng và kiểm thử từ A-Z
```

---

## 🛠️ Hướng dẫn cài đặt & Chạy hệ thống (Getting Started)

### 1. Yêu cầu môi trường (Prerequisites)
- **Python**: `>= 3.10` (Khuyến nghị `3.11`)
- **Docker & Docker Compose** (Tùy chọn nếu triển khai trên container)
- **Tài khoản & API Keys**:
  - **Telegram Bot Token**: Tạo bot qua [@BotFather](https://t.me/BotFather).
  - **Telegram Chat ID**: Lấy ID của bạn qua [@userinfobot](https://t.me/userinfobot).
  - **Groq API Key**: Đăng ký miễn phí tại [Groq Console](https://console.groq.com).
  - **Vnstock API Key**: Đăng ký miễn phí tại [Vnstock](https://vnstocks.com) (tăng giới hạn tốc độ).
  - **PostgreSQL / Supabase URL** (Tùy chọn nếu dùng cơ sở dữ liệu cloud).

---

### 2. Cài đặt cục bộ (Local Setup)

#### Bước 1: Clone kho mã nguồn
```bash
git clone https://github.com/Doan01062002/vn-wavetrader.git
cd vn-wavetrader
```

#### Bước 2: Tạo môi trường ảo & cài đặt thư viện
```bash
# Tạo virtual environment
python -m venv venv

# Kích hoạt virtual environment
# Trên Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Trên Linux/macOS:
source venv/bin/activate

# Nâng cấp pip và cài đặt dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

#### Bước 3: Cấu hình biến môi trường `.env`
Tạo file `.env` từ `.env.example`:
```bash
cp .env.example .env
```
Mở file `.env` và điền đầy đủ các thông tin:
```env
# Telegram Configuration (Bắt buộc)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# AI / LLM Configuration (Khuyến nghị Groq LLaMA 3.3)
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Database Configuration (Tùy chọn Supabase / PostgreSQL)
DATABASE_URL=postgresql://postgres:password@db.supabase.co:5432/postgres
```

#### Bước 4: Kiểm thử hệ thống trước khi chạy
```bash
# Kiểm tra kết nối dữ liệu Vnstock
python test_vnstock.py

# Kiểm tra cơ chế giám sát và gửi thông báo Telegram
python test_monitor.py
```

#### Bước 5: Khởi chạy toàn bộ hệ thống
```bash
python main.py
```

---

### 3. Triển khai bằng Docker & Docker Compose (Production Deployment)

Hệ thống đã được đóng gói sẵn Dockerfile tối ưu hóa tài nguyên:

```bash
# Xây dựng và khởi chạy container dưới nền (detached mode)
docker compose up -d --build

# Xem log hoạt động theo thời gian thực
docker compose logs -f wavetrader

# Dừng hệ thống
docker compose down
```

---

## 💬 Danh sách lệnh Telegram Bot (Bot Commands)

| Lệnh (Command) | Chức năng chi tiết |
| :--- | :--- |
| `/start` | Khởi động Bot, hiển thị menu chính và bàn phím tương tác. |
| `/scan` | Quét tức thời toàn bộ danh mục VN30 để tìm tín hiệu Mua/Bán kỹ thuật. |
| `/portfolio` | Hiển thị chi tiết ví ảo, trạng thái lãi/lỗ từng mã, mốc SL/TP hiện tại. |
| `/market` | Đánh giá độ rộng thị trường VN30 và sức mạnh 7 nhóm ngành chính. |
| `/ai` | Yêu cầu AI (LLaMA 3.3 70B) phân tích tổng quan chiến lược thị trường. |
| `/sentiment` | Xem điểm số tâm lý đám đông (Fear & Greed Index) và tin tức mới nhất. |
| `/chart <MÃ>` | Xuất biểu đồ kỹ thuật Dark Theme (Candlestick + EMA + RSI + MACD). Ví dụ: `/chart FPT`. |
| `/buy <MÃ> <GIÁ> <SL>` | Mở vị thế thủ công cho mã cổ phiếu trong ví ảo. Ví dụ: `/buy FPT 120.5 100`. |
| `/sell <MÃ>` | Đóng vị thế chốt lời / cắt lỗ cổ phiếu trong danh mục ví ảo. |
| `/history` | Xem lịch sử các giao dịch đã thực hiện và tổng kết PnL. |
| `/reset` | Đặt lại số dư ví ảo về 100.000.000 VNĐ ban đầu. |
| `/help` | Hiển thị bảng hướng dẫn sử dụng chi tiết. |

---

## ⚙️ Cấu hình kỹ thuật tùy chỉnh (`config.py`)

Bạn có thể tinh chỉnh các tham số lọc tín hiệu và quy tắc giao dịch trong file `config.py`:
- `WATCHLIST`: Danh sách các mã cổ phiếu ưu tiên theo dõi (mặc định rổ VN30 và các nhóm ngành hot).
- `TECHNICAL_PARAMS`: Các chu kỳ chỉ báo (RSI 14, MACD 12-26-9, EMA 20/50, ATR 14, Bollinger Bands 20,2).
- `RISK_MANAGEMENT`:
  - `MAX_PORTFOLIO_ALLOCATION`: Tỷ trọng vốn tối đa cho 1 cổ phiếu (mặc định 25%).
  - `FIXED_RISK_PERCENT`: Tỷ lệ rủi ro tối đa trên tổng tài sản cho mỗi lệnh (mặc định 2%).
  - `ATR_MULTIPLIER_SL`: Hệ số nhân ATR cho điểm cắt lỗ (mặc định 2.0x).
  - `ATR_MULTIPLIER_TP1` / `TP2`: Hệ số nhân ATR cho điểm chốt lời (2.0x và 4.0x).

---

## 🔒 Bản quyền & Miễn trừ trách nhiệm (Disclaimer)

- **Mục đích sử dụng**: Hệ thống **VN-WaveTrader** được phát triển nhằm mục đích nghiên cứu, học tập thuật toán giao dịch tài chính và hỗ trợ ra quyết định đầu tư cá nhân.
- **Rủi ro đầu tư**: Thị trường chứng khoán luôn tiềm ẩn rủi ro biến động giá. Mọi tín hiệu từ thuật toán và phân tích của AI mang tính chất tham khảo cố vấn. Người dùng hoàn toàn tự chịu trách nhiệm đối với các quyết định đặt lệnh và giao dịch thực tế trên tài khoản chứng khoán của mình.

---

<p align="center">
  <b>Phát triển bởi Doan01062002 | VN-WaveTrader Project © 2026</b>
</p>
