import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import threading
from vnstock import Market

# Add project root to path
sys.path.append(os.getcwd())

from config import MY_PORTFOLIO, INDICATOR_PARAMS
from src.notifier import send_telegram_message
from src.data_fetcher import get_stock_ohlcv
from src.indicators import find_support_resistance
from src.paper_trader import load_portfolio, check_and_execute_auto_orders

# Thiết lập Logging ghi cả ra File và Console
log_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.FileHandler("portfolio_monitor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Bộ nhớ lưu vết các cảnh báo đã gửi trong ngày để tránh spam tin nhắn liên tục
# Cấu trúc: {(symbol, alert_type): date_string}
sent_alerts = {}

# Mức hỗ trợ động được tính từ EOD hôm trước để so sánh thời gian thực
dynamic_supports = {}

def calculate_dynamic_supports():
    """
    Tính mức hỗ trợ cứng cho các mã trong danh mục dựa trên dữ liệu lịch sử 60 phiên.
    """
    logging.info("Đang tính toán mức hỗ trợ kỹ thuật cho danh mục của bạn...")
    for item in MY_PORTFOLIO:
        symbol = item["symbol"]
        df = get_stock_ohlcv(symbol, length=60)
        if not df.empty:
            sr = find_support_resistance(df)
            dynamic_supports[symbol] = sr["support"]
            logging.info(f"  - {symbol}: Mức hỗ trợ kỹ thuật được xác định ở giá {sr['support']:.2f}")
        else:
            dynamic_supports[symbol] = None
        time.sleep(2.0) # Tránh bị lỗi Rate Limit

import json

PROCESSED_NEWS_FILE = "processed_news.json"

def analyze_news_sentiment_realtime(symbol: str, title: str) -> float:
    """
    Sử dụng Groq API để phân tích xem tiêu đề tin tức có phải là tin tức cực xấu (tiêu cực) ảnh hưởng đến giá cổ phiếu hay không.
    Trả về điểm số từ -1.0 (cực kỳ tiêu cực) đến 1.0 (cực kỳ tích cực).
    Tích hợp cơ chế tự động thử lại (retry) khi gặp lỗi giới hạn tần suất gọi API (429 Rate Limit).
    """
    import requests
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logging.warning("GROQ_API_KEY chưa được thiết lập trong file .env")
        return 0.0
        
    prompt = f"""
    Bạn là một chuyên gia phân tích tài chính chứng khoán. Hãy phân tích xem tin tức dưới đây đối với mã cổ phiếu {symbol} là tích cực hay tiêu cực.
    
    Tin tức: "{title}"
    
    Hãy chỉ trả về duy nhất một con số thực nằm trong khoảng từ -1.0 (cực kỳ tiêu cực, nguy hại, giá có thể giảm sàn ngay lập tức) đến 1.0 (cực kỳ tích cực). Không trả về bất kỳ từ ngữ hay giải thích nào khác.
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
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                result = response.json()
                score_str = result["choices"][0]["message"]["content"].strip()
                try:
                    return float(score_str)
                except ValueError:
                    import re
                    match = re.search(r"[-+]?\d*\.\d+|\d+", score_str)
                    if match:
                        return float(match.group())
                    return 0.0
            elif response.status_code == 429:
                logging.warning(f"Chạm giới hạn gọi API Groq (429). Thử lại lần {attempt+1}/{max_retries} sau {delay} giây...")
                time.sleep(delay)
                delay *= 2
            else:
                logging.error(f"Lỗi phản hồi Groq API ({response.status_code}): {response.text}")
                break
        except Exception as e:
            logging.error(f"Lỗi kết nối hoặc xử lý Groq API: {e}")
            time.sleep(delay)
            delay *= 2
                
    return 0.0

def check_realtime_news_alerts(portfolio_symbols: list):
    """
    Quét tin tức mới nhất của các mã trong danh mục và gửi cảnh báo nếu phát hiện tin tức cực xấu (Gemini score <= -0.6).
    """
    if not portfolio_symbols:
        return
        
    processed_urls = set()
    if os.path.exists(PROCESSED_NEWS_FILE):
        try:
            with open(PROCESSED_NEWS_FILE, "r", encoding="utf-8") as f:
                processed_urls = set(json.load(f))
        except Exception as e:
            logging.error(f"Lỗi đọc file cache tin tức: {e}")
            
    from src.data_fetcher import get_stock_news
    
    for sym in portfolio_symbols:
        news_list = get_stock_news(sym, limit=2)
        for news in news_list:
            url = news.get("url")
            title = news.get("title")
            
            news_key = url if url else f"{sym}_{title}"
            
            if news_key not in processed_urls:
                logging.info(f"Phát hiện tin mới cho {sym}: {title}")
                score = analyze_news_sentiment_realtime(sym, title)
                logging.info(f"  - Điểm sắc thái tin tức từ Gemini: {score:+.2f}")
                
                if score <= -0.6:
                    alert_msg = f"🚨 *[CẢNH BÁO TIN XẤU KHẨN CẤP - {sym}]* 🚨\n\n" \
                                f"Hệ thống vừa phát hiện tin tức tiêu cực nghiêm trọng có thể ảnh hưởng nặng tới giá cổ phiếu **{sym}** bạn đang theo dõi:\n\n" \
                                f"👉 *{title}*\n\n" \
                                f"⚠️ *Đánh giá AI:* Nguy hiểm cao (Điểm: **{score:.2f}**)\n" \
                                f"🔗 *Chi tiết:* [Đọc tin tại đây]({url})\n\n" \
                                f"💡 _Hãy kiểm tra ngay trạng thái tài khoản thực tế và đồ thị để cân nhắc bán bảo toàn tài sản!_"
                    send_telegram_message(alert_msg)
                    logging.info(f"Đã gửi cảnh báo tin tức khẩn cấp cho {sym}")
                    
                processed_urls.add(news_key)
                time.sleep(2.0) # Tránh Rate Limit
                
    # Lưu lại bộ nhớ cache tin tức
    try:
        with open(PROCESSED_NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(processed_urls), f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Lỗi ghi file cache tin tức: {e}")

def is_market_hours() -> bool:
    """
    Kiểm tra xem thời điểm hiện tại có đang trong giờ giao dịch Việt Nam hay không.
    Thứ 2 - Thứ 6: Sáng (9:00 - 11:30), Chiều (13:00 - 14:45).
    """
    now = datetime.now(timezone(timedelta(hours=7)))
    # Thứ 7 (5) và Chủ nhật (6) đóng cửa
    if now.weekday() >= 5:
        return False
        
    current_time = now.time()
    morning_start = datetime.strptime("09:00:00", "%H:%M:%S").time()
    morning_end = datetime.strptime("11:30:00", "%H:%M:%S").time()
    afternoon_start = datetime.strptime("13:00:00", "%H:%M:%S").time()
    afternoon_end = datetime.strptime("14:45:00", "%H:%M:%S").time()
    
    return (morning_start <= current_time <= morning_end) or (afternoon_start <= current_time <= afternoon_end)

def run_portfolio_monitor():
    """
    Vòng lặp giám sát danh mục thời gian thực và gửi tin nhắn cảnh báo.
    """
    logging.info("=== BẮT ĐẦU KHỞI CHẠY HỆ THỐNG GIÁM SÁT DANH MỤC REALTIME ===")
    
    # 1. Tính toán trước mức hỗ trợ động lúc khởi tạo
    calculate_dynamic_supports()
    
    m = Market()
    
    while True:
        # Kiểm tra giờ giao dịch bảo vệ tài nguyên
        if not is_market_hours():
            logging.info("Thị trường chứng khoán đang đóng cửa. Hệ thống tạm nghỉ... (Kiểm tra lại sau 15 phút)")
            time.sleep(900) # Sleep 15 phút
            continue
            
        logging.info("Bắt đầu chu kỳ quét giá thời gian thực...")
        today_str = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        
        # 2. Tải danh mục ảo để lấy thêm các mã cần giám sát
        port = load_portfolio()
        pos_symbols = [pos["symbol"] for pos in port.get("positions", [])]
        
        # Kết hợp các mã trong danh mục thực tế (MY_PORTFOLIO) và danh mục ví ảo
        all_symbols = list(set([item["symbol"] for item in MY_PORTFOLIO] + pos_symbols))
        
        current_prices = {}
        
        for symbol in all_symbols:
            try:
                # Gọi API lấy giá khớp thời gian thực
                df_quote = m.equity(symbol).quote()
                
                if df_quote.empty:
                    logging.warning(f"Không thể lấy bảng giá thời gian thực cho mã {symbol}")
                    continue
                    
                close_price = df_quote.iloc[0]["close_price"]
                percent_change = df_quote.iloc[0]["percent_change"]
                
                # Fallback nếu giá khớp bằng 0 (ngoài giờ giao dịch hoặc đầu phiên chưa khớp lệnh)
                if close_price <= 0:
                    close_price = df_quote.iloc[0].get("reference_price", 0)
                    if close_price <= 0:
                        logging.warning(f"Giá khớp lệnh và giá tham chiếu của {symbol} đều không hợp lệ. Bỏ qua.")
                        continue
                
                # Chuẩn hóa đơn vị giá (từ VNĐ về nghìn VNĐ nếu API trả về VNĐ thực tế)
                if close_price > 1000:
                    close_price /= 1000.0
                
                current_prices[symbol] = close_price
                
                # Tìm xem mã này có trong MY_PORTFOLIO để chạy cảnh báo thực tế không
                my_portfolio_item = next((item for item in MY_PORTFOLIO if item["symbol"] == symbol), None)
                
                if my_portfolio_item:
                    entry_price = my_portfolio_item["entry_price"]
                    stop_loss = my_portfolio_item.get("stop_loss")
                    if stop_loss is None:
                        stop_loss = entry_price * 0.95
                        
                    # Tính phần trăm lỗ thực tế dựa trên giá mua
                    loss_pct = ((close_price - entry_price) / entry_price) * 100
                    
                    logging.info(f"[{symbol} - Thực tế] Giá hiện tại: {close_price:.2f} ({percent_change:+.2f}%) | Giá mua: {entry_price:.2f} | Cắt lỗ: {stop_loss:.2f} (Lỗ hiện tại: {loss_pct:.1f}%)")
                    
                    # 2.1. KIỂM TRA ĐIỀU KIỆN CẮT LỖ CỨNG (HARD STOP-LOSS)
                    if close_price <= stop_loss:
                        alert_key = (symbol, "stop_loss")
                        if sent_alerts.get(alert_key) != today_str:
                            alert_msg = f"🚨 *CẢNH BÁO CẮT LỖ KHẨN CẤP* 🚨\n\n" \
                                        f"Mã cổ phiếu: **{symbol}** đã giảm chạm hoặc vượt quá ngưỡng cắt lỗ đặt ra!\n" \
                                        f"───────────────────\n" \
                                        f"- *Giá mua của bạn:* **{entry_price:.2f}**\n" \
                                        f"- *Ngưỡng cắt lỗ:* **{stop_loss:.2f}**\n" \
                                        f"- *Giá khớp hiện tại:* **{close_price:.2f}** (Thua lỗ: **{loss_pct:.1f}%**)\n" \
                                        f"───────────────────\n" \
                                        f"👉 *Khuyến nghị:* Hãy thực hiện **BÁN NGAY LẬP TỨC** toàn bộ vị thế của mã này để bảo toàn vốn!"
                            
                            logging.warning(f"🔥 CẢNH BÁO: {symbol} chạm ngưỡng cắt lỗ {stop_loss}! Gửi thông báo Telegram...")
                            if send_telegram_message(alert_msg):
                                sent_alerts[alert_key] = today_str
                                
                    # 2.2. KIỂM TRA ĐIỀU KIỆN THỦNG HỖ TRỢ KỸ THUẬT ĐỘNG (DYNAMIC SUPPORT BREACH)
                    support_val = dynamic_supports.get(symbol)
                    if support_val and close_price < support_val:
                        alert_key = (symbol, "support_breach")
                        if sent_alerts.get(alert_key) != today_str:
                            alert_msg = f"⚠️ *CẢNH BÁO THỦNG HỖ TRỢ KỸ THUẬT* ⚠️\n\n" \
                                        f"Mã cổ phiếu: **{symbol}** đã đâm thủng mức hỗ trợ cứng được tính toán!\n" \
                                        f"───────────────────\n" \
                                        f"- *Mức hỗ trợ kỹ thuật:* **{support_val:.2f}**\n" \
                                        f"- *Giá khớp hiện tại:* **{close_price:.2f}**\n" \
                                        f"───────────────────\n" \
                                        f"👉 *Khuyến nghị:* Hành vi thủng hỗ trợ báo hiệu xu hướng ngắn hạn chuyển sang tiêu cực. Cân nhắc hạ 50% tỷ trọng!"
                            
                            logging.warning(f"⚠️ CẢNH BÁO: {symbol} thủng hỗ trợ kỹ thuật {support_val}! Gửi thông báo Telegram...")
                            if send_telegram_message(alert_msg):
                                sent_alerts[alert_key] = today_str
                # 2.3. KIỂM TRA CẢNH BÁO BÁN SỚM CHO VỊ THẾ VÍ ẢO (EARLY EXIT WARNING)
                if symbol in pos_symbols:
                    pos_item = next(p for p in port["positions"] if p["symbol"] == symbol)
                    df_sym = get_stock_ohlcv(symbol, length=120)
                    if not df_sym.empty:
                        from src.indicators import calculate_indicators, check_swing_signals
                        df_sym = calculate_indicators(df_sym, symbol=symbol)
                        sig = check_swing_signals(df_sym, symbol=symbol)
                        
                        if sig["status"] in ["SELL", "STRONG SELL"]:
                            alert_key = (symbol, "early_exit")
                            if sent_alerts.get(alert_key) != today_str:
                                p_change_pct = ((close_price - pos_item["buy_price"]) / pos_item["buy_price"]) * 100
                                alert_msg = f"⚠️ *[VÍ ẢO - CẢNH BÁO BÁN SỚM]* ⚠️\n\n" \
                                            f"Vị thế **{symbol}** đang nắm giữ có dấu hiệu suy yếu kỹ thuật ({sig['status']})!\n" \
                                            f"───────────────────\n" \
                                            f"- *Giá mua ảo:* **{pos_item['buy_price']:.2f}**\n" \
                                            f"- *Giá khớp hiện tại:* **{close_price:.2f}** (Lãi/Lỗ: **{p_change_pct:+.2f}%**)\n" \
                                            f"- *Chi tiết suy yếu:* {', '.join(sig['details']) if sig['details'] else 'Xu hướng bắt đầu suy giảm'}\n" \
                                            f"───────────────────\n" \
                                            f"👉 *Khuyến nghị:* Xu hướng chuyển biến xấu. Cân nhắc bán chủ động chốt lời/cắt lỗ sớm trên sàn thực tế!"
                                
                                logging.warning(f"⚠️ CẢNH BÁO BÁN SỚM: {symbol} có tín hiệu suy yếu ({sig['status']})! Gửi thông báo Telegram...")
                                if send_telegram_message(alert_msg):
                                    sent_alerts[alert_key] = today_str
                                    
            except Exception as e:
                logging.error(f"Lỗi khi xử lý giám sát mã {symbol}: {e}")
                
            # Nghỉ 2.5 giây giữa mỗi cổ phiếu tránh quá tải API Rate Limit
            time.sleep(2.5)
            
        # 3. KIỂM TRA VÀ TỰ ĐỘNG KHỚP LỆNH DỪNG LỖ / CHỐT LỜI CHO VÍ ẢO (AUTO PAPER ORDERS)
        if current_prices:
            try:
                triggered_alerts = check_and_execute_auto_orders(current_prices)
                for alert in triggered_alerts:
                    logging.info(f"Kích hoạt lệnh Ví ảo tự động: {alert}")
                    send_telegram_message(alert)
            except Exception as e:
                logging.error(f"Lỗi khi kiểm tra lệnh tự động ví ảo: {e}")
                
        # 4. QUÉT TIN TỨC NÓNG THỜI GIAN THỰC (REALTIME NEWS SENTIMENT ALERTS)
        try:
            p_syms = set()
            for item in MY_PORTFOLIO:
                p_syms.add(item["symbol"])
            v_port = load_portfolio()
            for pos in v_port.get("positions", []):
                p_syms.add(pos["symbol"])
            check_realtime_news_alerts(list(p_syms))
        except Exception as e:
            logging.error(f"Lỗi khi quét tin tức nóng danh mục: {e}")
            
        # Nghỉ 120 giây (2 phút) trước khi chạy chu kỳ kiểm tra tiếp theo
        logging.info("Đã quét xong chu kỳ. Nghỉ 2 phút...")
        time.sleep(120)

def telegram_polling_loop():
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logging.warning("[BOT] TELEGRAM_BOT_TOKEN chưa được cấu hình. Luồng phản hồi tương tác bị tắt.")
        return
        
    logging.info("[BOT] Khởi động luồng lắng nghe tương tác Telegram Bot thành công.")
    offset = 0
    from src.paper_trader import buy_stock
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=15"
            response = requests.get(url, timeout=20)
            if response.status_code != 200:
                time.sleep(5)
                continue
                
            res = response.json()
            if not res.get("ok"):
                time.sleep(5)
                continue
                
            for update in res.get("result", []):
                offset = update["update_id"] + 1
                
                # Xử lý callback từ nút bấm
                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_data = cb.get("data", "")
                    cb_id = cb["id"]
                    chat_id = cb["message"]["chat"]["id"]
                    
                    # Cấu trúc callback_data: buy_{symbol}_{price}
                    if cb_data.startswith("buy_"):
                        parts = cb_data.split("_")
                        if len(parts) >= 3:
                            symbol = parts[1]
                            try:
                                buy_price = float(parts[2])
                            except ValueError:
                                buy_price = 0.0
                                
                            # Tính toán cắt lỗ/chốt lời động theo ATR
                            from src.paper_trader import get_atr_for_symbol
                            atr = get_atr_for_symbol(symbol)
                            if atr > 0:
                                sl = round(buy_price - 2 * atr, 2)
                                tp = round(buy_price + 4 * atr, 2)
                            else:
                                sl = round(buy_price * 0.94, 2)
                                tp = round(buy_price * 1.15, 2)
                            
                            # Thực hiện mua ảo
                            buy_res = buy_stock(symbol, buy_price, quantity=100, stop_loss=sl, take_profit=tp)
                            
                            # Soạn tin nhắn phản hồi
                            if buy_res.get("success"):
                                reply_msg = f"🟢 *XÁC NHẬN GIÁM SÁT THÀNH CÔNG* 🟢\n\n" \
                                            f"Đã thêm vị thế mua ảo mã **{symbol}** vào danh sách giám sát!\n" \
                                            f"───────────────────\n" \
                                            f"- *Giá mua ghi nhận:* **{buy_price:.2f}**\n" \
                                            f"- *Ngưỡng cắt lỗ (SL):* **{sl:.2f}**\n" \
                                            f"- *Ngưỡng chốt lời (TP):* **{tp:.2f}**\n" \
                                            f"───────────────────\n" \
                                            f"🖥️ Hệ thống sẽ theo dõi giá thời gian thực liên tục trong phiên giao dịch và gửi cảnh báo BÁN khẩn cấp qua Telegram ngay khi chạm cắt lỗ/chốt lời hoặc khi xu hướng kỹ thuật bắt đầu yếu đi!"
                            else:
                                reply_msg = f"🔴 *XÁC NHẬN GIÁM SÁT THẤT BẠI* 🔴\n\nLý do: {buy_res.get('message')}"
                                
                            # Gửi tin nhắn xác nhận
                            send_url = f"https://api.telegram.org/bot{token}/sendMessage"
                            requests.post(send_url, json={
                                "chat_id": chat_id,
                                "text": reply_msg,
                                "parse_mode": "Markdown"
                            })
                            
                            # Tắt vòng xoay chờ của nút bấm trên app Telegram
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={
                                "callback_query_id": cb_id,
                                "text": f"Đã xử lý yêu cầu giám sát {symbol}!"
                            })
                            
        except Exception as e:
            logging.error(f"[BOT] Lỗi trong vòng lặp lắng nghe tương tác Telegram: {e}")
            time.sleep(5)

def daily_report_scheduler_loop():
    """
    Luồng chạy độc lập kiểm tra và tự động gửi báo cáo hàng ngày lúc 15:15 (GMT+7) từ Thứ 2 - Thứ 6.
    """
    logging.info("[SCHEDULER] Khởi động luồng hẹn giờ báo cáo hàng ngày thành công.")
    from datetime import datetime, timedelta, timezone
    
    def get_vietnam_now():
        return datetime.now(timezone(timedelta(hours=7)))
        
    last_sent_date = ""
    
    while True:
        try:
            vn_now = get_vietnam_now()
            # Chỉ chạy từ Thứ 2 đến Thứ 6 (ngày giao dịch)
            if vn_now.weekday() < 5:
                today_str = vn_now.strftime("%Y-%m-%d")
                # Hẹn giờ từ lúc 15:15 đến hết khung giờ 15:00-16:00
                if (vn_now.hour == 15 and vn_now.minute >= 15) and last_sent_date != today_str:
                    logging.info("[SCHEDULER] Đến giờ tự động gửi báo cáo hàng ngày (15:15)...")
                    from src.notifier import send_daily_report_to_telegram
                    success = send_daily_report_to_telegram()
                    if success:
                        logging.info("[SCHEDULER] Tự động gửi báo cáo EOD thành công.")
                        last_sent_date = today_str
                    else:
                        logging.error("[SCHEDULER] Tự động gửi báo cáo EOD thất bại. Sẽ thử lại sau 60 giây.")
                        time.sleep(60)
                        continue
            
            # Quét mỗi 30 giây để kiểm tra giờ
            time.sleep(30)
        except Exception as e:
            logging.error(f"[SCHEDULER] Lỗi trong luồng hẹn giờ báo cáo: {e}")
            time.sleep(60)

if __name__ == "__main__":
    try:
        # 1. Khởi chạy luồng Telegram Bot Polling lắng nghe tương tác
        bot_thread = threading.Thread(target=telegram_polling_loop, daemon=True)
        bot_thread.start()
        
        # 2. Khởi chạy luồng Scheduler tự động gửi báo cáo cuối ngày EOD lúc 15:15
        scheduler_thread = threading.Thread(target=daily_report_scheduler_loop, daemon=True)
        scheduler_thread.start()
        
        # 3. Chạy luồng giám sát chính
        run_portfolio_monitor()
    except KeyboardInterrupt:
        logging.info("Tiến trình giám sát danh mục đã bị dừng bởi người dùng.")
