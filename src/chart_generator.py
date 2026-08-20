"""
Module tạo biểu đồ kỹ thuật candlestick và gửi qua Telegram.

Sử dụng matplotlib + mplfinance để tạo biểu đồ:
- Nến Nhật (Candlestick)
- EMA 20/50
- Volume bars
- Đánh dấu vị trí tín hiệu MUA/BÁN

Biểu đồ được lưu tạm vào temp_charts/ và gửi qua Telegram sendPhoto API.
"""
import os
import logging
import requests
from datetime import datetime, timezone, timedelta

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend cho server
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)


def generate_chart(df: pd.DataFrame, symbol: str, signals: dict = None) -> str:
    """
    Tạo biểu đồ candlestick + EMA + Volume cho mã cổ phiếu.
    Trả về đường dẫn file ảnh.
    """
    if df.empty or len(df) < 20:
        logger.warning(f"Dữ liệu quá ít để vẽ biểu đồ cho {symbol}")
        return ""

    # Lấy 60 nến gần nhất để biểu đồ rõ ràng
    df_chart = df.tail(60).copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={'height_ratios': [3, 1]},
                                     sharex=True)
    fig.patch.set_facecolor('#1a1a2e')
    ax1.set_facecolor('#16213e')
    ax2.set_facecolor('#16213e')

    # --- Vẽ Candlestick thủ công ---
    dates = range(len(df_chart))
    opens = df_chart['open'].values
    highs = df_chart['high'].values
    lows = df_chart['low'].values
    closes = df_chart['close'].values
    volumes = df_chart['volume'].values

    for i in range(len(df_chart)):
        color = '#26de81' if closes[i] >= opens[i] else '#ff6b6b'
        # Thân nến
        ax1.bar(i, abs(closes[i] - opens[i]), bottom=min(opens[i], closes[i]),
                width=0.6, color=color, alpha=0.9)
        # Bóng nến
        ax1.vlines(i, lows[i], highs[i], color=color, linewidth=0.8, alpha=0.7)

    # --- Vẽ EMA ---
    if 'ema_short' in df_chart.columns:
        ax1.plot(dates, df_chart['ema_short'].values, color='#ffd93d', linewidth=1.2,
                 label='EMA 20', alpha=0.9)
    if 'ema_long' in df_chart.columns:
        ax1.plot(dates, df_chart['ema_long'].values, color='#6c5ce7', linewidth=1.2,
                 label='EMA 50', alpha=0.9)

    # --- Vẽ Bollinger Bands ---
    if 'bb_high' in df_chart.columns and 'bb_low' in df_chart.columns:
        ax1.fill_between(dates, df_chart['bb_high'].values, df_chart['bb_low'].values,
                         alpha=0.08, color='#74b9ff')

    # --- Đánh dấu tín hiệu ---
    if signals:
        status = signals.get("status", "NEUTRAL")
        if status in ("BUY", "STRONG BUY"):
            ax1.annotate('▲ MUA', xy=(len(df_chart)-1, closes[-1]),
                        fontsize=10, color='#26de81', fontweight='bold',
                        ha='center', va='bottom',
                        xytext=(0, 15), textcoords='offset points')
        elif status in ("SELL", "STRONG SELL"):
            ax1.annotate('▼ BÁN', xy=(len(df_chart)-1, closes[-1]),
                        fontsize=10, color='#ff6b6b', fontweight='bold',
                        ha='center', va='top',
                        xytext=(0, -15), textcoords='offset points')

    # --- Vẽ Volume ---
    vol_colors = ['#26de81' if closes[i] >= opens[i] else '#ff6b6b' for i in range(len(df_chart))]
    ax2.bar(dates, volumes, color=vol_colors, alpha=0.6, width=0.6)
    if 'volume_sma20' in df_chart.columns:
        ax2.plot(dates, df_chart['volume_sma20'].values, color='#ffd93d',
                 linewidth=1, alpha=0.7, label='Vol SMA20')

    # --- Styling ---
    vn_tz = timezone(timedelta(hours=7))
    now_str = datetime.now(vn_tz).strftime("%d/%m/%Y")
    score_text = f" | Score: {signals['score']:.1f}" if signals else ""
    ax1.set_title(f'{symbol} — Biểu đồ kỹ thuật ({now_str}){score_text}',
                  color='white', fontsize=14, fontweight='bold', pad=10)
    ax1.legend(loc='upper left', fontsize=8, facecolor='#16213e', edgecolor='#30475e',
               labelcolor='white')
    ax2.set_ylabel('Volume', color='#a0a0a0', fontsize=9)

    # Tick formatting
    tick_positions = list(range(0, len(df_chart), max(1, len(df_chart)//8)))
    tick_labels = []
    for i in tick_positions:
        if i < len(df_chart):
            idx_val = df_chart.index[i]
            if hasattr(idx_val, 'strftime'):
                tick_labels.append(idx_val.strftime('%d/%m'))
            else:
                tick_labels.append(str(idx_val)[:5])
        else:
            tick_labels.append('')
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, color='#a0a0a0', fontsize=8)

    for ax in (ax1, ax2):
        ax.tick_params(colors='#a0a0a0', labelsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#30475e')
        ax.spines['left'].set_color('#30475e')
        ax.grid(True, alpha=0.15, color='#30475e')

    plt.tight_layout()

    # Lưu file
    filepath = os.path.join(CHARTS_DIR, f"{symbol}_chart.png")
    fig.savefig(filepath, dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"Đã tạo biểu đồ: {filepath}")
    return filepath


def send_chart_to_telegram(filepath: str, caption: str = "", chat_id: str = None) -> bool:
    """Gửi ảnh biểu đồ qua Telegram sendPhoto API."""
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id or not os.path.exists(filepath):
        logger.warning("Thiếu token/chat_id hoặc file biểu đồ không tồn tại.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(filepath, 'rb') as photo:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": photo},
                timeout=30
            )
        if resp.status_code == 200:
            logger.info(f"Đã gửi biểu đồ {os.path.basename(filepath)} qua Telegram.")
            return True
        else:
            logger.error(f"Lỗi gửi biểu đồ: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Lỗi gửi biểu đồ Telegram: {e}")
        return False
