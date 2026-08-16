import os
import json
import logging
import pandas as pd
import sys

from src.backtest import run_backtest
from config import INDICATOR_PARAMS

logger = logging.getLogger(__name__)

OPTIMIZED_PARAMS_FILE = "optimized_params.json"

def load_optimized_params() -> dict:
    """Tải cấu hình tham số tối ưu từ file JSON."""
    if not os.path.exists(OPTIMIZED_PARAMS_FILE):
        return {}
    try:
        with open(OPTIMIZED_PARAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file tham số tối ưu: {e}")
        return {}

def save_optimized_params(params: dict):
    """Lưu cấu hình tham số tối ưu xuống file JSON."""
    try:
        with open(OPTIMIZED_PARAMS_FILE, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Lỗi khi lưu file tham số tối ưu: {e}")

def get_indicator_params(symbol: str, strategy_name: str = 'ema_cross') -> dict:
    """
    Trả về bộ tham số chỉ báo kỹ thuật của một mã cổ phiếu.
    Nếu mã đó đã được tối ưu hóa thì trả về tham số đã tối ưu, ngược lại trả về mặc định từ config.py.
    """
    optimized = load_optimized_params()
    
    if symbol in optimized and strategy_name in optimized[symbol]:
        return optimized[symbol][strategy_name]
        
    # Giá trị mặc định
    if strategy_name == 'ema_cross':
        return {
            "short_period": INDICATOR_PARAMS.get("EMA_SHORT", 20),
            "long_period": INDICATOR_PARAMS.get("EMA_LONG", 50)
        }
    elif strategy_name == 'rsi':
        return {
            "rsi_period": INDICATOR_PARAMS["RSI"]["period"],
            "oversold": INDICATOR_PARAMS["RSI"]["oversold"],
            "overbought": INDICATOR_PARAMS["RSI"]["overbought"]
        }
    return {}

def optimize_ticker_parameters(symbol: str, df: pd.DataFrame, strategy_name: str = 'ema_cross') -> dict:
    """
    Chạy Grid Search trên dữ liệu lịch sử của mã để tìm tham số tối ưu nhất.
    Trả về: dict chứa kết quả so sánh trước/sau tối ưu và bộ tham số tốt nhất.
    """
    if df.empty or len(df) < 50:
        return {"success": False, "message": "Không đủ dữ liệu lịch sử để chạy tối ưu."}
        
    best_return = -999.0
    best_params = {}
    best_stats = {}
    
    # 1. Chạy với tham số mặc định trước làm mốc so sánh (Baseline)
    default_params = get_indicator_params(symbol, strategy_name)
    default_stats, _ = run_backtest(df, strategy_name, params=default_params)
    
    # Grid Search tìm kiếm thủ công (Tránh PicklingError của thư viện trên Windows)
    if strategy_name == 'ema_cross':
        # Thử nghiệm 12 tổ hợp EMA
        ema_shorts = [10, 15, 20, 25]
        ema_longs = [30, 45, 50, 60]
        
        for s in ema_shorts:
            for l in ema_longs:
                if s >= l:
                    continue
                params = {"short_period": s, "long_period": l}
                stats, _ = run_backtest(df, 'ema_cross', params=params)
                
                if stats and stats.get("return_pct", 0.0) > best_return:
                    best_return = stats["return_pct"]
                    best_params = params
                    best_stats = stats
                    
    elif strategy_name == 'rsi':
        # Thử nghiệm 18 tổ hợp RSI
        rsi_periods = [10, 12, 14, 16]
        oversolds = [30, 35, 40]
        overboughts = [60, 65, 70]
        
        for p in rsi_periods:
            for os_val in oversolds:
                for ob_val in overboughts:
                    params = {"rsi_period": p, "oversold": os_val, "overbought": ob_val}
                    stats, _ = run_backtest(df, 'rsi', params=params)
                    
                    if stats and stats.get("return_pct", 0.0) > best_return:
                        best_return = stats["return_pct"]
                        best_params = params
                        best_stats = stats
    
    if not best_params:
        return {"success": False, "message": "Không tìm thấy bộ tham số hợp lệ."}
        
    # Lưu bộ tham số tốt nhất vào optimized_params.json
    optimized = load_optimized_params()
    if symbol not in optimized:
        optimized[symbol] = {}
    optimized[symbol][strategy_name] = best_params
    save_optimized_params(optimized)
    
    return {
        "success": True,
        "strategy": strategy_name,
        "default_params": default_params,
        "default_stats": default_stats,
        "optimized_params": best_params,
        "optimized_stats": best_stats,
        "improvement_pct": best_stats.get("return_pct", 0.0) - default_stats.get("return_pct", 0.0)
    }
