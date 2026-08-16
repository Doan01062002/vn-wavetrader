"""
Module phân tích AI sử dụng Groq SDK chính thức.

Cải tiến v2:
- Chuyển từ raw HTTP requests sang Groq SDK chính thức
- Retry tự động với exponential backoff
- Rate limiting tập trung qua groq_limiter
- Fallback graceful khi không có API key
"""
import os
import logging
import pandas as pd
from dotenv import load_dotenv

from src.rate_limiter import groq_limiter, api_retrier

logger = logging.getLogger(__name__)

# Load biến môi trường từ .env
load_dotenv()

# Groq client singleton (lazy init)
_groq_client = None


def init_gemini():
    """
    Khởi tạo Groq API Client chính thức.
    Tên hàm giữ nguyên để tương thích ngược với các module khác.
    """
    global _groq_client
    if _groq_client is not None:
        return _groq_client

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY chưa được thiết lập trong file .env")
        return None

    try:
        from groq import Groq
        _groq_client = _GroqWrapper(Groq(api_key=api_key))
        logger.info("Groq SDK client đã khởi tạo thành công.")
        return _groq_client
    except ImportError:
        logger.warning("Thư viện 'groq' chưa được cài đặt. Chạy: pip install groq")
        # Fallback về raw HTTP client cũ
        return _GroqHttpWrapper(api_key)
    except Exception as e:
        logger.error(f"Lỗi khởi tạo Groq SDK: {e}")
        return None


class _GroqWrapper:
    """Wrapper cho Groq SDK chính thức — thêm rate limit và retry."""

    def __init__(self, client, model_name: str = "llama-3.3-70b-versatile"):
        self._client = client
        self.model_name = model_name

    @groq_limiter.throttle
    @api_retrier.retry
    def generate_content(self, prompt: str) -> object:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096
        )

        class ResponseMock:
            def __init__(self, text: str):
                self.text = text

        return ResponseMock(response.choices[0].message.content)


class _GroqHttpWrapper:
    """
    Fallback: Gọi Groq qua raw HTTP nếu SDK chưa được cài.
    Giữ lại để không bị lỗi khi groq package chưa install.
    """

    def __init__(self, api_key: str, model_name: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model_name = model_name
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    @groq_limiter.throttle
    def generate_content(self, prompt: str) -> object:
        import requests as _requests
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        response = _requests.post(self.url, json=payload, headers=self.headers, timeout=30)
        if response.status_code == 200:
            text_content = response.json()["choices"][0]["message"]["content"]

            class ResponseMock:
                def __init__(self, text: str):
                    self.text = text

            return ResponseMock(text_content)
        elif response.status_code == 429:
            raise Exception(f"Groq rate limit (429): {response.text}")
        else:
            raise Exception(f"Groq API error ({response.status_code}): {response.text}")


def analyze_stock_with_ai(
    symbol: str,
    price_data_summary: dict,
    technical_signals: dict,
    financial_ratios: pd.DataFrame = None,
    news_list: list = None,
    canslim_data: dict = None
) -> str:
    """
    Sử dụng Groq API để sinh báo cáo phân tích cổ phiếu lướt sóng chuyên sâu.
    """
    model = init_gemini()

    # Chuẩn bị thông tin đầu vào cho Prompt
    signals_str = "\n".join([f"- {d}" for d in technical_signals.get("details", [])])

    fin_str = ""
    if financial_ratios is not None and not financial_ratios.empty:
        try:
            latest_fin = financial_ratios.iloc[0].to_dict() if len(financial_ratios) > 0 else {}
            fin_str = "\n".join([f"- {k}: {v}" for k, v in latest_fin.items() if pd.notna(v)])
        except Exception:
            fin_str = "Không có dữ liệu tài chính chi tiết."
    else:
        fin_str = "Không có dữ liệu tài chính chi tiết."

    news_str = ""
    if news_list:
        news_str = "\n".join([f"- [{n.get('time')}]: {n.get('title')}" for n in news_list])
    else:
        news_str = "Không có thông tin tin tức mới."

    canslim_str = ""
    if canslim_data:
        canslim_str = f"- Điểm số CANSLIM tổng hợp: {canslim_data.get('total_score', 'N/A')}/100 (Phân loại: {canslim_data.get('rating', 'NEUTRAL')})\n"
        canslim_str += "Chi tiết điểm các thành phần:\n"
        for k, v in canslim_data.get('details', {}).items():
            canslim_str += f"  * {k} ({v.get('score')}đ): {v.get('desc')}\n"
    else:
        canslim_str = "Chưa cấu hình hoặc thiếu dữ liệu chấm điểm CANSLIM."

    prompt = f"""
Bạn là một chuyên gia phân tích kỹ thuật và quản lý danh mục đầu tư chứng khoán chuyên nghiệp tại thị trường Việt Nam.
Hãy viết một báo cáo phân tích lướt sóng ngắn hạn (swing trading) cho mã cổ phiếu: **{symbol}**.

Dưới đây là dữ liệu giao dịch gần nhất của cổ phiếu này:
- Giá hiện tại: {price_data_summary.get('close', 'N/A')} (nghìn VNĐ)
- Giá cao nhất trong ngày: {price_data_summary.get('high', 'N/A')}
- Giá thấp nhất trong ngày: {price_data_summary.get('low', 'N/A')}
- Khối lượng giao dịch: {price_data_summary.get('volume', 'N/A')} (so với trung bình 20 phiên: {price_data_summary.get('volume_sma20', 'N/A')})

Dữ liệu tín hiệu kỹ thuật tự động quét được:
- Trạng thái tổng quát: {technical_signals.get('status', 'NEUTRAL')}
- Điểm số kỹ thuật (-5 đến +5): {technical_signals.get('score', 0)}
- Xu hướng ngắn hạn: {technical_signals.get('trend', 'Neutral')}
- Trạng thái RSI (14): {technical_signals.get('rsi', 50):.2f}
- Trạng thái MACD: {technical_signals.get('macd_signal', 'Neutral')}
- Chi tiết tín hiệu quét được:
{signals_str}

Các chỉ số cơ bản của doanh nghiệp:
{fin_str}

Chấm điểm chất lượng cổ phiếu theo tiêu chí CANSLIM / Minervini:
{canslim_str}

Tin tức mới nhận được liên quan đến doanh nghiệp:
{news_str}

Yêu cầu báo cáo bao gồm các phần sau (sử dụng định dạng Markdown rõ ràng, chuyên nghiệp):
1. **Đánh giá xu hướng ngắn hạn**: Giải thích xu hướng giá hiện tại dựa trên các đường EMA, RSI, MACD, chỉ báo xu hướng nâng cao (SuperTrend) và khối lượng giao dịch. Tín hiệu này mạnh hay yếu?
2. **Đánh giá điểm cơ bản & CANSLIM & Tin tức**: Phân tích sức khỏe tài chính doanh nghiệp (P/E, P/B, ROE...) và điểm số chất lượng CANSLIM kết hợp tin tức gần đây để bổ trợ cho phân tích kỹ thuật.
3. **Kế hoạch giao dịch lướt sóng**:
   - Khuyến nghị hành động (MUA mạnh, MUA, THEO DÕI, BÁN, BÁN mạnh).
   - Vùng giá mua đề xuất (nếu khuyến nghị mua).
   - Điểm chốt lời mục tiêu (Target).
   - Điểm dừng lỗ bắt buộc (Stop-loss) (gợi ý dựa trên ATR hoặc hỗ trợ cứng).
4. **Cảnh báo rủi ro**: Liệt kê các rủi ro (thị trường chung VN-Index, rủi ro thanh khoản, rủi ro tin tức tiêu cực của mã này).

Hãy viết báo cáo bằng tiếng Việt, giọng văn khách quan, sắc bén, chuyên nghiệp của một chuyên gia phân tích.
"""

    if not model:
        # Báo cáo mẫu khi không có API Key
        mock_report = f"""
### 🚨 Trợ lý AI WaveTrader - Chế độ dùng thử (Demo)

*Lưu ý: Bạn chưa cấu hình `GROQ_API_KEY` trong file `.env` hoặc Key không hợp lệ. Đây là báo cáo tự động dựa trên quy tắc kỹ thuật cứng.*

#### 1. Đánh giá xu hướng ngắn hạn cho **{symbol}**
- **Trạng thái**: {technical_signals.get('status', 'NEUTRAL')}
- **Xu hướng**: {technical_signals.get('trend', 'Neutral')}
- Giá hiện tại là {price_data_summary.get('close', 'N/A')} nghìn VNĐ. Chỉ số RSI đang ở mức {technical_signals.get('rsi', 50):.2f}.
- Tín hiệu kỹ thuật tự động ghi nhận:
{signals_str}

#### 2. Kế hoạch giao dịch lướt sóng đề xuất:
- **Khuyến nghị**: **{technical_signals.get('status', 'NEUTRAL')}**
- **Vùng giá mua**: Xem xét mua quanh giá hiện tại nếu thị trường chung ổn định.
- **Điểm dừng lỗ (Stop-loss)**: Đề xuất đặt dưới mức giá thấp nhất 10 phiên hoặc cách giá hiện tại khoảng 5-7%.
- **Điểm chốt lời (Target)**: Đề xuất chốt lời từng phần khi đạt lợi nhuận 8% - 15% hoặc khi giá chạm biên trên Bollinger Bands.

*👉 Vui lòng thêm `GROQ_API_KEY` vào file `.env` ở thư mục gốc để kích hoạt báo cáo phân tích thông minh và chi tiết từ AI Groq.*
"""
        return mock_report

    try:
        logger.info(f"Đang gọi Groq API để phân tích mã {symbol}...")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Lỗi khi gọi Groq API cho mã {symbol}: {e}")
        return f"Không thể tạo báo cáo AI do lỗi kết nối hoặc giới hạn API: {e}"


if __name__ == "__main__":
    print(analyze_stock_with_ai(
        "HPG",
        {"close": 28.5, "high": 28.7, "low": 28.2, "volume": 12000000, "volume_sma20": 10000000},
        {"status": "BUY", "score": 2.0, "trend": "BULLISH", "rsi": 62.5,
         "macd_signal": "Golden Cross", "details": ["Giá vượt EMA20", "MACD cắt lên đường Tín hiệu"]}
    ))
