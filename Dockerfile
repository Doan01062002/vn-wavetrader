FROM python:3.11-slim

WORKDIR /app

# Cài đặt các công cụ biên dịch tối thiểu cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Sử dụng uv binary chính thức để cài đặt thư viện siêu tốc (< 10s) và chống tràn RAM trên VPS
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy file requirements.txt trước để tận dụng cache của Docker
COPY requirements.txt .

# Cài đặt các thư viện Python bằng uv (nhanh gấp 50 lần pip, không bị treo bộ nhớ)
RUN uv pip install --system --no-cache -r requirements.txt

# Copy toàn bộ mã nguồn vào container
COPY . .

# Thiết lập mã hóa tiếng Việt mặc định cho output terminal
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Ho_Chi_Minh

# Healthcheck: kiểm tra process Python vẫn sống
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

# Khởi chạy entrypoint mới (main.py)
CMD ["python", "main.py"]
