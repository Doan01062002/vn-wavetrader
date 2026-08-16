"""
Module Telegram Bot — xử lý tất cả tương tác với người dùng qua Telegram.
Chịu trách nhiệm:
- Polling loop (getUpdates)
- Xử lý text commands và callback buttons
- Hiển thị menu, số dư, lịch sử, danh mục

Cải tiến v2:
- Tất cả import đặt đầu file (không import trong hàm)
- is_forecast_running dùng threading.Lock chuẩn
- Rate limiting qua telegram_limiter
- Graceful stop khi nhận signal dừng
"""
import os
import sys
import time
import logging
import threading
import requests
from typing import Optional

from vnstock import Market

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.paper_trader import load_portfolio, buy_stock, get_atr_for_symbol
from src.notifier import send_daily_report_to_telegram, send_telegram_message
from src.data_fetcher import get_stock_ohlcv
from src.rate_limiter import telegram_limiter
from config import DEFAULT_WATCHLIST

logger = logging.getLogger(__name__)

# Cờ kiểm soát vòng lặp polling
_polling_active = True

# Lock chống spam lệnh dự báo đồng thời
_is_forecast_running = False
_forecast_lock = threading.Lock()


def _send(token: str, chat_id: int, text: str, parse_mode: str = "Markdown", reply_markup: dict = None) -> bool:
    """Helper gửi tin nhắn Telegram với rate limit."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        with telegram_limiter:
            resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"[BOT] Lỗi gửi tin nhắn: {e}")
        return False


def send_telegram_menu(token: str, chat_id: int) -> None:
    menu_markup = {
        "keyboard": [
            [{"text": "🔮 Xem dự báo"}, {"text": "💰 Xem số dư"}],
            [{"text": "📜 Lịch sử lệnh"}, {"text": "📋 Danh mục"}],
            [{"text": "❓ Trợ giúp"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    _send(
        token, chat_id,
        "👋 Xin chào! Tôi là VN-WaveTrader Bot.\n\nHãy chọn một trong các chức năng dưới đây từ menu để tương tác:",
        reply_markup=menu_markup
    )


def handle_forecast_request(token: str, chat_id: int) -> None:
    global _is_forecast_running
    with _forecast_lock:
        if _is_forecast_running:
            _send(token, chat_id,
                  "⚠️ *Hệ thống đang thực hiện một phân tích khác.*\n\nVui lòng đợi khoảng 1-2 phút cho đến khi có kết quả.")
            return
        _is_forecast_running = True

    try:
        _send(token, chat_id,
              "⏳ *Hệ thống bắt đầu quét dữ liệu & phân tích thị trường VN30...*\n\n"
              "_Vui lòng đợi khoảng 30-60 giây..._")
        success = send_daily_report_to_telegram(chat_id=str(chat_id))
        if not success:
            _send(token, chat_id, "❌ *Lỗi:* Không thể chạy phân tích. Vui lòng kiểm tra log trên server.")
    except Exception as e:
        logger.error(f"[BOT] Lỗi khi chạy dự báo: {e}")
        _send(token, chat_id, f"❌ *Lỗi hệ thống khi phân tích:* {str(e)}")
    finally:
        with _forecast_lock:
            _is_forecast_running = False


def handle_balance_request(token: str, chat_id: int) -> None:
    _send(token, chat_id, "⏳ *Đang kết nối database và truy vấn bảng giá trực tiếp...*")

    try:
        portfolio = load_portfolio()
        cash = portfolio.get("cash", 100_000_000.0)
        positions = portfolio.get("positions", [])

        if not positions:
            _send(token, chat_id,
                  f"💰 *BÁO CÁO SỐ DƯ VÍ ẢO* 💰\n"
                  f"───────────────────\n"
                  f"- 💵 *Tiền mặt:* **{cash:,.0f}đ**\n"
                  f"- 📂 *Danh mục:* Không có vị thế nào.\n"
                  f"- 📈 *Tổng tài sản:* **{cash:,.0f}đ**")
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
                    raw_p = df_quote.iloc[0]["close_price"]
                    if raw_p > 0:
                        from src.realtime_monitor import _normalize_price
                        curr_price = _normalize_price(raw_p, sym)
            except Exception as quote_e:
                logger.error(f"Lỗi lấy giá {sym}: {quote_e}")

            buy_val_vnd = qty * buy_price * 1000
            curr_val_vnd = qty * curr_price * 1000
            pnl_vnd = curr_val_vnd - buy_val_vnd
            pnl_pct = ((curr_price - buy_price) / buy_price) * 100

            total_buy_val += buy_val_vnd
            total_curr_val += curr_val_vnd

            pos_list.append(
                f"📌 **{sym}**\n"
                f"  - Số lượng: {qty:,} cp\n"
                f"  - Giá mua: {buy_price:.2f} | Hiện tại: {curr_price:.2f}\n"
                f"  - Định giá: {curr_val_vnd:,.0f}đ\n"
                f"  - Lãi/Lỗ: *{pnl_vnd:+,.0f}đ* ({pnl_pct:+.2f}%)"
            )
            time.sleep(0.5)

        net_worth = cash + total_curr_val
        total_pnl_vnd = total_curr_val - total_buy_val
        total_pnl_pct = (total_pnl_vnd / total_buy_val * 100) if total_buy_val > 0 else 0.0

        msg = (
            f"💰 *BÁO CÁO SỐ DƯ & DANH MỤC VÍ ẢO* 💰\n"
            f"───────────────────\n"
            f"- 💵 *Tiền mặt:* **{cash:,.0f}đ**\n"
            f"- 📈 *Tổng tài sản:* **{net_worth:,.0f}đ**\n"
            f"- 📊 *Hiệu suất:* **{total_pnl_vnd:+,.0f}đ** ({total_pnl_pct:+.2f}%)\n"
            f"───────────────────\n"
            f"📂 *Chi tiết vị thế:*\n\n" + "\n\n".join(pos_list)
        )
        _send(token, chat_id, msg)

    except Exception as e:
        logger.error(f"[BOT] Lỗi khi xử lý số dư: {e}")
        _send(token, chat_id, f"❌ *Lỗi hệ thống khi tải số dư:* {str(e)}")


def handle_history_request(token: str, chat_id: int) -> None:
    try:
        portfolio = load_portfolio()
        history = portfolio.get("history", [])

        if not history:
            _send(token, chat_id,
                  "📜 *LỊCH SỬ GIAO DỊCH VÍ ẢO* 📜\n───────────────────\nChưa ghi nhận giao dịch nào.")
            return

        recent = list(reversed(history[-10:]))
        hist_list = []
        for i, h in enumerate(recent, 1):
            pnl_sign = "+" if h["pnl_amount"] > 0 else ""
            hist_list.append(
                f"{i}. **{h['symbol']}** ({h['reason']})\n"
                f"  - Mua: {h['buy_price']:.2f} ({h['buy_date'].split()[0]})\n"
                f"  - Bán: {h['sell_price']:.2f} ({h['sell_date'].split()[0]})\n"
                f"  - SL: {h['quantity']:,} cp | Lãi/Lỗ: *{pnl_sign}{h['pnl_amount']:,.0f}đ* ({pnl_sign}{h['pnl_percent']:.2f}%)"
            )

        msg = (
            "📜 *LỊCH SỬ GIAO DỊCH VÍ ẢO* 📜\n"
            "_(Tối đa 10 giao dịch gần nhất)_\n"
            "───────────────────\n\n" + "\n\n".join(hist_list)
        )
        _send(token, chat_id, msg)
    except Exception as e:
        logger.error(f"[BOT] Lỗi lịch sử: {e}")
        _send(token, chat_id, f"❌ *Lỗi khi tải lịch sử:* {str(e)}")


def handle_watchlist_request(token: str, chat_id: int) -> None:
    _send(token, chat_id, "⏳ *Đang tải bảng giá danh mục theo dõi...*")
    try:
        watch_list = []
        for sym in DEFAULT_WATCHLIST:
            try:
                df = get_stock_ohlcv(sym, length=120)
                if not df.empty and len(df) >= 2:
                    p = df['close'].iloc[-1]
                    prev_p = df['close'].iloc[-2]
                    chg = ((p - prev_p) / prev_p) * 100
                    watch_list.append(f"📌 **{sym}**: Giá **{p:.2f}** ({chg:+.2f}%)")
                else:
                    watch_list.append(f"📌 **{sym}**: Không có dữ liệu")
            except Exception as sym_e:
                logger.error(f"Lỗi lấy giá {sym}: {sym_e}")
                watch_list.append(f"📌 **{sym}**: Lỗi tải giá")
            time.sleep(0.2)

        msg = (
            "📋 *DANH MỤC CỔ PHIẾU THEO DÕI* 📋\n"
            "───────────────────\n\n" + "\n".join(watch_list) +
            "\n\n💡 _Dùng '🔮 Xem dự báo' để phân tích kỹ thuật chi tiết._"
        )
        _send(token, chat_id, msg)
    except Exception as e:
        logger.error(f"[BOT] Lỗi watchlist: {e}")
        _send(token, chat_id, f"❌ *Lỗi khi tải danh mục:* {str(e)}")


def handle_help_request(token: str, chat_id: int) -> None:
    help_text = (
        "❓ *HƯỚNG DẪN SỬ DỤNG VN-WAVETRADER BOT* ❓\n"
        "───────────────────\n"
        "🔮 *Xem dự báo:* Phân tích VN30, tín hiệu Mua/Bán, tối ưu vốn HRP, nhận định AI.\n\n"
        "💰 *Xem số dư:* Tiền mặt, vị thế đang nắm giữ, định giá real-time, tổng lợi nhuận.\n\n"
        "📜 *Lịch sử lệnh:* 10 giao dịch đã đóng gần nhất kèm hiệu suất.\n\n"
        "📋 *Danh mục:* Danh sách cổ phiếu đang theo dõi với giá hiện tại.\n\n"
        "💡 *Mẹo:* Khi hệ thống gửi tín hiệu MUA, click nút **`💼 Xác nhận Mua & Giám sát [Mã]`** để hệ thống tự động theo dõi dừng lỗ/chốt lời!"
    )
    _send(token, chat_id, help_text)


def register_telegram_commands(token: str) -> None:
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
        r = requests.post(url, json={"commands": commands}, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            logger.info("[BOT] Đã đăng ký Command Menu với Telegram thành công.")
        else:
            logger.error(f"[BOT] Lỗi đăng ký Command Menu: {r.text}")
    except Exception as e:
        logger.error(f"[BOT] Không thể đăng ký Command Menu: {e}")


def _handle_buy_callback(token: str, chat_id: int, cb_data: str, cb_id: str) -> None:
    """Xử lý callback khi người dùng bấm nút 'Xác nhận Mua'."""
    parts = cb_data.split("_")
    if len(parts) < 3:
        return

    symbol = parts[1]
    try:
        buy_price = float(parts[2])
    except ValueError:
        buy_price = 0.0

    # Tính SL/TP động theo ATR
    atr = get_atr_for_symbol(symbol)
    if atr > 0:
        sl = round(buy_price - 2 * atr, 2)
        tp = round(buy_price + 4 * atr, 2)
    else:
        sl = round(buy_price * 0.94, 2)
        tp = round(buy_price * 1.15, 2)

    buy_res = buy_stock(symbol, buy_price, quantity=100, stop_loss=sl, take_profit=tp)

    if buy_res.get("success"):
        reply_msg = (
            f"🟢 *XÁC NHẬN GIÁM SÁT THÀNH CÔNG* 🟢\n\n"
            f"Đã thêm vị thế mua ảo mã **{symbol}** vào danh sách giám sát!\n"
            f"───────────────────\n"
            f"- *Giá mua ghi nhận:* **{buy_price:.2f}**\n"
            f"- *Ngưỡng cắt lỗ (SL):* **{sl:.2f}**\n"
            f"- *Ngưỡng chốt lời (TP):* **{tp:.2f}**\n"
            f"───────────────────\n"
            f"🖥️ Hệ thống sẽ theo dõi giá real-time và gửi cảnh báo tự động!"
        )
    else:
        reply_msg = f"🔴 *XÁC NHẬN THẤT BẠI* 🔴\n\nLý do: {buy_res.get('message')}"

    _send(token, chat_id, reply_msg)

    # Tắt spinner nút bấm
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": cb_id, "text": f"Đã xử lý giám sát {symbol}!"},
            timeout=5
        )
    except Exception:
        pass


def telegram_polling_loop() -> None:
    """Vòng lặp lắng nghe tương tác Telegram Bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logger.warning("[BOT] TELEGRAM_BOT_TOKEN chưa được cấu hình. Luồng tương tác bị tắt.")
        return

    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    logger.info("[BOT] Khởi động luồng lắng nghe Telegram Bot thành công.")
    register_telegram_commands(token)

    offset = 0

    while _polling_active:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=15"
            response = requests.get(url, timeout=20)
            if response.status_code != 200:
                time.sleep(5)
                continue

            res = response.json()
            if not res.get("ok"):
                logger.warning(f"[BOT] Telegram API lỗi: {res.get('description')}")
                time.sleep(5)
                continue

            for update in res.get("result", []):
                offset = update["update_id"] + 1

                # --- Xử lý tin nhắn text ---
                if "message" in update:
                    msg = update["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "").strip()

                    # Xác thực chat ID
                    if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
                        logger.warning(f"[BOT] Tin nhắn từ Chat ID lạ: {chat_id}. Bỏ qua.")
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

                # --- Xử lý callback buttons ---
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    cb_data = cb.get("data", "")
                    cb_id = cb["id"]
                    chat_id = cb["message"]["chat"]["id"]

                    if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
                        logger.warning(f"[BOT] Callback từ Chat ID lạ: {chat_id}. Bỏ qua.")
                        continue

                    if cb_data.startswith("buy_"):
                        threading.Thread(
                            target=_handle_buy_callback,
                            args=(token, chat_id, cb_data, cb_id),
                            daemon=True
                        ).start()

        except Exception as e:
            logger.error(f"[BOT] Lỗi trong vòng lặp polling: {e}")
            time.sleep(5)


def stop_polling() -> None:
    """Dừng vòng lặp polling (graceful shutdown)."""
    global _polling_active
    _polling_active = False
    logger.info("[BOT] Đã nhận tín hiệu dừng polling.")
