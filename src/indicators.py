import pandas as pd
import numpy as np
import logging
from config import INDICATOR_PARAMS

# Import các module của thư viện ta (bukosabino/ta)
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange

logger = logging.getLogger(__name__)

def calculate_indicators(df: pd.DataFrame, symbol: str = None) -> pd.DataFrame:
    """
    Tính toán các chỉ báo kỹ thuật cốt lõi sử dụng thư viện ta.
    """
    if df.empty or len(df) < 50:
        logger.warning("Dữ liệu quá ít hoặc rỗng để tính toán chỉ báo (yêu cầu tối thiểu 50 nến).")
        return df
        
    df = df.copy()
    
    # Tải tham số tối ưu động nếu có cung cấp symbol
    from src.parameter_tuning import get_indicator_params
    
    # 1. Chỉ số động lượng RSI
    rsi_params = get_indicator_params(symbol, 'rsi') if symbol else {
        "rsi_period": INDICATOR_PARAMS["RSI"]["period"]
    }
    rsi_p = rsi_params.get("rsi_period", 14)
    df['rsi'] = RSIIndicator(close=df['close'], window=rsi_p).rsi()
    
    # 2. Chỉ báo MACD
    macd_fast = INDICATOR_PARAMS["MACD"]["fast"]
    macd_slow = INDICATOR_PARAMS["MACD"]["slow"]
    macd_sign = INDICATOR_PARAMS["MACD"]["signal"]
    macd_obj = MACD(close=df['close'], window_fast=macd_fast, window_slow=macd_slow, window_sign=macd_sign)
    df['macd'] = macd_obj.macd()
    df['macd_signal'] = macd_obj.macd_signal()
    df['macd_diff'] = macd_obj.macd_diff()
    
    # 3. Dải Bollinger Bands
    bb_p = INDICATOR_PARAMS["BOLLINGER_BANDS"]["period"]
    bb_std = INDICATOR_PARAMS["BOLLINGER_BANDS"]["std_dev"]
    bb_obj = BollingerBands(close=df['close'], window=bb_p, window_dev=bb_std)
    df['bb_high'] = bb_obj.bollinger_hband()
    df['bb_low'] = bb_obj.bollinger_lband()
    df['bb_mavg'] = bb_obj.bollinger_mavg()
    df['bb_percent'] = bb_obj.bollinger_pband()
    
    # 4. Đường trung bình động lũy thừa EMA
    ema_params = get_indicator_params(symbol, 'ema_cross') if symbol else {
        "short_period": INDICATOR_PARAMS["EMA_SHORT"],
        "long_period": INDICATOR_PARAMS["EMA_LONG"]
    }
    ema_s = ema_params.get("short_period", 20)
    ema_l = ema_params.get("long_period", 50)
    df['ema_short'] = EMAIndicator(close=df['close'], window=ema_s).ema_indicator()
    df['ema_long'] = EMAIndicator(close=df['close'], window=ema_l).ema_indicator()
    
    # 5. Stochastic Oscillator
    stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()
    
    # 6. Biến động ATR
    atr_p = INDICATOR_PARAMS["ATR_PERIOD"]
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=atr_p).average_true_range()
    
    # 7. Khối lượng trung bình (Volume SMA 20) để phát hiện đột biến thanh khoản
    df['volume_sma20'] = SMAIndicator(close=df['volume'], window=20).sma_indicator()
    
    # 8. ADX — Average Directional Index (đo cường độ xu hướng)
    adx_obj = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
    df['adx'] = adx_obj.adx()
    df['adx_pos'] = adx_obj.adx_pos()  # +DI
    df['adx_neg'] = adx_obj.adx_neg()  # -DI
    
    # 9. Chỉ báo SuperTrend nâng cao
    df = calculate_supertrend(df)
    
    return df

def check_swing_signals(df: pd.DataFrame, symbol: str = None) -> dict:
    """
    Quét và tạo tín hiệu lướt sóng cho ngày gần nhất (dòng cuối cùng của DataFrame).
    """
    signals = {
        "status": "NEUTRAL",
        "score": 0,  # Thang điểm từ -5 (Cực kỳ xấu) đến +5 (Cực kỳ tốt)
        "details": [],
        "price": 0.0,
        "rsi": 50.0,
        "macd_signal": "Neutral",
        "trend": "Neutral",
        "volume_breakout": False
    }
    
    if df.empty or 'rsi' not in df.columns:
        return signals
        
    # Lấy dòng cuối cùng (ngày giao dịch gần nhất) và dòng kế cuối (để phát hiện điểm giao cắt)
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) > 1 else last_row
    
    close_price = last_row['close']
    signals["price"] = close_price
    signals["rsi"] = last_row['rsi']
    
    # 1. Đánh giá Xu hướng qua EMA
    # Xu hướng tăng ngắn hạn: ema_short > ema_long và giá nằm trên ema_short
    if last_row['ema_short'] > last_row['ema_long']:
        if close_price > last_row['ema_short']:
            signals["trend"] = "BULLISH"
            signals["score"] += 1
            signals["details"].append("Xu hướng tăng (Giá > EMA20 > EMA50)")
        else:
            signals["trend"] = "PULLBACK"
            signals["details"].append("Điều chỉnh trong xu hướng tăng (Giá nằm dưới EMA20 nhưng EMA20 > EMA50)")
    else:
        if close_price < last_row['ema_short']:
            signals["trend"] = "BEARISH"
            signals["score"] -= 1
            signals["details"].append("Xu hướng giảm (Giá < EMA20 < EMA50)")
        else:
            signals["trend"] = "RECOVERY"
            signals["details"].append("Phục hồi ngắn hạn (Giá vượt EMA20 nhưng EMA20 < EMA50)")

    # Đánh giá SuperTrend
    if 'supertrend_dir' in last_row:
        if last_row['supertrend_dir'] == 1:
            signals["details"].append("SuperTrend báo Xu hướng tăng (BULLISH)")
            if prev_row['supertrend_dir'] == -1:
                signals["score"] += 2.5
                signals["details"].append("[MUA] SuperTrend đảo chiều sang TĂNG (Tín hiệu MUA mạnh)")
        else:
            signals["details"].append("SuperTrend báo Xu hướng giảm (BEARISH)")
            if prev_row['supertrend_dir'] == 1:
                signals["score"] -= 2.5
                signals["details"].append("[BÁN] SuperTrend đảo chiều sang GIẢM (Tín hiệu BÁN mạnh)")

    # Giao cắt EMA (Golden/Death Cross mới xuất hiện)
    if prev_row['ema_short'] <= prev_row['ema_long'] and last_row['ema_short'] > last_row['ema_long']:
        signals["score"] += 2
        signals["details"].append("[MUA] Xuất hiện Golden Cross mới (EMA20 cắt lên EMA50)")
    elif prev_row['ema_short'] >= prev_row['ema_long'] and last_row['ema_short'] < last_row['ema_long']:
        signals["score"] -= 2
        signals["details"].append("[BÁN] Xuất hiện Death Cross mới (EMA20 cắt xuống EMA50)")

    # 2. Đánh giá MACD
    macd = last_row['macd']
    macd_sig = last_row['macd_signal']
    
    # Giao cắt MACD Line và Signal Line
    if prev_row['macd'] <= prev_row['macd_signal'] and macd > macd_sig:
        signals["macd_signal"] = "Golden Cross"
        signals["score"] += 2
        signals["details"].append("[MUA] MACD cắt lên đường Tín hiệu (Golden Cross)")
    elif prev_row['macd'] >= prev_row['macd_signal'] and macd < macd_sig:
        signals["macd_signal"] = "Death Cross"
        signals["score"] -= 2
        signals["details"].append("[BÁN] MACD cắt xuống đường Tín hiệu (Death Cross)")
    else:
        signals["macd_signal"] = "Bullish" if macd > macd_sig else "Bearish"
        
    # 3. Đánh giá RSI
    rsi = last_row['rsi']
    from src.parameter_tuning import get_indicator_params
    rsi_params = get_indicator_params(symbol, 'rsi') if symbol else {
        "oversold": INDICATOR_PARAMS["RSI"]["oversold"],
        "overbought": INDICATOR_PARAMS["RSI"]["overbought"]
    }
    oversold = rsi_params.get("oversold", 30)
    overbought = rsi_params.get("overbought", 70)
    
    if rsi < oversold:
        signals["score"] += 1
        signals["details"].append(f"RSI Quá bán (<{oversold}) - Có khả năng hồi kỹ thuật")
    elif rsi > overbought:
        signals["score"] -= 1
        signals["details"].append(f"RSI Quá mua (>{overbought}) - Rủi ro đảo chiều giảm")
        
    # Giao cắt thoát quá bán/quá mua
    if prev_row['rsi'] <= oversold and rsi > oversold:
        signals["score"] += 2
        signals["details"].append("[MUA] RSI cắt lên trên vùng Quá bán (Tín hiệu hồi phục)")
    elif prev_row['rsi'] >= overbought and rsi < overbought:
        signals["score"] -= 2
        signals["details"].append("[BÁN] RSI cắt xuống dưới vùng Quá mua (Tín hiệu hạ nhiệt)")

    # 4. Đánh giá Bollinger Bands
    bb_pband = last_row['bb_percent']
    if bb_pband < 0:
        signals["score"] += 1.5
        signals["details"].append("[MUA] Giá đóng cửa thủng biên dưới Bollinger Bands (Kỳ vọng hồi lại vào dải)")
    elif bb_pband > 1:
        signals["score"] -= 1.5
        signals["details"].append("[BÁN] Giá vượt biên trên Bollinger Bands (Có thể quá đà tăng)")

    # 5. Đột biến khối lượng (Volume Breakout)
    volume = last_row['volume']
    vol_sma = last_row['volume_sma20']
    if vol_sma > 0 and volume > 1.5 * vol_sma:
        signals["volume_breakout"] = True
        if signals["trend"] in ["BULLISH", "RECOVERY"] and last_row['close'] > prev_row['close']:
            signals["score"] += 1.5
            signals["details"].append("Khối lượng tăng mạnh (>1.5 lần TB 20 ngày) đồng thuận với giá tăng (Breakout)")
        else:
            signals["details"].append("Khối lượng tăng đột biến (>1.5 lần TB 20 ngày)")

    # 6. Đánh giá Stochastic Oscillator (đã tính nhưng chưa dùng trong scoring trước đây)
    if 'stoch_k' in last_row and 'stoch_d' in last_row:
        stoch_k = last_row['stoch_k']
        stoch_d = last_row['stoch_d']
        prev_stoch_k = prev_row.get('stoch_k', 50)
        prev_stoch_d = prev_row.get('stoch_d', 50)
        
        # Stochastic Golden Cross tại vùng oversold (< 20)
        if prev_stoch_k <= prev_stoch_d and stoch_k > stoch_d and stoch_k < 25:
            signals["score"] += 1.5
            signals["details"].append("[MUA] Stochastic %K cắt lên %D tại vùng quá bán (<25)")
        # Stochastic Death Cross tại vùng overbought (> 80)
        elif prev_stoch_k >= prev_stoch_d and stoch_k < stoch_d and stoch_k > 75:
            signals["score"] -= 1.5
            signals["details"].append("[BÁN] Stochastic %K cắt xuống %D tại vùng quá mua (>75)")
        # Vùng oversold/overbought nhẹ
        elif stoch_k < 20:
            signals["score"] += 0.5
            signals["details"].append("Stochastic quá bán (<20) — kỳ vọng phục hồi")
        elif stoch_k > 80:
            signals["score"] -= 0.5
            signals["details"].append("Stochastic quá mua (>80) — rủi ro đảo chiều")

    # 7. Đánh giá ADX — cường độ xu hướng
    if 'adx' in last_row:
        adx_val = last_row['adx']
        adx_pos = last_row.get('adx_pos', 0)
        adx_neg = last_row.get('adx_neg', 0)
        signals["adx"] = adx_val
        
        if adx_val >= 25:
            # Xu hướng mạnh — tăng trọng số cho signal hiện tại
            if adx_pos > adx_neg:
                signals["score"] += 0.5
                signals["details"].append(f"ADX={adx_val:.0f} (xu hướng TĂNG mạnh, +DI > -DI)")
            else:
                signals["score"] -= 0.5
                signals["details"].append(f"ADX={adx_val:.0f} (xu hướng GIẢM mạnh, -DI > +DI)")
        elif adx_val < 20:
            # Sideway — giảm trọng số tín hiệu (tín hiệu yếu trong sideway)
            signals["score"] *= 0.7  # Giảm 30% score
            signals["details"].append(f"⚠️ ADX={adx_val:.0f} (thị trường sideway — tín hiệu yếu, đã giảm 30% trọng số)")

    # 8. Tổng hợp tín hiệu (Status)
    score = signals["score"]
    if score >= 3:
        signals["status"] = "STRONG BUY"
    elif 1 <= score < 3:
        signals["status"] = "BUY"
    elif -1 < score < 1:
        signals["status"] = "NEUTRAL"
    elif -3 < score <= -1:
        signals["status"] = "SELL"
    else:
        signals["status"] = "STRONG SELL"
        
    return signals

def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    Tính toán chỉ báo SuperTrend.
    """
    df = df.copy()
    if df.empty or len(df) < period:
        df['supertrend'] = df['close']
        df['supertrend_dir'] = 1
        return df

    # Tính ATR nếu chưa có
    if 'atr' not in df.columns:
        df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=period).average_true_range()
        
    df['atr'] = df['atr'].fillna(0)
    
    # 1. Tính các dải cơ bản (Basic Bands)
    hl2 = (df['high'] + df['low']) / 2
    df['basic_ub'] = hl2 + multiplier * df['atr']
    df['basic_lb'] = hl2 - multiplier * df['atr']
    
    # 2. Khởi tạo các dải cuối cùng (Final Bands) và SuperTrend
    final_ub = np.zeros(len(df))
    final_lb = np.zeros(len(df))
    supertrend = np.zeros(len(df))
    direction = np.ones(len(df)) # 1: Up, -1: Down
    
    close = df['close'].values
    basic_ub = df['basic_ub'].values
    basic_lb = df['basic_lb'].values
    
    # Chạy vòng lặp tính toán từng nến
    for i in range(1, len(df)):
        # Tính Final Upper Band
        if basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1]:
            final_ub[i] = basic_ub[i]
        else:
            final_ub[i] = final_ub[i-1]
            
        # Tính Final Lower Band
        if basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1]:
            final_lb[i] = basic_lb[i]
        else:
            final_lb[i] = final_lb[i-1]
            
        # Xác định xu hướng (direction) và giá trị SuperTrend
        if supertrend[i-1] == final_ub[i-1]:
            direction[i] = -1 if close[i] > final_ub[i] else 1
        else:
            direction[i] = 1 if close[i] < final_lb[i] else -1
            
        if direction[i] == 1:
            supertrend[i] = final_ub[i]
            direction[i] = -1 # Xu hướng giảm (close < supertrend)
        else:
            supertrend[i] = final_lb[i]
            direction[i] = 1 # Xu hướng tăng (close > supertrend)
            
    df['supertrend'] = supertrend
    df['supertrend_dir'] = direction
    
    # Dọn dẹp cột tạm
    df.drop(columns=['basic_ub', 'basic_lb'], inplace=True, errors='ignore')
    return df

def find_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """
    Tự động xác định mức Hỗ trợ gần nhất bên dưới giá hiện tại
    và mức Kháng cự gần nhất bên trên giá hiện tại dựa trên cực trị lịch sử.
    """
    levels = {"support": None, "resistance": None}
    if df.empty or len(df) < window:
        return levels
        
    try:
        from scipy.signal import argrelextrema
        # Lấy dữ liệu giá đóng cửa 60 phiên gần nhất để tìm hỗ trợ/kháng cự ngắn hạn
        prices = df['close'].tail(60).values
        
        # Tìm cực tiểu địa phương (hỗ trợ) và cực đại địa phương (kháng cự)
        min_indices = argrelextrema(prices, np.less, order=5)[0]
        max_indices = argrelextrema(prices, np.greater, order=5)[0]
        
        supports = prices[min_indices]
        resistances = prices[max_indices]
        
        current_price = df.iloc[-1]['close']
        
        # Lọc hỗ trợ gần nhất bên dưới giá hiện tại
        sub_supports = [s for s in supports if s < current_price]
        if sub_supports:
            levels["support"] = float(max(sub_supports))
        else:
            # Fallback nếu không tìm thấy cực tiểu, lấy giá thấp nhất của 60 phiên
            levels["support"] = float(prices.min())
            
        # Lọc kháng cự gần nhất bên trên giá hiện tại
        sup_resistances = [r for r in resistances if r > current_price]
        if sup_resistances:
            levels["resistance"] = float(min(sup_resistances))
        else:
            # Fallback lấy giá cao nhất của 60 phiên
            levels["resistance"] = float(prices.max())
            
    except Exception as e:
        logger.error(f"Lỗi tự động tính Hỗ trợ/Kháng cự: {e}")
        
    return levels

