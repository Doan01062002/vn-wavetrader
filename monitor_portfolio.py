import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import threading
from vnstock import Market

# Add project root to path
import socket
socket.setdefaulttimeout(15) # Ngăn chặn nghẽn socket mạng vô hạn khi gọi API
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

def send_telegram_menu(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    menu_markup = {
        "keyboard": [
            [{"text": "🔮 Xem dự báo"}, {"text": "💰 Xem số dư"}],
            [{"text": "📜 Lịch sử lệnh"}, {"text": "📋 Danh mục"}],
            [{"text": "❓ Trợ giúp"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    payload = {
        "chat_id": chat_id,
        "text": "👋 Xin chào! Tôi là VN-WaveTrader Bot.\n\nHãy chọn một trong các chức năng dưới đây từ menu để tương tác:",
        "reply_markup": menu_markup
    }
    try:
        import requests
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi gửi menu: {e}")

def handle_forecast_request(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": "⏳ *Hệ thống bắt đầu quét dữ liệu & phân tích thị trường VN30...*\n\n_Vui lòng đợi khoảng 30-60 giây để chạy tính năng chỉ báo kỹ thuật, tối ưu danh mục HRP và nhận định chuyên sâu từ AI Gemini..._",
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi gửi thông báo bắt đầu dự báo: {e}")
        
    try:
        from src.notifier import send_daily_report_to_telegram
        success = send_daily_report_to_telegram(chat_id=str(chat_id))
        if not success:
            import requests
            requests.post(url, json={
                "chat_id": chat_id,
                "text": "❌ *Lỗi:* Không thể chạy phân tích dữ liệu hoặc gửi báo cáo. Vui lòng kiểm tra log trên server.",
                "parse_mode": "Markdown"
            }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi khi chạy dự báo: {e}")
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": f"❌ *Lỗi hệ thống khi phân tích:* {str(e)}",
            "parse_mode": "Markdown"
        }, timeout=10)

def handle_balance_request(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": "⏳ *Đang kết nối database và truy vấn bảng giá trực tiếp...*",
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi gửi thông báo số dư: {e}")
        
    try:
        import requests
        from src.paper_trader import load_portfolio
        from vnstock import Market
        
        portfolio = load_portfolio()
        cash = portfolio.get("cash", 100000000.0)
        positions = portfolio.get("positions", [])
        
        if not positions:
            msg = f"💰 *BÁO CÁO SỐ DƯ VÍ ẢO* 💰\n" \
                  f"───────────────────\n" \
                  f"- 💵 *Tiền mặt:* **{cash:,.0f}đ**\n" \
                  f"- 📂 *Danh mục:* Không có vị thế nào đang nắm giữ.\n" \
                  f"- 📈 *Tổng tài sản (Net Worth):* **{cash:,.0f}đ**"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
            
        m = Market()
        total_buy_val = 0.0
        total_curr_val = 0.0
        pos_list = []
        
        for pos in positions:
            sym = pos["symbol"]
            qty = pos["quantity"]
            buy_price = pos["buy_price"]
            
            curr_price = buy_price
            try:
                df_quote = m.equity(sym).quote()
                if not df_quote.empty:
                    p = df_quote.iloc[0]["close_price"]
                    if p > 0:
                        if p > 1000:
                            p /= 1000.0
                        curr_price = p
            except Exception as quote_e:
                logging.error(f"Lỗi lấy giá {sym}: {quote_e}")
                
            buy_val_vnd = qty * buy_price * 1000
            curr_val_vnd = qty * curr_price * 1000
            pnl_vnd = curr_val_vnd - buy_val_vnd
            pnl_pct = ((curr_price - buy_price) / buy_price) * 100
            
            total_buy_val += buy_val_vnd
            total_curr_val += curr_val_vnd
            
            pos_info = f"📌 **{sym}**\n" \
                       f"  - Số lượng: {qty:,} cp\n" \
                       f"  - Giá mua: {buy_price:.2f} | Hiện tại: {curr_price:.2f}\n" \
                       f"  - Giá trị mua: {buy_val_vnd:,.0f}đ\n" \
                       f"  - Định giá: {curr_val_vnd:,.0f}đ\n" \
                       f"  - Lãi/Lỗ: *{pnl_vnd:+,.0f}đ* ({pnl_pct:+.2f}%)"
            pos_list.append(pos_info)
            time.sleep(1.0)
            
        net_worth = cash + total_curr_val
        total_pnl_vnd = total_curr_val - total_buy_val
        total_pnl_pct = (total_pnl_vnd / total_buy_val * 100) if total_buy_val > 0 else 0.0
        
        msg = f"💰 *BÁO CÁO SỐ DƯ & DANH MỤC VÍ ẢO* 💰\n" \
              f"───────────────────\n" \
              f"- 💵 *Tiền mặt:* **{cash:,.0f}đ**\n" \
              f"- 📈 *Tổng tài sản (Net Worth):* **{net_worth:,.0f}đ**\n" \
              f"- 📊 *Hiệu suất danh mục:* **{total_pnl_vnd:+,.0f}đ** ({total_pnl_pct:+.2f}%)\n" \
              f"───────────────────\n" \
              f"📂 *Chi tiết các vị thế đang nắm giữ:*\n\n" + "\n\n".join(pos_list)
              
        requests.post(url, json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
        
    except Exception as e:
        logging.error(f"[BOT] Lỗi khi xử lý số dư: {e}")
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": f"❌ *Lỗi hệ thống khi tải số dư:* {str(e)}",
            "parse_mode": "Markdown"
        }, timeout=10)

def handle_history_request(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import requests
        from src.paper_trader import load_portfolio
        portfolio = load_portfolio()
        history = portfolio.get("history", [])
        
        if not history:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": "📜 *LỊCH SỬ GIAO DỊCH VÍ ẢO* 📜\n───────────────────\nChưa ghi nhận giao dịch đóng nào trong lịch sử.",
                "parse_mode": "Markdown"
            }, timeout=10)
            return
            
        recent_history = history[-10:]
        recent_history.reverse()
        
        hist_list = []
        for i, h in enumerate(recent_history, 1):
            pnl_sign = "+" if h["pnl_amount"] > 0 else ""
            pnl_percent_str = f"{pnl_sign}{h['pnl_percent']:.2f}%"
            pnl_amount_str = f"{pnl_sign}{h['pnl_amount']:,.0f}đ"
            
            entry = f"{i}. **{h['symbol']}** ({h['reason']})\n" \
                    f"  - Mua: {h['buy_price']:.2f} ({h['buy_date'].split()[0]})\n" \
                    f"  - Bán: {h['sell_price']:.2f} ({h['sell_date'].split()[0]})\n" \
                    f"  - SL: {h['quantity']:,} cp\n" \
                    f"  - Lãi/Lỗ: *{pnl_amount_str}* ({pnl_percent_str})"
            hist_list.append(entry)
            
        msg = f"📜 *LỊCH SỬ GIAO DỊCH VÍ ẢO* 📜\n" \
              f"_(Hiển thị tối đa 10 giao dịch gần nhất, mới nhất xếp trước)_\n" \
              f"───────────────────\n\n" + "\n\n".join(hist_list)
              
        requests.post(url, json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi khi truy vấn lịch sử giao dịch: {e}")
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": f"❌ *Lỗi hệ thống khi tải lịch sử:* {str(e)}",
            "parse_mode": "Markdown"
        }, timeout=10)

def handle_watchlist_request(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": "⏳ *Đang tải bảng giá danh mục theo dõi...*",
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi gửi thông báo danh mục theo dõi: {e}")
        
    try:
        import requests
        from config import DEFAULT_WATCHLIST
        from vnstock import Market
        m = Market()
        
        watch_list = []
        for sym in DEFAULT_WATCHLIST:
            try:
                df_quote = m.equity(sym).quote()
                if not df_quote.empty:
                    p = df_quote.iloc[0]["close_price"]
                    chg = df_quote.iloc[0]["percent_change"]
                    if p > 0:
                        if p > 1000:
                            p /= 1000.0
                        watch_list.append(f"📌 **{sym}**: Giá **{p:.2f}** ({chg:+.2f}%)")
                    else:
                        watch_list.append(f"📌 **{sym}**: Giá --")
                else:
                    watch_list.append(f"📌 **{sym}**: Không có dữ liệu")
            except Exception as e:
                logging.error(f"Lỗi lấy giá cho {sym} trong watchlist: {e}")
                watch_list.append(f"📌 **{sym}**: Lỗi tải giá")
            time.sleep(1.0)
            
        msg = f"📋 *DANH MỤC CỔ PHIẾU THEO DÕI* 📋\n" \
              f"───────────────────\n\n" + "\n".join(watch_list) + \
              f"\n\n💡 _Dùng tính năng '🔮 Xem dự báo' để phân tích kỹ thuật và quét tín hiệu Mua/Bán chi tiết cho danh mục này._"
              
        requests.post(url, json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi khi tải danh mục theo dõi: {e}")
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": f"❌ *Lỗi hệ thống khi tải danh mục theo dõi:* {str(e)}",
            "parse_mode": "Markdown"
        }, timeout=10)

def handle_help_request(token: str, chat_id: int):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    help_text = f"❓ *HƯỚNG DẪN SỬ DỤNG VN-WAVETRADER BOT* ❓\n" \
                f"───────────────────\n" \
                f"Hệ thống cung cấp các nút tương tác nhanh ở bàn phím điện thoại của bạn:\n\n" \
                f"🔮 *Xem dự báo:* Phân tích độ rộng thị trường VN30, tính toán các tín hiệu Mua/Bán ngắn hạn cho watchlist của bạn, chạy thuật toán tối ưu hóa tỷ trọng vốn HRP, và gửi nhận định chuyên sâu từ AI Gemini.\n\n" \
                f"💰 *Xem số dư:* Xem tiền mặt còn lại trong tài khoản ví ảo, thống kê tất cả các vị thế đang nắm giữ, định giá tài sản thời gian thực và tổng lợi nhuận ngắn hạn.\n\n" \
                f"📜 *Lịch sử lệnh:* Xem lại danh sách 10 giao dịch đã đóng gần nhất trong ví ảo cùng hiệu suất và lý do đóng vị thế (Cắt lỗ động ATR, Chốt lời TP1/TP2, Bán tay...).\n\n" \
                f"📋 *Danh mục:* Xem danh sách cổ phiếu đang theo dõi cùng với giá khớp hiện tại.\n\n" \
                f"💡 *Mẹo:* Khi hệ thống gửi tín hiệu MUA, bạn có thể click vào nút **`💼 Xác nhận Mua & Giám sát [Mã]`** đính kèm dưới tin nhắn. Hệ thống sẽ tự động thêm vị thế ảo vào ví và bắt đầu chạy giám sát cắt lỗ chốt lời thời gian thực cho bạn trong phiên giao dịch!"
                
    try:
        import requests
        requests.post(url, json={
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logging.error(f"[BOT] Lỗi gửi hướng dẫn: {e}")

def register_telegram_commands(token: str):
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "menu", "description": "Mở bàn phím menu tương tác nhanh"},
        {"command": "forecast", "description": "Xem dự báo & phân tích thị trường EOD"},
        {"command": "balance", "description": "Xem số dư & danh mục ví ảo"},
        {"command": "history", "description": "Xem lịch sử lệnh ví ảo"},
        {"command": "watchlist", "description": "Xem danh mục cổ phiếu theo dõi"},
        {"command": "help", "description": "Hướng dẫn sử dụng"}
    ]
    try:
        import requests
        r = requests.post(url, json={"commands": commands}, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            logging.info("[BOT] Đã đăng ký danh sách lệnh Command Menu với Telegram thành công.")
        else:
            logging.error(f"[BOT] Lỗi đăng ký Command Menu: {r.text}")
    except Exception as e:
        logging.error(f"[BOT] Không thể kết nối đăng ký Command Menu: {e}")

def telegram_polling_loop():
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logging.warning("[BOT] TELEGRAM_BOT_TOKEN chưa được cấu hình. Luồng phản hồi tương tác bị tắt.")
        return
        
    logging.info("[BOT] Khởi động luồng lắng nghe tương tác Telegram Bot thành công.")
    register_telegram_commands(token)
    
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
                logging.warning(f"[BOT] Telegram API trả về lỗi: {res.get('description')}")
                time.sleep(5)
                continue
                
            for update in res.get("result", []):
                offset = update["update_id"] + 1
                
                # 1. Xử lý tin nhắn văn bản (commands & menu)
                if "message" in update:
                    msg = update["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "").strip()
                    
                    # Xác thực chat ID từ .env
                    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
                    if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
                        logging.warning(f"[BOT] Nhận tin nhắn từ Chat ID lạ: {chat_id}. Bỏ qua để bảo mật.")
                        continue
                        
                    if text.startswith("/start") or text.startswith("/menu") or text.lower() == "menu":
                        send_telegram_menu(token, chat_id)
                    elif text == "🔮 Xem dự báo" or text.startswith("/forecast"):
                        threading.Thread(target=handle_forecast_request, args=(token, chat_id), daemon=True).start()
                    elif text == "💰 Xem số dư" or text.startswith("/balance"):
                        threading.Thread(target=handle_balance_request, args=(token, chat_id), daemon=True).start()
                    elif text == "📜 Lịch sử lệnh" or text.startswith("/history"):
                        threading.Thread(target=handle_history_request, args=(token, chat_id), daemon=True).start()
                    elif text == "📋 Danh mục" or text.startswith("/watchlist"):
                        threading.Thread(target=handle_watchlist_request, args=(token, chat_id), daemon=True).start()
                    elif text == "❓ Trợ giúp" or text.startswith("/help"):
                        threading.Thread(target=handle_help_request, args=(token, chat_id), daemon=True).start()
                        
                # 2. Xử lý callback từ nút bấm
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cb_data = cb.get("data", "")
                    cb_id = cb["id"]
                    chat_id = cb["message"]["chat"]["id"]
                    
                    # Xác thực chat ID
                    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
                    if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
                        logging.warning(f"[BOT] Nhận callback từ Chat ID lạ: {chat_id}. Bỏ qua để bảo mật.")
                        continue
                        
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

if __name__ == "__main__":
    try:
        # 1. Khởi chạy luồng Telegram Bot Polling lắng nghe tương tác
        bot_thread = threading.Thread(target=telegram_polling_loop, daemon=True)
        bot_thread.start()
        
        # 2. Chạy luồng giám sát chính
        run_portfolio_monitor()
    except KeyboardInterrupt:
        logging.info("Tiến trình giám sát danh mục đã bị dừng bởi người dùng.")
