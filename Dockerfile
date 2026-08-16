FROM python:3.11-slim

WORKDIR /app

# Cài đặt các công cụ biên dịch tối thiểu cần thiết
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt uv trực tiếp qua PyPI (chỉ 1 giây, tránh phụ thuộc ghcr.io)
RUN pip install --no-cache-dir uv

# Copy file requirements.txt trước để tận dụng cache của Docker
COPY requirements.txt .

# Cài đặt các thư viện Python bằng uv (siêu tốc, tiết kiệm RAM)
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
