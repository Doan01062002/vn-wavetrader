"""
Module giám sát danh mục thời gian thực.
Chịu trách nhiệm:
- Tính mức hỗ trợ/kháng cự kỹ thuật động
- Giám sát giá real-time và gửi cảnh báo stop-loss, hỗ trợ
- Phân tích tin tức bất lợi real-time
- Tự động kích hoạt lệnh SL/TP cho ví ảo

Cải tiến v2:
- Tất cả import đặt đầu file
- sent_alerts được bảo vệ bằng Lock
- Logic kiểm tra giờ giao dịch dùng giờ Việt Nam chuẩn
- Chuẩn hóa giá dùng hàm helper (loại bỏ magic number)
"""
import os
import re
import sys
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta

import pandas as pd
from vnstock import Market

# --- Internal imports ---
from config import MY_PORTFOLIO, INDICATOR_PARAMS
from src.notifier import send_telegram_message
from src.data_fetcher import get_stock_ohlcv, get_stock_news
from src.indicators import find_support_resistance, calculate_indicators, check_swing_signals
from src.paper_trader import load_portfolio, check_and_execute_auto_orders
from src.rate_limiter import vnstock_limiter, groq_limiter

logger = logging.getLogger(__name__)

# ==============================================================
# Shared state (bảo vệ bằng Lock)
# ==============================================================
_sent_alerts: dict = {}
_sent_alerts_lock = threading.Lock()

_dynamic_supports: dict = {}

PROCESSED_NEWS_FILE = "processed_news.json"
NEWS_RETENTION_DAYS = 30  # Xóa cache tin tức cũ hơn 30 ngày


# ==============================================================
# Helpers
# ==============================================================

def _normalize_price(raw_price: float, symbol: str) -> float:
    """
    Chuẩn hóa đơn vị giá từ API về nghìn VNĐ.
    vnstock v4 trả về đơn vị VNĐ (số nguyên lớn > 10000), cần chia 1000.
    
    Ngưỡng: nếu giá > 10,000 thì giả định đơn vị là VNĐ → chia 1000.
    Ngưỡng 10,000 thay vì 1,000 để tránh nhầm với cổ phiếu giá cao (VNM, SAB...).
    """
    if raw_price > 10_000:
        logger.debug(f"[{symbol}] Chuẩn hóa giá: {raw_price} VNĐ → {raw_price / 1000:.2f} nghìn VNĐ")
        return raw_price / 1000.0
    return raw_price


def _is_alert_sent_today(symbol: str, alert_type: str) -> bool:
    """Kiểm tra xem cảnh báo này đã được gửi hôm nay chưa (thread-safe)."""
    today_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    with _sent_alerts_lock:
        return _sent_alerts.get((symbol, alert_type)) == today_str


def _mark_alert_sent(symbol: str, alert_type: str) -> None:
    """Đánh dấu cảnh báo đã gửi hôm nay (thread-safe)."""
    today_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    with _sent_alerts_lock:
        _sent_alerts[(symbol, alert_type)] = today_str


def is_market_hours() -> bool:
    """
    Kiểm tra thời điểm hiện tại có đang trong giờ giao dịch Việt Nam hay không.
    Thứ 2 - Thứ 6: Sáng (9:00 - 11:30), Chiều (13:00 - 14:45).
    """
    now = datetime.now(timezone(timedelta(hours=7)))
    if now.weekday() >= 5:  # Thứ 7 (5) và Chủ nhật (6)
        return False

    t = now.time()
    from datetime import time as dt_time
    return (
        dt_time(9, 0) <= t <= dt_time(11, 30)
        or dt_time(13, 0) <= t <= dt_time(14, 45)
    )


# ==============================================================
# Tính mức hỗ trợ động
# ==============================================================

def calculate_dynamic_supports() -> None:
    """Tính mức hỗ trợ kỹ thuật cho các mã trong danh mục dựa trên 60 phiên lịch sử."""
    logger.info("Đang tính toán mức hỗ trợ kỹ thuật cho danh mục...")
    for item in MY_PORTFOLIO:
        symbol = item["symbol"]
        with vnstock_limiter:
            df = get_stock_ohlcv(symbol, length=60)
        if not df.empty:
            sr = find_support_resistance(df)
            _dynamic_supports[symbol] = sr["support"]
            logger.info(f"  - {symbol}: Mức hỗ trợ kỹ thuật = {sr['support']:.2f}")
        else:
            _dynamic_supports[symbol] = None


# ==============================================================
# Phân tích tin tức real-time
# ==============================================================

def _load_processed_news() -> set:
    """Tải cache URL tin tức đã xử lý, loại bỏ entries cũ hơn NEWS_RETENTION_DAYS ngày."""
    if not os.path.exists(PROCESSED_NEWS_FILE):
        return set()
    try:
        with open(PROCESSED_NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Support both old format (list of strings) and new format (dict with timestamp)
        if isinstance(data, list):
            # Old format: chuyển đổi sang format mới
            return set(data)
        elif isinstance(data, dict):
            # New format: {url: timestamp_str} — lọc bỏ entries cũ
            cutoff = datetime.now() - __import__('datetime').timedelta(days=NEWS_RETENTION_DAYS)
            valid = set()
            for url, ts_str in data.items():
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts >= cutoff:
                        valid.add(url)
                except Exception:
                    valid.add(url)
            return valid
    except Exception as e:
        logger.error(f"Lỗi đọc file cache tin tức: {e}")
        return set()


def _save_processed_news(processed_urls: set) -> None:
    """Lưu cache tin tức đã xử lý (format mới: dict url → timestamp)."""
    try:
        # Giữ timestamp cho các URL mới, dùng now() cho URL cũ (từ format cũ)
        now_str = datetime.now().isoformat()
        # Load existing data để giữ timestamps cũ
        existing = {}
        if os.path.exists(PROCESSED_NEWS_FILE):
            try:
                with open(PROCESSED_NEWS_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    existing = raw
            except Exception:
                pass

        # Merge: giữ timestamp cũ nếu có, gán now cho mới
        merged = {url: existing.get(url, now_str) for url in processed_urls}

        with open(PROCESSED_NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi ghi file cache tin tức: {e}")


def analyze_news_sentiment_realtime(symbol: str, title: str) -> float:
    """
    Sử dụng Groq API để phân tích sắc thái tiêu đề tin tức.
    Trả về điểm từ -1.0 (cực xấu) đến 1.0 (cực tốt).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY chưa được thiết lập.")
        return 0.0

    prompt = f"""
Bạn là một chuyên gia phân tích tài chính chứng khoán. Hãy phân tích xem tin tức dưới đây đối với mã cổ phiếu {symbol} là tích cực hay tiêu cực.

Tin tức: "{title}"

Hãy chỉ trả về duy nhất một con số thực nằm trong khoảng từ -1.0 (cực kỳ tiêu cực) đến 1.0 (cực kỳ tích cực). Không trả về bất kỳ từ ngữ hay giải thích nào khác.
"""

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    max_retries = 3
    delay = 6.0

    for attempt in range(max_retries):
        try:
            with groq_limiter:
                response = requests.post(url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                score_str = response.json()["choices"][0]["message"]["content"].strip()
                try:
                    return float(score_str)
                except ValueError:
                    match = re.search(r"[-+]?\d*\.\d+|\d+", score_str)
                    return float(match.group()) if match else 0.0
            elif response.status_code == 429:
                logger.warning(f"Rate limit Groq (429). Thử lại sau {delay:.1f}s...")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Lỗi Groq API ({response.status_code}): {response.text}")
                break
        except Exception as e:
            logger.error(f"Lỗi kết nối Groq: {e}")
            time.sleep(delay)
            delay *= 2

    return 0.0


def check_realtime_news_alerts(portfolio_symbols: list) -> None:
    """Quét tin tức mới và gửi cảnh báo nếu phát hiện tin xấu (score <= -0.6)."""
    if not portfolio_symbols:
        return

    processed_urls = _load_processed_news()

    for sym in portfolio_symbols:
        news_list = get_stock_news(sym, limit=2)
        for news in news_list:
            url = news.get("url")
            title = news.get("title")
            news_key = url if url else f"{sym}_{title}"

            if news_key not in processed_urls:
                logger.info(f"Phát hiện tin mới cho {sym}: {title}")
                score = analyze_news_sentiment_realtime(sym, title)
                logger.info(f"  - Điểm sắc thái: {score:+.2f}")

                if score <= -0.6:
                    alert_msg = (
                        f"🚨 *[CẢNH BÁO TIN XẤU KHẨN CẤP - {sym}]* 🚨\n\n"
                        f"Hệ thống vừa phát hiện tin tức tiêu cực nghiêm trọng có thể ảnh hưởng nặng tới giá cổ phiếu **{sym}** bạn đang theo dõi:\n\n"
                        f"👉 *{title}*\n\n"
                        f"⚠️ *Đánh giá AI:* Nguy hiểm cao (Điểm: **{score:.2f}**)\n"
                        f"🔗 *Chi tiết:* [Đọc tin tại đây]({url})\n\n"
                        f"💡 _Hãy kiểm tra ngay trạng thái tài khoản thực tế và đồ thị để cân nhắc bán bảo toàn tài sản!_"
                    )
                    send_telegram_message(alert_msg)
                    logger.info(f"Đã gửi cảnh báo tin xấu cho {sym}")

                processed_urls.add(news_key)

    _save_processed_news(processed_urls)


# ==============================================================
# Vòng lặp giám sát chính
# ==============================================================

def run_portfolio_monitor() -> None:
    """
    Vòng lặp giám sát danh mục thời gian thực.
    Chạy trong thread chính, kiểm tra giá mỗi 2 phút trong giờ giao dịch.
    """
    logger.info("=== BẮT ĐẦU KHỞI CHẠY HỆ THỐNG GIÁM SÁT DANH MỤC REALTIME ===")

    # Tính mức hỗ trợ động lúc khởi tạo
    calculate_dynamic_supports()

    m = Market()

    while True:
        if not is_market_hours():
            logger.info("Thị trường đang đóng cửa. Nghỉ 15 phút...")
            time.sleep(900)
            continue

        logger.info("Bắt đầu chu kỳ quét giá thời gian thực...")

        # Lấy danh sách mã cần giám sát
        port = load_portfolio()
        pos_symbols = [pos["symbol"] for pos in port.get("positions", [])]
        all_symbols = list(set([item["symbol"] for item in MY_PORTFOLIO] + pos_symbols))

        current_prices: dict = {}

        for symbol in all_symbols:
            try:
                with vnstock_limiter:
                    df_quote = m.equity(symbol).quote()

                if df_quote.empty:
                    logger.warning(f"Không thể lấy bảng giá real-time cho {symbol}")
                    continue

                raw_price = df_quote.iloc[0]["close_price"]
                percent_change = df_quote.iloc[0].get("percent_change", 0)

                # Fallback nếu giá khớp bằng 0
                if raw_price <= 0:
                    raw_price = df_quote.iloc[0].get("reference_price", 0)
                    if raw_price <= 0:
                        logger.warning(f"Giá {symbol} không hợp lệ. Bỏ qua.")
                        continue

                close_price = _normalize_price(raw_price, symbol)
                current_prices[symbol] = close_price

                # --- Kiểm tra cảnh báo cho MY_PORTFOLIO ---
                my_item = next((item for item in MY_PORTFOLIO if item["symbol"] == symbol), None)
                if my_item:
                    entry_price = my_item["entry_price"]
                    stop_loss = my_item.get("stop_loss") or (entry_price * 0.95)
                    loss_pct = ((close_price - entry_price) / entry_price) * 100

                    logger.info(
                        f"[{symbol} - Thực tế] Hiện tại: {close_price:.2f} ({percent_change:+.2f}%) | "
                        f"Mua: {entry_price:.2f} | SL: {stop_loss:.2f} (Lỗ: {loss_pct:.1f}%)"
                    )

                    # Cắt lỗ cứng
                    if close_price <= stop_loss and not _is_alert_sent_today(symbol, "stop_loss"):
                        alert_msg = (
                            f"🚨 *CẢNH BÁO CẮT LỖ KHẨN CẤP* 🚨\n\n"
                            f"Mã cổ phiếu: **{symbol}** đã giảm chạm ngưỡng cắt lỗ!\n"
                            f"───────────────────\n"
                            f"- *Giá mua:* **{entry_price:.2f}**\n"
                            f"- *Ngưỡng cắt lỗ:* **{stop_loss:.2f}**\n"
                            f"- *Giá khớp hiện tại:* **{close_price:.2f}** (Thua lỗ: **{loss_pct:.1f}%**)\n"
                            f"───────────────────\n"
                            f"👉 *Khuyến nghị:* **BÁN NGAY** để bảo toàn vốn!"
                        )
                        logger.warning(f"🔥 {symbol} chạm SL {stop_loss}!")
                        if send_telegram_message(alert_msg):
                            _mark_alert_sent(symbol, "stop_loss")

                    # Thủng hỗ trợ kỹ thuật
                    support_val = _dynamic_supports.get(symbol)
                    if support_val and close_price < support_val and not _is_alert_sent_today(symbol, "support_breach"):
                        alert_msg = (
                            f"⚠️ *CẢNH BÁO THỦNG HỖ TRỢ KỸ THUẬT* ⚠️\n\n"
                            f"Mã **{symbol}** đã đâm thủng mức hỗ trợ cứng!\n"
                            f"───────────────────\n"
                            f"- *Mức hỗ trợ kỹ thuật:* **{support_val:.2f}**\n"
                            f"- *Giá khớp hiện tại:* **{close_price:.2f}**\n"
                            f"───────────────────\n"
                            f"👉 Cân nhắc hạ 50% tỷ trọng!"
                        )
                        logger.warning(f"⚠️ {symbol} thủng hỗ trợ {support_val}!")
                        if send_telegram_message(alert_msg):
                            _mark_alert_sent(symbol, "support_breach")

                # --- Kiểm tra cảnh báo bán sớm cho ví ảo ---
                if symbol in pos_symbols:
                    pos_item = next(p for p in port["positions"] if p["symbol"] == symbol)
                    df_sym = get_stock_ohlcv(symbol, length=120)
                    if not df_sym.empty:
                        df_sym = calculate_indicators(df_sym, symbol=symbol)
                        sig = check_swing_signals(df_sym, symbol=symbol)

                        if sig["status"] in ["SELL", "STRONG SELL"] and not _is_alert_sent_today(symbol, "early_exit"):
                            p_change_pct = ((close_price - pos_item["buy_price"]) / pos_item["buy_price"]) * 100
                            alert_msg = (
                                f"⚠️ *[VÍ ẢO - CẢNH BÁO BÁN SỚM]* ⚠️\n\n"
                                f"Vị thế **{symbol}** có dấu hiệu suy yếu kỹ thuật ({sig['status']})!\n"
                                f"───────────────────\n"
                                f"- *Giá mua ảo:* **{pos_item['buy_price']:.2f}**\n"
                                f"- *Giá khớp hiện tại:* **{close_price:.2f}** (Lãi/Lỗ: **{p_change_pct:+.2f}%**)\n"
                                f"- *Chi tiết:* {', '.join(sig['details']) if sig['details'] else 'Xu hướng suy giảm'}\n"
                                f"───────────────────\n"
                                f"👉 Cân nhắc bán chủ động trên sàn thực tế!"
                            )
                            logger.warning(f"⚠️ {symbol} suy yếu kỹ thuật ({sig['status']})")
                            if send_telegram_message(alert_msg):
                                _mark_alert_sent(symbol, "early_exit")

            except Exception as e:
                logger.error(f"Lỗi giám sát mã {symbol}: {e}")

        # Tự động khớp lệnh SL/TP cho ví ảo
        if current_prices:
            try:
                triggered = check_and_execute_auto_orders(current_prices)
                for alert in triggered:
                    logger.info(f"Kích hoạt lệnh ví ảo: {alert[:50]}...")
                    send_telegram_message(alert)
            except Exception as e:
                logger.error(f"Lỗi kiểm tra lệnh tự động ví ảo: {e}")

        # Quét tin tức nóng
        try:
            all_watched = set(item["symbol"] for item in MY_PORTFOLIO)
            for pos in load_portfolio().get("positions", []):
                all_watched.add(pos["symbol"])
            check_realtime_news_alerts(list(all_watched))
        except Exception as e:
            logger.error(f"Lỗi quét tin tức nóng: {e}")

        logger.info("Đã quét xong chu kỳ. Nghỉ 2 phút...")
        time.sleep(120)
