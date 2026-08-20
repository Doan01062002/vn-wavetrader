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
            [{"text": "📊 Phân tích mã"}, {"text": "❓ Trợ giúp"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    _send(
        token, chat_id,
        "👋 Xin chào! Tôi là *VN-WaveTrader Bot* v2.0\n\n"
        "🆕 *Tính năng mới:*\n"
        "• Phân tích chi tiết từng mã: `/detail FPT`\n"
        "• Stochastic + ADX trong scoring\n"
        "• Báo cáo tự động 08:30 / 14:45 / 16:30\n"
        "• AI tóm tắt kết quả quét\n\n"
        "Hãy chọn chức năng từ menu bên dưới:",
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


def handle_market_request(token: str, chat_id: int) -> None:
    """Xử lý yêu cầu xem độ rộng thị trường và sóng ngành."""
    _send(token, chat_id, "⏳ *Đang quét độ rộng thị trường VN30 và 7 nhóm ngành chính...*")
    try:
        from src.data_fetcher import get_vn30_symbols, get_stock_ohlcv
        from src.indicators import calculate_indicators
        from src.notifier import SECTORS

        vn30 = get_vn30_symbols()
        uptrend_count = 0
        total_count = 0

        for sym in vn30:
            df = get_stock_ohlcv(sym, length=50)
            if not df.empty:
                df = calculate_indicators(df, symbol=sym)
                if 'ema_short' in df.columns and len(df) > 0:
                    if df['close'].iloc[-1] > df['ema_short'].iloc[-1]:
                        uptrend_count += 1
                    total_count += 1

        breadth = (uptrend_count / total_count * 100) if total_count > 0 else 50.0

        if breadth >= 60.0:
            regime = "🟢 *THỊ TRƯỜNG TÍCH CỰC (Uptrend mạnh)*"
        elif breadth >= 40.0:
            regime = "🟡 *THỊ TRƯỜNG PHÂN HÓA (Sideways)*"
        else:
            regime = "🔴 *THỊ TRƯỜNG RỦI RO (Downtrend / Phòng vệ)*"

        msg = (
            f"📊 *BÁO CÁO ĐỘ RỘNG THỊ TRƯỜNG VN30* 📊\n"
            f"───────────────────\n"
            f"- *Trạng thái:* {regime}\n"
            f"- *Tỷ lệ mã trên EMA20:* **{breadth:.1f}%** ({uptrend_count}/{total_count} mã)\n"
            f"───────────────────\n"
            f"💡 _Khi độ rộng < 40%, hệ thống tự động kích hoạt chế độ phòng vệ rủi ro vĩ mô._"
        )
        _send(token, chat_id, msg)
    except Exception as e:
        logger.error(f"[BOT] Lỗi market breadth: {e}")
        _send(token, chat_id, f"❌ *Lỗi khi quét độ rộng thị trường:* {str(e)[:200]}")


def handle_sentiment_request(token: str, chat_id: int) -> None:
    """Xử lý yêu cầu xem chỉ số tâm lý và tin tức nóng."""
    _send(token, chat_id, "⏳ *Đang phân tích sắc thái tin tức thị trường...*")
    try:
        from src.sentiment_analyzer import analyze_market_sentiment
        sent = analyze_market_sentiment()

        score = float(sent.get("score", 0.0))
        label = sent.get("label", "TRUNG TÍNH (Neutral)")
        bullish_pct = float(sent.get("bullish_pct", 50.0))
        bearish_pct = float(sent.get("bearish_pct", 50.0))

        if score >= 0.15:
            icon = "🟢"
        elif score <= -0.15:
            icon = "🔴"
        else:
            icon = "⚪"

        msg = (
            f"📰 *CHỈ SỐ TÂM LÝ THỊ TRƯỜNG* 📰\n"
            f"───────────────────\n"
            f"- *Tâm lý vĩ mô:* {icon} **{label}**\n"
            f"- *Điểm sắc thái:* **{score:+.2f}**\n"
            f"- *Tỷ lệ tin tức:* 🐂 {bullish_pct:.0f}% Tích cực | 🐻 {bearish_pct:.0f}% Tiêu cực\n"
            f"───────────────────\n"
        )

        details = sent.get("details", [])
        if details:
            msg += "*Tin tức thị trường mới nhất:*\n"
            for item in details[:5]:
                sc = float(item.get("score", 0.0))
                tag = "🟢" if sc >= 0.15 else ("🔴" if sc <= -0.15 else "⚪")
                title = item.get("title", "").strip()
                msg += f"  {tag} {title}\n"

        _send(token, chat_id, msg)
    except Exception as e:
        logger.error(f"[BOT] Lỗi sentiment: {e}")
        _send(token, chat_id, f"❌ *Lỗi khi phân tích tâm lý:* {str(e)[:200]}")


def handle_help_request(token: str, chat_id: int) -> None:
    help_text = (
        "❓ *HƯỚNG DẪN SỬ DỤNG VN-WAVETRADER BOT* ❓\n"
        "───────────────────\n"
        "🔮 `/scan` hoặc `/forecast`: Quét toàn diện VN30, lọc tín hiệu Mua/Bán & nhận định AI.\n\n"
        "💰 `/balance` hoặc `/portfolio`: Xem số dư tiền mặt, định giá ví ảo và vị thế mở.\n\n"
        "📊 `/detail <MÃ>`: Phân tích kỹ thuật chi tiết từng mã (Ví dụ: `/detail FPT`).\n\n"
        "📈 `/chart <MÃ>`: Xuất biểu đồ kỹ thuật Dark Theme (Ví dụ: `/chart HPG`).\n\n"
        "🌐 `/market`: Kiểm tra độ rộng thị trường VN30 & trạng thái sóng ngành.\n\n"
        "📰 `/sentiment`: Xem chỉ số tâm lý đám đông (Fear & Greed Index) & tin tức.\n\n"
        "📜 `/history`: Xem lịch sử các giao dịch đã đóng của ví ảo.\n\n"
        "📋 `/watchlist`: Bảng giá theo dõi nhanh danh mục cổ phiếu cốt lõi.\n\n"
        "💡 *Mẹo:* Khi có tín hiệu MUA, bấm nút **`💼 Xác nhận Mua & Giám sát`** để bot tự động quản trị SL/TP và chặn lãi động cho bạn!"
    )
    _send(token, chat_id, help_text)


def register_telegram_commands(token: str) -> None:
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "menu", "description": "Mở bàn phím tương tác nhanh"},
        {"command": "scan", "description": "Quét tín hiệu lướt sóng VN30 tức thì"},
        {"command": "forecast", "description": "Xem báo cáo phân tích toàn diện EOD"},
        {"command": "portfolio", "description": "Xem số dư & danh mục ví ảo"},
        {"command": "detail", "description": "Phân tích kỹ thuật chi tiết mã (vd: /detail FPT)"},
        {"command": "chart", "description": "Xuất biểu đồ nến Dark Theme (vd: /chart FPT)"},
        {"command": "market", "description": "Xem độ rộng thị trường VN30"},
        {"command": "sentiment", "description": "Xem tâm lý đám đông & tin tức nóng"},
        {"command": "history", "description": "Xem lịch sử giao dịch ví ảo"},
        {"command": "watchlist", "description": "Xem bảng giá danh mục theo dõi"},
        {"command": "help", "description": "Xem hướng dẫn sử dụng"}
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


def _handle_detail_callback(token: str, chat_id: int, symbol: str, cb_id: str = None) -> None:
    """Xử lý callback chi tiết kỹ thuật cho một mã cổ phiếu."""
    try:
        from src.indicators import calculate_indicators, check_swing_signals, find_support_resistance

        _send(token, chat_id, f"⏳ Đang phân tích chi tiết **{symbol}**...")

        df = get_stock_ohlcv(symbol, length=120)
        if df.empty:
            _send(token, chat_id, f"❌ Không tải được dữ liệu cho mã **{symbol}**")
            return

        df = calculate_indicators(df, symbol=symbol)
        signals = check_swing_signals(df, symbol=symbol)
        levels = find_support_resistance(df)

        last = df.iloc[-1]
        msg = (
            f"📊 *PHÂN TÍCH CHI TIẾT: {symbol}*\n\n"
            f"💹 *Giá hiện tại:* {last['close']:.2f}\n"
            f"📈 *Xu hướng:* {signals['trend']}\n"
            f"🎯 *Trạng thái:* {signals['status']} (Score: {signals['score']:.1f})\n"
            f"───────────────────\n"
            f"*Chỉ báo kỹ thuật:*\n"
            f"  • RSI: {last['rsi']:.1f}\n"
            f"  • MACD: {last['macd']:.3f} (Signal: {last['macd_signal']:.3f})\n"
            f"  • Stoch %K: {last.get('stoch_k', 0):.1f} | %D: {last.get('stoch_d', 0):.1f}\n"
            f"  • ADX: {last.get('adx', 0):.1f} (+DI: {last.get('adx_pos', 0):.1f} / -DI: {last.get('adx_neg', 0):.1f})\n"
            f"  • BB %B: {last['bb_percent']:.2f}\n"
            f"  • SuperTrend: {'🟢 TĂNG' if last.get('supertrend_dir', 0) == 1 else '🔴 GIẢM'}\n"
            f"  • ATR: {last['atr']:.2f}\n"
            f"───────────────────\n"
            f"*Hỗ trợ / Kháng cự:*\n"
            f"  🟢 Hỗ trợ: {levels.get('support', 'N/A')}\n"
            f"  🔴 Kháng cự: {levels.get('resistance', 'N/A')}\n"
            f"───────────────────\n"
            f"*Chi tiết tín hiệu:*\n"
        )

        for detail in signals.get("details", [])[:10]:
            msg += f"  • {detail}\n"

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "📈 Phân tích CANSLIM", "callback_data": f"canslim_{symbol}"},
                    {"text": f"💼 Mua ảo {symbol}", "callback_data": f"buy_{symbol}_{last['close']:.2f}"}
                ]
            ]
        }

        _send(token, chat_id, msg, reply_markup=reply_markup)

        # Gửi biểu đồ candlestick
        try:
            from src.chart_generator import generate_chart, send_chart_to_telegram
            chart_path = generate_chart(df, symbol, signals)
            if chart_path:
                send_chart_to_telegram(
                    chart_path,
                    caption=f"📊 Biểu đồ kỹ thuật *{symbol}* — {signals['status']} (Score: {signals['score']:.1f})",
                    chat_id=str(chat_id)
                )
        except Exception as chart_e:
            logger.error(f"[BOT] Lỗi tạo biểu đồ {symbol}: {chart_e}")

    except Exception as e:
        logger.error(f"[BOT] Lỗi detail {symbol}: {e}")
        _send(token, chat_id, f"❌ Lỗi phân tích {symbol}: {str(e)[:200]}")

    if cb_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": cb_id, "text": f"Phân tích {symbol}"},
                timeout=5
            )
        except Exception:
            pass


def _handle_chart_command(token: str, chat_id: int, symbol: str) -> None:
    """Xử lý lệnh /chart <MÃ> tạo và gửi biểu đồ trực tiếp."""
    try:
        from src.indicators import calculate_indicators, check_swing_signals
        from src.chart_generator import generate_chart, send_chart_to_telegram

        _send(token, chat_id, f"⏳ Đang vẽ biểu đồ kỹ thuật Dark Theme cho **{symbol}**...")
        df = get_stock_ohlcv(symbol, length=120)
        if df.empty:
            _send(token, chat_id, f"❌ Không tải được dữ liệu nến cho mã **{symbol}**")
            return

        df = calculate_indicators(df, symbol=symbol)
        signals = check_swing_signals(df, symbol=symbol)
        chart_path = generate_chart(df, symbol, signals)

        if chart_path:
            send_chart_to_telegram(
                chart_path,
                caption=f"📊 Biểu đồ kỹ thuật *{symbol}* | Giá: {df['close'].iloc[-1]:.2f} | Trạng thái: {signals['status']}",
                chat_id=str(chat_id)
            )
        else:
            _send(token, chat_id, f"❌ Không thể tạo file ảnh biểu đồ cho {symbol}")
    except Exception as e:
        logger.error(f"[BOT] Lỗi lệnh /chart {symbol}: {e}")
        _send(token, chat_id, f"❌ Lỗi tạo biểu đồ {symbol}: {str(e)[:200]}")


def _handle_canslim_callback(token: str, chat_id: int, symbol: str, cb_id: str = None) -> None:
    """Xử lý callback phân tích CANSLIM cơ bản."""
    try:
        from src.fundamental_screener import calculate_canslim_score

        _send(token, chat_id, f"⏳ Đang tính điểm CANSLIM cho **{symbol}**...")
        result = calculate_canslim_score(symbol)

        msg = (
            f"📈 *PHÂN TÍCH CANSLIM: {symbol}*\n\n"
            f"🏆 *Tổng điểm:* **{result['total_score']}/100** — {result['rating']}\n"
            f"───────────────────\n"
        )

        for key, data in result.get("details", {}).items():
            score = data.get("score", 0)
            desc = data.get("desc", "")
            msg += f"  {key}: {score}/20 — {desc}\n"

        metrics = result.get("financial_metrics", {})
        if metrics:
            msg += (
                f"\n*Chỉ số tài chính:*\n"
                f"  • ROE: {metrics.get('roe', 0):.1f}%\n"
                f"  • P/E: {metrics.get('pe', 0):.1f}\n"
                f"  • P/B: {metrics.get('pb', 0):.1f}\n"
                f"  • Net Margin: {metrics.get('net_margin', 0):.1f}%\n"
            )

        _send(token, chat_id, msg)
    except Exception as e:
        logger.error(f"[BOT] Lỗi CANSLIM {symbol}: {e}")
        _send(token, chat_id, f"❌ Lỗi tính CANSLIM {symbol}: {str(e)[:200]}")

    if cb_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": cb_id, "text": f"CANSLIM {symbol}"},
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
                    elif text in ("🔮 Xem dự báo", "/forecast", "/scan") or text.startswith("/forecast") or text.startswith("/scan"):
                        threading.Thread(target=handle_forecast_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("💰 Xem số dư", "/balance", "/portfolio", "/wallet") or text.startswith("/balance") or text.startswith("/portfolio"):
                        threading.Thread(target=handle_balance_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("📜 Lịch sử lệnh", "/history") or text.startswith("/history"):
                        threading.Thread(target=handle_history_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("📋 Danh mục", "/watchlist") or text.startswith("/watchlist"):
                        threading.Thread(target=handle_watchlist_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("🌐 Độ rộng TT", "/market", "/breadth") or text.startswith("/market"):
                        threading.Thread(target=handle_market_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("📰 Tin tức", "/sentiment", "/news") or text.startswith("/sentiment"):
                        threading.Thread(target=handle_sentiment_request, args=(token, chat_id), daemon=True).start()
                    elif text in ("❓ Trợ giúp", "/help") or text.startswith("/help"):
                        threading.Thread(target=handle_help_request, args=(token, chat_id), daemon=True).start()
                    elif text == "📊 Phân tích mã":
                        _send(
                            token, chat_id,
                            "📊 *PHÂN TÍCH KỸ THUẬT & BIỂU ĐỒ*\n\n"
                            "Hãy gửi tin nhắn theo cú pháp:\n"
                            "• `/detail <MÃ>`: Xem phân tích chi tiết & chỉ báo\n"
                            "• `/chart <MÃ>`: Xuất biểu đồ nến Dark Theme\n\n"
                            "*Ví dụ:* `/detail FPT` hoặc `/chart HPG`"
                        )
                    elif text.startswith("/chart ") or text.startswith("📈 "):
                        parts = text.split()
                        if len(parts) >= 2:
                            sym = parts[1].upper()
                            threading.Thread(
                                target=_handle_chart_command,
                                args=(token, chat_id, sym),
                                daemon=True
                            ).start()
                        else:
                            _send(token, chat_id, "📈 Cú pháp: `/chart FPT` — Xuất biểu đồ nến kỹ thuật mã FPT")
                    elif text.startswith("/detail ") or (text.startswith("📊 ") and len(text.split()) >= 2):
                        parts = text.split()
                        if len(parts) >= 2:
                            sym = parts[1].upper()
                            threading.Thread(
                                target=_handle_detail_callback,
                                args=(token, chat_id, sym, None),
                                daemon=True
                            ).start()
                        else:
                            _send(token, chat_id, "📊 Cú pháp: `/detail FPT` — Xem phân tích chi tiết mã cổ phiếu")

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
                    elif cb_data.startswith("detail_"):
                        symbol = cb_data.replace("detail_", "")
                        threading.Thread(
                            target=_handle_detail_callback,
                            args=(token, chat_id, symbol, cb_id),
                            daemon=True
                        ).start()
                    elif cb_data.startswith("canslim_"):
                        symbol = cb_data.replace("canslim_", "")
                        threading.Thread(
                            target=_handle_canslim_callback,
                            args=(token, chat_id, symbol, cb_id),
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

