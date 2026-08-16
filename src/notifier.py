import os
import requests
import logging
import time
import pandas as pd
from dotenv import load_dotenv
from config import DEFAULT_WATCHLIST

# Nạp hàm từ các module khác
from src.data_fetcher import get_stock_ohlcv, get_stock_news, get_company_ratios, get_vn30_symbols
from src.indicators import check_swing_signals
from src.portfolio import optimize_portfolio
from src.llm_analyzer import analyze_stock_with_ai
from src.rate_limiter import vnstock_limiter


logger = logging.getLogger(__name__)

# Phân nhóm ngành để lọc tín hiệu đồng thuận sóng ngành (Sector Strength Filter)
SECTORS = {
    "BANK": ["VCB", "TCB", "MBB", "ACB", "STB", "CTG", "BID"],
    "STEEL": ["HPG", "HSG", "NKG"],
    "SECURITIES": ["SSI", "VND", "VCI", "HCM"],
    "RETAIL": ["MWG", "FRT", "DGW", "PNJ"],
    "TECH": ["FPT", "CMG", "ELC"],
    "REAL_ESTATE": ["VIC", "VHM", "DXG", "KDH", "NLG"],
    "F&B": ["VNM", "MSN", "SAB"]
}

SYMBOL_TO_SECTOR = {}
for sector, syms in SECTORS.items():
    for s in syms:
        SYMBOL_TO_SECTOR[s] = sector

# Cache sector strength trong mỗi phiên quét (tránh gọi lại API cho từng mã)
_sector_strength_cache: dict = {}  # {sector_name: float (% uptrend)}

load_dotenv()

def send_telegram_message(message: str, reply_markup: dict = None, chat_id: str = None) -> bool:
    """
    Gửi tin nhắn Markdown tới Telegram thông qua Bot API.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or token == "your_telegram_bot_token_here":
        logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN trong file .env")
        return False
    if not chat_id or chat_id == "your_telegram_chat_id_here":
        logger.warning("Chưa cấu hình TELEGRAM_CHAT_ID trong file .env")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    try:
        # Nếu tin nhắn quá dài (giới hạn Telegram là 4096 ký tự), cắt đôi để gửi
        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                requests.post(url, json={**payload, "text": chunk})
            return True
            
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            logger.info("Gửi thông báo Telegram thành công!")
            return True
        else:
            logger.error(f"Lỗi gửi Telegram ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        logger.error(f"Lỗi kết nối gửi Telegram: {e}")
        return False

def _calculate_all_sector_strengths(cached_dfs: dict) -> None:
    """
    Tính sức mạnh tất cả các ngành một lần trước vòng lặp quét chính.
    Lưu vào _sector_strength_cache để tái sử dụng — tránh gọi API lặp cho từng mã.
    """
    from src.indicators import calculate_indicators
    global _sector_strength_cache
    _sector_strength_cache.clear()

    for sector, peers in SECTORS.items():
        uptrend_count = 0
        total_count = 0
        for peer in peers:
            peer_df = cached_dfs.get(peer)
            if peer_df is None:
                with vnstock_limiter:
                    peer_df = get_stock_ohlcv(peer, length=50)
                if not peer_df.empty:
                    peer_df = calculate_indicators(peer_df, symbol=peer)
            if not peer_df.empty and 'ema_short' in peer_df.columns:
                if peer_df['close'].iloc[-1] > peer_df['ema_short'].iloc[-1]:
                    uptrend_count += 1
                total_count += 1

        _sector_strength_cache[sector] = (uptrend_count / total_count * 100) if total_count > 0 else 50.0
        logger.info(f"Sector {sector}: {_sector_strength_cache[sector]:.1f}% uptrend")


def _recalculate_status(score: float) -> str:
    """Tính lại status dựa trên score (dùng sau khi score bị điều chỉnh bởi filter)."""
    if score >= 3:
        return "STRONG BUY"
    elif score >= 1:
        return "BUY"
    elif score > -1:
        return "NEUTRAL"
    elif score > -3:
        return "SELL"
    else:
        return "STRONG SELL"


def _calculate_confidence(signals: dict, volume_confirmed: bool, weekly_ok: bool, sector_ok: bool) -> str:
    """
    Tính mức độ tin cậy (confidence) cho tín hiệu MUA dựa trên các yếu tố xác nhận.
    Trả về: 'CAO', 'TRUNG BÌNH', hoặc 'THẤP'
    """
    if signals.get("status") not in ["BUY", "STRONG BUY"]:
        return "N/A"

    confirmations = sum([volume_confirmed, weekly_ok, sector_ok])
    if confirmations >= 3:
        return "CAO"
    elif confirmations >= 2:
        return "TRUNG BÌNH"
    else:
        return "THẤP"


def send_daily_report_to_telegram(chat_id: str = None) -> bool:
    """
    Quét toàn bộ cổ phiếu theo dõi, chạy tối ưu và gửi báo cáo phân tích lướt sóng về Telegram.
    """
    logger.info("Bắt đầu khởi chạy Báo cáo lướt sóng tự động...")
    
    # 1. Kiểm tra xu hướng thị trường chung qua chỉ số VN30 (chỉ dùng 1 request thay vì 15)
    logger.info("Đang kiểm tra xu hướng thị trường chung qua chỉ số VN30...")
    is_market_risky = False
    market_warning = ""
    breadth = 100.0  # Mặc định tốt
    try:
        df_vn30_index = get_stock_ohlcv("VN30", length=100)
        if not df_vn30_index.empty:
            from src.indicators import calculate_indicators
            df_vn30_index = calculate_indicators(df_vn30_index, symbol="VN30")
            if not df_vn30_index.empty and 'ema_short' in df_vn30_index.columns:
                close_price = df_vn30_index['close'].iloc[-1]
                ema20 = df_vn30_index['ema_short'].iloc[-1]
                logger.info(f"Chỉ số VN30 đóng cửa ở {close_price:.2f} (EMA20: {ema20:.2f})")
                if close_price < ema20:
                    is_market_risky = True
                    breadth = 30.0  # Đặt độ rộng 30% để kích hoạt chế độ phòng vệ
        else:
            logger.warning("Không tải được dữ liệu chỉ số VN30, bỏ qua kiểm tra rủi ro thị trường.")
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra xu hướng chỉ số VN30: {e}")
        
    if is_market_risky:
        market_warning = f"⚠️ *[BẢO VỆ DÒNG VỐN - RỦI RO THỊ TRƯỜNG CHUNG]* ⚠️\n" \
                         f"Chỉ số VN30 hiện tại đang nằm dưới đường xu hướng EMA20. " \
                         f"Hệ thống đã kích hoạt chế độ phòng vệ rủi ro vĩ mô, **vô hiệu hóa các tín hiệu Mua mới** để bảo vệ tài sản của bạn!\n\n"
                         
    # 2. Tải dữ liệu OHLCV cho tất cả mã trước (để tính sector strength)
    scanned_stocks = []
    buy_list = []
    price_dict = {}
    cached_dfs = {}

    logger.info("Đang tải dữ liệu OHLCV cho tất cả mã theo dõi...")
    for sym in DEFAULT_WATCHLIST:
        with vnstock_limiter:
            df = get_stock_ohlcv(sym, length=120)
        if not df.empty:
            from src.indicators import calculate_indicators
            df = calculate_indicators(df, symbol=sym)
            cached_dfs[sym] = df
            price_dict[sym] = df['close']
    logger.info(f"Đã tải {len(cached_dfs)}/{len(DEFAULT_WATCHLIST)} mã thành công.")

    # 2.1 Tính sector strength TRƯỚC khi quét tín hiệu (để cache sẵn cho filter)
    _calculate_all_sector_strengths(cached_dfs)

    # 3. Quét tín hiệu và áp dụng pipeline lọc
    
    for sym in DEFAULT_WATCHLIST:
        df = cached_dfs.get(sym)
        if df is not None and not df.empty:
            signals = check_swing_signals(df, symbol=sym)
            original_score = signals["score"]
            original_status = signals["status"]

            # --- Các yếu tố xác nhận (dùng cho Confidence Level) ---
            volume_confirmed = signals.get("volume_breakout", False)
            weekly_ok = True
            sector_ok = True

            # 3.1 Volume Breakout — SOFT FACTOR (không chặn, chỉ cảnh báo)
            if signals["status"] in ["BUY", "STRONG BUY"]:
                if not volume_confirmed:
                    signals["details"].append("⚠️ Thanh khoản chưa xác nhận (<1.5x TB 20 ngày)")
                else:
                    signals["details"].append("✅ Thanh khoản xác nhận mạnh (≥1.5x TB 20 ngày)")

            # 3.2 Xu hướng trung hạn khung tuần (1W) — SOFT FACTOR (trừ điểm)
            if signals["status"] in ["BUY", "STRONG BUY"]:
                try:
                    with vnstock_limiter:
                        df_weekly = get_stock_ohlcv(sym, length=365, interval="1W")
                    if not df_weekly.empty and len(df_weekly) >= 30:
                        from ta.trend import EMAIndicator
                        ema10_w = EMAIndicator(close=df_weekly['close'], window=10).ema_indicator()
                        ema30_w = EMAIndicator(close=df_weekly['close'], window=30).ema_indicator()
                        if ema10_w.iloc[-1] < ema30_w.iloc[-1]:
                            weekly_ok = False
                            signals["score"] -= 1.5
                            signals["details"].append("⚠️ Xu hướng tuần đang giảm (EMA10w < EMA30w) — Score -1.5")
                            signals["status"] = _recalculate_status(signals["score"])
                except Exception as weekly_e:
                    logger.error(f"Lỗi kiểm tra khung tuần cho {sym}: {weekly_e}")

            # 3.3 Độ rộng thị trường VN30 — HARD GATE (giữ nguyên, bảo vệ vốn)
            if signals["status"] in ["BUY", "STRONG BUY"] and is_market_risky:
                signals["status"] = "NEUTRAL"
                signals["details"].append("🛑 Tín hiệu MUA bị chặn do VN30 dưới EMA20 (bảo vệ dòng vốn)")

            # 3.4 Sức mạnh nhóm ngành — SOFT FACTOR (trừ điểm)
            if signals["status"] in ["BUY", "STRONG BUY"]:
                sector = SYMBOL_TO_SECTOR.get(sym)
                if sector:
                    sector_strength = _sector_strength_cache.get(sector, 50.0)
                    if sector_strength < 50.0:
                        sector_ok = False
                        signals["score"] -= 0.5
                        signals["details"].append(f"⚠️ Sóng ngành {sector} yếu ({sector_strength:.1f}%) — Score -0.5")
                        signals["status"] = _recalculate_status(signals["score"])

            # --- Tính Confidence Level ---
            confidence = _calculate_confidence(signals, volume_confirmed, weekly_ok, sector_ok)

            # --- Logging chi tiết pipeline ---
            if original_status in ["BUY", "STRONG BUY"] or signals["status"] in ["BUY", "STRONG BUY"]:
                logger.info(
                    f"[PIPELINE {sym}] Score gốc: {original_score:+.1f} ({original_status}) → "
                    f"Score cuối: {signals['score']:+.1f} ({signals['status']}) | "
                    f"Volume: {'✅' if volume_confirmed else '⚠️'} | "
                    f"Weekly: {'✅' if weekly_ok else '⚠️ -1.5'} | "
                    f"Market: {'✅' if not is_market_risky else '🛑 BLOCKED'} | "
                    f"Sector: {'✅' if sector_ok else '⚠️ -0.5'} | "
                    f"Confidence: {confidence}"
                )

            scanned_stocks.append({
                "symbol": sym,
                "status": signals["status"],
                "score": signals["score"],
                "price": signals["price"],
                "rsi": signals["rsi"],
                "trend": signals["trend"],
                "confidence": confidence,
                "volume_confirmed": volume_confirmed
            })

            if signals["status"] in ["BUY", "STRONG BUY"]:
                buy_list.append(sym)

    df_scanned = pd.DataFrame(scanned_stocks)
    
    # 2. Tối ưu phân bổ vốn cho các mã BUY/STRONG BUY
    portfolio_text = ""
    if len(buy_list) >= 2:
        df_prices = pd.DataFrame(price_dict)
        weights, _ = optimize_portfolio(df_prices, buy_list, method='hrp')
        if weights:
            portfolio_text = "\n*🛡️ Phân Bổ Vốn Gợi Ý (HRP):*\n"
            for sym, w in weights.items():
                if w > 0.01:
                    portfolio_text += f"- **{sym}**: {w*100:.1f}%\n"
                    
    # 3. Phân tích tâm lý thị trường vĩ mô từ Cafef RSS
    from src.sentiment_analyzer import analyze_market_sentiment
    try:
        logger.info("Đang phân tích tâm lý thị trường vĩ mô cho bản tin Telegram...")
        market_sent = analyze_market_sentiment()
        sentiment_text = f"📢 *Tâm lý vĩ mô:* {market_sent['label']} (Tích cực: {market_sent['bullish_pct']:.1f}% | Điểm: {market_sent['score']:+.2f})\n"
    except Exception as e:
        logger.error(f"Lỗi phân tích tâm lý vĩ mô: {e}")
        sentiment_text = ""

    # 4. Tổng hợp Báo cáo chung gửi Telegram
    header = f"🔔 *BẢN TIN LƯỚT SÓNG VN-WAVETRADER* 🔔\n"
    header += f"📅 Ngày: {pd.Timestamp.now().strftime('%d/%m/%Y')} | Khung ngày giao dịch EOD\n"
    header += sentiment_text
    header += f"📊 Độ rộng VN30: **{breadth:.1f}%**\n"
    if market_warning:
        header += market_warning
    header += "───────────────────\n\n"
    
    body = "*🔥 Các mã có Tín hiệu MUA tiềm năng:*\n"
    df_buys = df_scanned[df_scanned["status"].isin(["BUY", "STRONG BUY"])].sort_values(by="score", ascending=False)
    if not df_buys.empty:
        for _, row in df_buys.iterrows():
            conf = row.get('confidence', 'N/A')
            vol_icon = "📊" if row.get('volume_confirmed', False) else ""
            if conf == "CAO":
                conf_icon = "🟢"
            elif conf == "TRUNG BÌNH":
                conf_icon = "🟡"
            else:
                conf_icon = "🔴"
            body += f"🟢 **{row['symbol']}**: {row['status']} (Điểm: {row['score']:.1f}) | Giá: {row['price']} | RSI: {row['rsi']:.1f} | Tin cậy: {conf_icon} {conf} {vol_icon}\n"
    else:
        body += "Không có tín hiệu mua mới hôm nay.\n"
        
    body += "\n*⚠️ Các mã có Tín hiệu BÁN/RỦI RO:*\n"
    df_sells = df_scanned[df_scanned["status"].isin(["SELL", "STRONG SELL"])].sort_values(by="score")
    if not df_sells.empty:
        for _, row in df_sells.iterrows():
            body += f"🔴 **{row['symbol']}**: {row['status']} (Điểm: {row['score']:.1f}) | Giá: {row['price']} | RSI: {row['rsi']:.1f}\n"
    else:
        body += "Không có tín hiệu bán nguy hiểm hôm nay.\n"
        
    # Thêm gợi ý tối ưu danh mục
    body += portfolio_text
    
    # 4. Trợ lý AI phân tích sâu mã tốt nhất
    ai_report_text = ""
    if not df_buys.empty:
        best_symbol = df_buys.iloc[0]['symbol']
        
        # Tải điểm CANSLIM của mã tốt nhất để đưa vào nội dung tin nhắn và gửi cho AI
        from src.fundamental_screener import calculate_canslim_score
        try:
            canslim_best = calculate_canslim_score(best_symbol)
            canslim_text = f" (Điểm CANSLIM: **{canslim_best['total_score']}/100** - {canslim_best['rating']})"
        except Exception as e:
            logger.error(f"Lỗi tính CANSLIM cho {best_symbol} trong notifier: {e}")
            canslim_best = None
            canslim_text = ""
            
        body += f"\n🤖 *AI gợi ý mã sáng giá nhất:* **{best_symbol}**{canslim_text} (Xem phân tích chi tiết bên dưới)\n"
        
        # Sử dụng dữ liệu đã tải trong vòng lặp trước, tránh tải lại trùng lặp gây tốn request
        df_best = cached_dfs.get(best_symbol, pd.DataFrame())
        if not df_best.empty:
            last_row = df_best.iloc[-1]
            price_summary = {
                "close": last_row['close'],
                "high": last_row['high'],
                "low": last_row['low'],
                "volume": last_row['volume'],
                "volume_sma20": last_row['volume_sma20'] if 'volume_sma20' in last_row else last_row['volume']
            }
            signals_best = check_swing_signals(df_best, symbol=best_symbol)
            
            # Tải thêm tin tức và chỉ số tài chính của mã tốt nhất
            df_ratios = get_company_ratios(best_symbol)
            news_best = get_stock_news(best_symbol, limit=5)
            
            # Phân tích của Gemini (đưa thêm dữ liệu tin tức và điểm CANSLIM vào ngữ cảnh AI)
            ai_report_text = "\n\n🤖 *PHÂN TÍCH CHUYÊN SÂU TỪ AI GEMINI:*\n"
            ai_report_text += "───────────────────\n"
            ai_report = analyze_stock_with_ai(best_symbol, price_summary, signals_best, df_ratios, news_list=news_best, canslim_data=canslim_best)
            
            # Làm gọn định dạng báo cáo cho Telegram
            ai_report_text += ai_report
            
    # 5. AI Summary — tổng hợp tín hiệu bằng LLM
    ai_summary_text = ""
    if not df_buys.empty and len(df_buys) >= 1:
        try:
            from src.llm_analyzer import init_gemini
            model = init_gemini()
            if model:
                # Chuẩn bị dữ liệu cho LLM
                top_stocks = []
                for _, row in df_buys.head(5).iterrows():
                    top_stocks.append(
                        f"- {row['symbol']}: Score={row['score']:.1f}, RSI={row['rsi']:.0f}, "
                        f"Trend={row['trend']}, Confidence={row.get('confidence', 'N/A')}"
                    )
                stocks_text = "\n".join(top_stocks)
                
                summary_prompt = (
                    f"Bạn là chuyên gia phân tích chứng khoán Việt Nam. "
                    f"Dựa trên kết quả quét tín hiệu kỹ thuật hôm nay, hãy viết BẢN TÓM TẮT NGẮN GỌN (tối đa 5 câu) "
                    f"bằng tiếng Việt cho nhà đầu tư cá nhân:\n\n"
                    f"Độ rộng VN30: {breadth:.1f}%\n"
                    f"{'Cảnh báo: Thị trường rủi ro cao!' if is_market_risky else 'Thị trường bình thường.'}\n\n"
                    f"Top tín hiệu MUA:\n{stocks_text}\n\n"
                    f"Số mã BUY: {len(df_buys)}/{len(scanned_stocks)} mã quét.\n"
                    f"Hãy nhận xét ngắn gọn về: 1) Xu hướng chung, 2) Mã nào đáng chú ý nhất và tại sao, "
                    f"3) Lời khuyên cụ thể cho hôm nay."
                )
                
                response = model.generate_content(summary_prompt)
                if response and hasattr(response, 'text') and response.text:
                    ai_summary_text = f"\n\n📋 *TÓM TẮT AI:*\n"
                    ai_summary_text += f"───────────────────\n"
                    ai_summary_text += response.text[:800]  # Giới hạn 800 ký tự
                    ai_summary_text += "\n"
        except Exception as e:
            logger.error(f"Lỗi tạo AI summary: {e}")

    footer = "\n\n───────────────────\n"
    footer += "📈 _Chúc các bạn lướt sóng thành công! VN-WaveTrader System._"
    
    full_message = header + body + ai_report_text + ai_summary_text + footer

    main_sent = send_telegram_message(full_message, chat_id=chat_id)
    
    # Gửi riêng từng thẻ tín hiệu Mua để người dùng bấm nút tương tác (Chỉ gửi khi thị trường không rủi ro)
    if not is_market_risky and not df_buys.empty:
        for _, row in df_buys.iterrows():
            sym = row['symbol']
            price = row['price']
            status = row['status']
            
            # 1. Tối ưu tỷ lệ R:R động theo trạng thái độ rộng thị trường (Dynamic Risk-Reward Ratio)
            df_sym = cached_dfs.get(sym, pd.DataFrame())
            latest_atr = df_sym['atr'].iloc[-1] if not df_sym.empty and 'atr' in df_sym.columns else (price * 0.03)
            
            if breadth >= 65.0:
                sl_mult = 2.0
                tp_mult = 5.0
                market_regime = "Tăng mạnh (Uptrend)"
            else:
                sl_mult = 1.5
                tp_mult = 3.0
                market_regime = "Đi ngang / Yếu (Sideways)"
                
            sl = round(price - sl_mult * latest_atr, 2)
            tp = round(price + tp_mult * latest_atr, 2)
            
            # 2. Tính số lượng đi vốn theo rủi ro cố định 2% tài sản và Kelly
            from src.paper_trader import calculate_fixed_risk_qty, calculate_kelly_sizing
            fixed_risk_qty = calculate_fixed_risk_qty(sym, price, sl)
            kelly = calculate_kelly_sizing(sym)
            
            card_msg = f"🟢 *[TÍN HIỆU MUA TIỀM NĂNG - {sym}]* 🟢\n\n" \
                       f"Mã cổ phiếu **{sym}** ({status}) có điểm mua kỹ thuật bùng nổ!\n" \
                       f"📊 *Chu kỳ thị trường:* {market_regime} (Độ rộng VN30: {breadth:.1f}%)\n" \
                       f"───────────────────\n" \
                       f"- *Giá hiện tại:* **{price:.2f}**\n" \
                       f"- *Cắt lỗ động (SL):* **{sl:.2f}** (hệ số {sl_mult}x ATR)\n" \
                       f"- *Chốt lời động (TP):* **{tp:.2f}** (hệ số {tp_mult}x ATR)\n" \
                       f"- *Khối lượng mua gợi ý (Rủi ro 2%):* **{fixed_risk_qty:,} CP** (Nếu chạm SL chỉ lỗ tối đa 2% tổng tài sản)\n" \
                       f"- *Phân bổ tối đa (Kelly):* **{kelly['suggested_pct']}%** tổng vốn ({kelly['details']})\n" \
                       f"───────────────────\n" \
                       f"👉 *Nhấp chọn nút bên dưới nếu bạn đã mở vị thế mua mã này trên sàn thực tế, hệ thống sẽ tự động thêm vào danh mục ảo và bắt đầu theo dõi dừng lỗ/chốt lời/chặn lãi động cho bạn!*"
                       
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": f"💼 Xác nhận Mua & Giám sát {sym}", "callback_data": f"buy_{sym}_{price:.2f}"}
                    ]
                ]
            }
            send_telegram_message(card_msg, reply_markup=reply_markup, chat_id=chat_id)
            
    return main_sent

if __name__ == "__main__":
    # Test thử gửi báo cáo
    send_daily_report_to_telegram()
