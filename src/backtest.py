import pandas as pd
import numpy as np
import logging
import os
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Định nghĩa các chỉ báo phụ trợ
def EMA(values, n):
    return pd.Series(values).ewm(span=n, adjust=False).mean()

def SMA(values, n):
    return pd.Series(values).rolling(window=n).mean()

def RSI(values, n=14):
    delta = pd.Series(values).diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=n).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=n).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

# 1. Chiến lược giao cắt đường trung bình động (EMA Crossover)
class EmaCrossStrategy(Strategy):
    short_period = 20
    long_period = 50
    
    def init(self):
        # Tính toán các đường EMA ngắn và dài hạn
        # self.data.Close là dữ liệu đóng cửa được tự động truyền vào
        self.ema_s = self.I(EMA, self.data.Close, self.short_period)
        self.ema_l = self.I(EMA, self.data.Close, self.long_period)
        
    def next(self):
        # Mua khi EMA ngắn cắt lên EMA dài
        if crossover(self.ema_s, self.ema_l):
            self.buy()
        # Bán khi EMA ngắn cắt xuống EMA dài
        elif crossover(self.ema_l, self.ema_s):
            self.position.close()

# 2. Chiến lược đảo chiều RSI (RSI Mean Reversion)
class RsiReversionStrategy(Strategy):
    rsi_period = 14
    oversold = 30
    overbought = 70
    
    def init(self):
        self.rsi = self.I(RSI, self.data.Close, self.rsi_period)
        
    def next(self):
        # Mua khi RSI cắt lên từ vùng quá bán (<30)
        if crossover(self.rsi, self.oversold):
            self.buy()
        # Bán khi RSI cắt xuống từ vùng quá mua (>70)
        elif crossover(self.overbought, self.rsi):
            self.position.close()

def run_backtest(df: pd.DataFrame, strategy_name: str = 'ema_cross', cash: float = 100000000, commission: float = 0.0015, params: dict = None) -> tuple:
    """
    Chạy kiểm thử chiến thuật lướt sóng trên dữ liệu lịch sử.
    Trả về: (dict_stats, filepath_html)
    """
    if df.empty or len(df) < 50:
        logging.warning("Dữ liệu quá ít để chạy backtest.")
        return {}, ""
        
    # Chuẩn hóa cột: Backtesting.py yêu cầu viết hoa chữ cái đầu (Open, High, Low, Close, Volume)
    bt_df = df.copy()
    rename_dict = {}
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in bt_df.columns:
            rename_dict[col] = col.capitalize()
    bt_df.rename(columns=rename_dict, inplace=True)
    
    # Chỉ giữ lại các cột cần thiết cho backtest
    bt_df = bt_df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    
    # Chọn chiến lược — tạo dynamic subclass để tránh mutation class variable
    # (quan trọng: không sửa trực tiếp class attribute vì sẽ ảnh hưởng tất cả lần gọi tiếp theo)
    if strategy_name == 'ema_cross':
        short_p = params.get('short_period', 20) if params else 20
        long_p = params.get('long_period', 50) if params else 50
        strat = type('EmaCrossStrategyInstance', (EmaCrossStrategy,), {
            'short_period': short_p,
            'long_period': long_p
        })
    elif strategy_name == 'rsi':
        rsi_p = params.get('rsi_period', 14) if params else 14
        os_p = params.get('oversold', 30) if params else 30
        ob_p = params.get('overbought', 70) if params else 70
        strat = type('RsiReversionStrategyInstance', (RsiReversionStrategy,), {
            'rsi_period': rsi_p,
            'oversold': os_p,
            'overbought': ob_p
        })
    else:
        logging.error(f"Chiến lược {strategy_name} không tồn tại.")
        return {}, ""
        
    try:
        # Khởi tạo Backtest (vốn mặc định 100 triệu, phí giao dịch 0.15% mỗi chiều mua/bán)
        bt = Backtest(bt_df, strat, cash=cash, commission=commission)
        
        # Chạy backtest
        stats = bt.run()
        
        # Chuyển đổi Series stats thành dict
        stats_dict = {
            "start_date": str(stats['Start'].date()) if 'Start' in stats else "N/A",
            "end_date": str(stats['End'].date()) if 'End' in stats else "N/A",
            "duration": str(stats['Duration']) if 'Duration' in stats else "N/A",
            "initial_equity": float(stats['Equity Initial [$]']) if 'Equity Initial [$]' in stats else cash,
            "final_equity": float(stats['Equity Final [$]']) if 'Equity Final [$]' in stats else cash,
            "return_pct": float(stats['Return [%]']) if 'Return [%]' in stats else 0.0,
            "buy_and_hold_return_pct": float(stats['Buy & Hold Return [%]']) if 'Buy & Hold Return [%]' in stats else 0.0,
            "max_drawdown_pct": float(stats['Max. Drawdown [%]']) if 'Max. Drawdown [%]' in stats else 0.0,
            "sharpe_ratio": float(stats['Sharpe Ratio']) if 'Sharpe Ratio' in stats and pd.notna(stats['Sharpe Ratio']) else 0.0,
            "win_rate_pct": float(stats['Win Rate [%]']) if 'Win Rate [%]' in stats and pd.notna(stats['Win Rate [%]']) else 0.0,
            "trades_count": int(stats['# Trades']) if '# Trades' in stats else 0
        }
        
        # Lưu biểu đồ Bokeh thành file HTML tĩnh
        temp_dir = os.path.join(os.getcwd(), 'temp_charts')
        os.makedirs(temp_dir, exist_ok=True)
        html_path = os.path.join(temp_dir, f"backtest_{strategy_name}.html")
        
        try:
            # Tắt chế độ mở trình duyệt tự động của Backtesting.py
            bt.plot(filename=html_path, open_browser=False)
        except Exception as plot_e:
            logging.warning(f"Không thể vẽ biểu đồ do lỗi tương thích Bokeh: {plot_e}")
            html_path = ""
            
        return stats_dict, html_path
        
    except Exception as e:
        logging.error(f"Lỗi khi chạy backtest: {e}")
        return {}, ""

if __name__ == "__main__":
    # Test thử backtest với dữ liệu ngẫu nhiên
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=200)
    data = {
        "open": 100 + np.cumsum(np.random.normal(0.05, 1.0, 200)),
        "high": 102 + np.cumsum(np.random.normal(0.05, 1.0, 200)),
        "low": 98 + np.cumsum(np.random.normal(0.05, 1.0, 200)),
        "close": 100 + np.cumsum(np.random.normal(0.05, 1.0, 200)),
        "volume": np.random.randint(100000, 1000000, 200)
    }
    df = pd.DataFrame(data, index=dates)
    stats, path = run_backtest(df, 'ema_cross')
    print("Kết quả Backtest:")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print("Biểu đồ lưu tại:", path)
