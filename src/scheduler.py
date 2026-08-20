"""
Module lập lịch báo cáo tự động — sử dụng APScheduler.

Tính năng:
- 08:30 sáng: Báo cáo tâm lý thị trường + tin tức nóng
- 14:45 chiều: Quét tín hiệu intraday (giữa phiên chiều)
- 16:30 chiều: Báo cáo tổng kết ngày + performance danh mục ảo
- Chạy trong background, không chặn các thread khác
"""
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Timezone Việt Nam
VN_TZ = timezone(timedelta(hours=7))

# Scheduler singleton
_scheduler = None


def _send_morning_report():
    """08:30 — Báo cáo tâm lý thị trường sáng & điểm tin nóng."""
    try:
        from src.notifier import send_telegram_message
        from src.sentiment_analyzer import analyze_market_sentiment

        logger.info("⏰ [SCHEDULER] Bắt đầu gửi báo cáo sáng (08:30)...")

        sentiment_result = None
        try:
            sentiment_result = analyze_market_sentiment()
        except Exception as e:
            logger.error(f"Lỗi phân tích tâm lý sáng: {e}")

        now_str = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
        msg = f"☀️ *BÁO CÁO TÂM LÝ SÁNG — {now_str}*\n"
        msg += "───────────────────\n\n"

        if sentiment_result and isinstance(sentiment_result, dict):
            label = sentiment_result.get("label", "TRUNG TÍNH (Neutral)")
            score = float(sentiment_result.get("score", 0.0))
            bullish_pct = float(sentiment_result.get("bullish_pct", 50.0))
            bearish_pct = float(sentiment_result.get("bearish_pct", 50.0))

            # Icon theo trạng thái
            if score >= 0.15:
                sent_icon = "🟢"
            elif score <= -0.15:
                sent_icon = "🔴"
            else:
                sent_icon = "⚪"

            msg += f"🧠 *Tâm lý thị trường:* {sent_icon} **{label}**\n"
            msg += f"📊 *Chỉ số sắc thái:* **{score:+.2f}** (🐂 {bullish_pct:.0f}% Tích cực | 🐻 {bearish_pct:.0f}% Tiêu cực)\n\n"

            details = sentiment_result.get("details", [])
            if details:
                msg += "*📰 Điểm tin tài chính đầu ngày:*\n"
                for item in details[:5]:
                    item_score = float(item.get("score", 0.0))
                    tag = "🟢" if item_score >= 0.15 else ("🔴" if item_score <= -0.15 else "⚪")
                    title = item.get("title", "").strip()
                    msg += f"  {tag} {title}\n"
                msg += "\n"
        else:
            msg += "📝 *Tâm lý thị trường:* Đang cập nhật dữ liệu đầu phiên.\n\n"

        msg += "───────────────────\n"
        msg += "💡 _Gõ /forecast hoặc /scan để quét tín hiệu kỹ thuật chi tiết._"

        send_telegram_message(msg)
        logger.info("✅ [SCHEDULER] Đã gửi báo cáo sáng thành công.")
    except Exception as e:
        logger.error(f"[SCHEDULER] Lỗi gửi báo cáo sáng: {e}")


def _send_intraday_scan():
    """14:45 — Quét tín hiệu intraday giữa phiên chiều."""
    try:
        from src.notifier import send_daily_report_to_telegram

        logger.info("⏰ [SCHEDULER] Bắt đầu quét tín hiệu intraday (14:45)...")
        send_daily_report_to_telegram()
        logger.info("✅ [SCHEDULER] Đã gửi báo cáo intraday thành công.")
    except Exception as e:
        logger.error(f"[SCHEDULER] Lỗi quét intraday: {e}")


def _send_eod_report():
    """16:30 — Báo cáo tổng kết ngày + danh mục ví ảo."""
    try:
        from src.notifier import send_telegram_message
        from src.paper_trader import load_portfolio

        logger.info("⏰ [SCHEDULER] Bắt đầu gửi báo cáo cuối ngày (16:30)...")

        portfolio = load_portfolio()
        positions = portfolio.get("positions", [])
        cash = portfolio.get("cash", 100_000_000.0)
        history = portfolio.get("history", [])

        now_str = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
        msg = f"🌙 *BÁO CÁO CUỐI NGÀY — {now_str}*\n"
        msg += "───────────────────\n\n"

        # Thống kê danh mục ảo
        msg += f"💰 *Tiền mặt khả dụng:* **{cash:,.0f}đ**\n"
        msg += f"📊 *Vị thế đang mở:* **{len(positions)} mã**\n"

        if positions:
            msg += "\n*Chi tiết vị thế nắm giữ:*\n"
            for pos in positions[:10]:
                symbol = pos.get("symbol", "?")
                buy_price = pos.get("buy_price", 0)
                quantity = pos.get("quantity", 0)
                sl = pos.get("stop_loss", 0)
                tp = pos.get("take_profit", 0)
                sl_str = f"{sl:.2f}" if sl else "N/A"
                tp_str = f"{tp:.2f}" if tp else "N/A"
                msg += f"  • **{symbol}**: {quantity:,} cp @ {buy_price:.2f} (SL: {sl_str} | TP: {tp_str})\n"

        # Thống kê giao dịch đã đóng hôm nay
        today_str = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        today_trades = [t for t in history if t.get("sell_date", "").startswith(today_str)]
        if today_trades:
            total_pnl = sum(t.get("pnl_amount", 0) for t in today_trades)
            pnl_sign = "+" if total_pnl >= 0 else ""
            msg += f"\n📈 *Giao dịch đóng hôm nay:* {len(today_trades)} lệnh\n"
            msg += f"💵 *P&L thực nhận hôm nay:* **{pnl_sign}{total_pnl:,.0f}đ**\n"

        msg += "\n───────────────────\n"
        msg += "🛡️ _Hệ thống sẽ tiếp tục giám sát stop-loss & take-profit realtime._"

        send_telegram_message(msg)
        logger.info("✅ [SCHEDULER] Đã gửi báo cáo cuối ngày thành công.")
    except Exception as e:
        logger.error(f"[SCHEDULER] Lỗi gửi báo cáo cuối ngày: {e}")


def start_scheduler():
    """Khởi động scheduler với 3 job chạy mỗi ngày (trừ T7/CN)."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("[SCHEDULER] Scheduler đã đang chạy, bỏ qua khởi tạo lặp.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone=VN_TZ)

    # Job 1: Báo cáo sáng — 08:30 thứ Hai-Thứ Sáu
    _scheduler.add_job(
        _send_morning_report,
        CronTrigger(hour=8, minute=30, day_of_week='mon-fri', timezone=VN_TZ),
        id='morning_report',
        name='Báo cáo tâm lý sáng',
        misfire_grace_time=300  # Cho phép trễ 5 phút
    )

    # Job 2: Quét tín hiệu intraday — 14:45 thứ Hai-Thứ Sáu
    _scheduler.add_job(
        _send_intraday_scan,
        CronTrigger(hour=14, minute=45, day_of_week='mon-fri', timezone=VN_TZ),
        id='intraday_scan',
        name='Quét tín hiệu intraday',
        misfire_grace_time=300
    )

    # Job 3: Báo cáo cuối ngày — 16:30 thứ Hai-Thứ Sáu
    _scheduler.add_job(
        _send_eod_report,
        CronTrigger(hour=16, minute=30, day_of_week='mon-fri', timezone=VN_TZ),
        id='eod_report',
        name='Báo cáo tổng kết ngày',
        misfire_grace_time=300
    )

    _scheduler.start()
    logger.info("✅ [SCHEDULER] Đã khởi động lịch báo cáo tự động:")
    logger.info("   📌 08:30 — Tâm lý thị trường sáng")
    logger.info("   📌 14:45 — Quét tín hiệu intraday")
    logger.info("   📌 16:30 — Báo cáo tổng kết ngày")
    return _scheduler


def stop_scheduler():
    """Dừng scheduler khi shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHEDULER] Scheduler đã được dừng.")
