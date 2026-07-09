FROM python:3.10-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Cài đặt các công cụ biên dịch tối thiểu cần thiết (cho một số thư viện tính toán)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements.txt trước để tận dụng cache của Docker
COPY requirements.txt .

# Cài đặt các thư viện Python
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn vào container
COPY . .

# Thiết lập mã hóa tiếng Việt mặc định cho output terminal
ENV PYTHONIOENCODING=utf-8

# Khởi chạy mặc định tiến trình giám sát và Telegram Bot
CMD ["python", "monitor_portfolio.py"]
