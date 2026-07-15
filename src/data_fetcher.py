import pandas as pd
import logging
import socket
socket.setdefaulttimeout(30) # Ngăn chặn nghẽn socket mạng vô hạn khi gọi API (tăng lên 30s tránh kết nối chậm)
from vnstock import Market, Reference, Fundamental

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_stock_ohlcv(symbol: str, length: int = 365, interval: str = "1D") -> pd.DataFrame:
    """
    Tải dữ liệu lịch sử giá OHLCV của cổ phiếu bằng vnstock.
    """
    try:
        logging.info(f"Đang tải dữ liệu lịch sử {symbol} ({length} ngày, interval={interval})...")
        market = Market()
        # Đối với vnstock v4+, gọi qua market.equity(symbol).ohlcv
        df = market.equity(symbol).ohlcv(length=length, interval=interval)
        
        if df is None or df.empty:
            logging.warning(f"Không có dữ liệu trả về cho {symbol}")
            return pd.DataFrame()
            
        # Chuẩn hóa cột về chữ thường hoặc tên chuẩn để các thư viện khác (ta, backtesting) dễ dùng
        # vnstock v4+ trả về cột dạng: time, open, high, low, close, volume...
        # Đổi tên cột 'time' thành 'Date' hoặc đặt làm Index
        df = df.copy()
        if 'time' in df.columns:
            df['Date'] = pd.to_datetime(df['time'])
            df.set_index('Date', inplace=True)
            df.drop(columns=['time'], inplace=True, errors='ignore')
        
        # Đảm bảo các cột giá là kiểu số
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # Sắp xếp theo ngày tăng dần (cực kỳ quan trọng cho phân tích kỹ thuật)
        df.sort_index(ascending=True, inplace=True)
        return df
        
    except Exception as e:
        logging.error(f"Lỗi khi tải dữ liệu {symbol}: {e}")
        # Thử fallback về cách gọi cũ nếu có lỗi
        try:
            logging.info(f"Đang thử phương thức cũ cho {symbol}...")
            # Trong một số phiên bản vnstock cũ, dùng stock_historical_data
            from vnstock import stock_historical_data
            # Tính toán start_date và end_date từ length
            end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=length)).strftime("%Y-%m-%d")
            df = stock_historical_data(symbol, start_date, end_date, "stock")
            if 'TradingDate' in df.columns:
                df['Date'] = pd.to_datetime(df['TradingDate'])
                df.set_index('Date', inplace=True)
                df.drop(columns=['TradingDate'], inplace=True, errors='ignore')
            elif 'time' in df.columns:
                df['Date'] = pd.to_datetime(df['time'])
                df.set_index('Date', inplace=True)
                df.drop(columns=['time'], inplace=True, errors='ignore')
            # Đổi tên các cột nếu viết hoa: Open -> open, vv.
            df.columns = [c.lower() for c in df.columns]
            df.sort_index(ascending=True, inplace=True)
            return df
        except Exception as fallback_e:
            logging.error(f"Fallback thất bại cho {symbol}: {fallback_e}")
            return pd.DataFrame()

def get_company_info(symbol: str) -> dict:
    """
    Lấy thông tin cơ bản và giới thiệu về doanh nghiệp.
    """
    try:
        ref = Reference()
        df_info = ref.company(symbol).info()
        if df_info is not None and not df_info.empty:
            # Chuyển DataFrame thông tin thành dict
            # Thông thường kết quả trả về dạng bảng 1 dòng hoặc dạng key-value
            return df_info.to_dict(orient='records')[0]
    except Exception as e:
        logging.error(f"Lỗi lấy thông tin doanh nghiệp {symbol}: {e}")
    return {}

def get_company_ratios(symbol: str) -> pd.DataFrame:
    """
    Lấy các chỉ số tài chính cơ bản (P/E, P/B, ROE, ROA, Debt/Equity...).
    """
    try:
        fa = Fundamental()
        df_ratios = fa.equity(symbol).ratio()
        return df_ratios
    except Exception as e:
        logging.error(f"Lỗi lấy chỉ số tài chính {symbol}: {e}")
        return pd.DataFrame()

def get_vn30_symbols() -> list:
    """
    Lấy danh sách các mã cổ phiếu trong nhóm VN30.
    """
    try:
        ref = Reference()
        # Thử lấy danh sách VN30 (vnstock v4+ trả về pandas.Series)
        res = ref.equity.list_by_group("VN30")
        if res is not None and not res.empty:
            if isinstance(res, pd.Series):
                return res.tolist()
            elif hasattr(res, 'columns') and 'symbol' in res.columns:
                return res['symbol'].tolist()
            else:
                return list(res)
    except Exception as e:
        logging.error(f"Lỗi lấy danh sách VN30 từ Reference: {e}")
        
    # Trả về danh sách tĩnh nếu có lỗi
    from config import DEFAULT_WATCHLIST
    return DEFAULT_WATCHLIST

def get_stock_news(symbol: str, limit: int = 5) -> list:
    """
    Lấy danh sách tin tức mới nhất của cổ phiếu từ vnstock.
    """
    try:
        logging.info(f"Đang tải tin tức cho mã {symbol} (tối đa {limit} tin)...")
        ref = Reference()
        df_news = ref.company(symbol).news()
        
        if df_news is None or df_news.empty:
            return []
            
        news_list = []
        for _, row in df_news.head(limit).iterrows():
            news_list.append({
                "title": row.get("title", row.get("head", "")),
                "time": str(row.get("publish_time", "")),
                "url": row.get("url", "")
            })
        return news_list
    except Exception as e:
        logging.error(f"Lỗi khi lấy tin tức của {symbol}: {e}")
        return []

def get_intraday_flow(symbol: str) -> dict:
    """
    Phân tích dòng tiền mua/bán chủ động và lệnh lớn cá mập trong phiên giao dịch gần nhất.
    """
    flow_summary = {
        "total_volume": 0,
        "buy_volume": 0,
        "sell_volume": 0,
        "net_volume": 0,
        "large_buy_vol": 0,
        "large_sell_vol": 0,
        "large_net_vol": 0,
        "large_buy_count": 0,
        "large_sell_count": 0,
        "ratio_buy": 0.5,
        "ratio_large": 0.0
    }
    
    try:
        logging.info(f"Đang tải và phân tích khớp lệnh thời gian thực của {symbol}...")
        mkt = Market()
        df_trades = mkt.equity(symbol).trades()
        
        if df_trades is None or df_trades.empty:
            logging.warning(f"Không có dữ liệu khớp lệnh trong phiên cho {symbol}")
            return flow_summary
            
        # Đảm bảo kiểu dữ liệu chuẩn
        df_trades = df_trades.copy()
        df_trades['volume'] = pd.to_numeric(df_trades['volume'], errors='coerce')
        df_trades['price'] = pd.to_numeric(df_trades['price'], errors='coerce')
        df_trades.dropna(subset=['volume', 'price'], inplace=True)
        
        # 1. Tổng khối lượng khớp lệnh
        total_vol = df_trades['volume'].sum()
        flow_summary["total_volume"] = int(total_vol)
        
        if total_vol == 0:
            return flow_summary
            
        # 2. Tính khối lượng mua / bán chủ động
        df_buy = df_trades[df_trades['match_type'].str.lower() == 'buy']
        df_sell = df_trades[df_trades['match_type'].str.lower() == 'sell']
        
        buy_vol = df_buy['volume'].sum()
        sell_vol = df_sell['volume'].sum()
        
        flow_summary["buy_volume"] = int(buy_vol)
        flow_summary["sell_volume"] = int(sell_vol)
        flow_summary["net_volume"] = int(buy_vol - sell_vol)
        flow_summary["ratio_buy"] = float(buy_vol / total_vol)
        
        # 3. Phân tích lệnh lớn (Cá mập)
        # Định nghĩa giá trị lệnh lớn: >= 50 triệu VNĐ (giá đơn vị: nghìn VNĐ, nên giá * vol >= 50,000)
        df_trades['value_vnd'] = df_trades['price'] * df_trades['volume'] * 1000
        df_large = df_trades[df_trades['value_vnd'] >= 50000000] # >= 50 triệu VNĐ
        
        large_buy = df_large[df_large['match_type'].str.lower() == 'buy']
        large_sell = df_large[df_large['match_type'].str.lower() == 'sell']
        
        large_buy_vol = large_buy['volume'].sum()
        large_sell_vol = large_sell['volume'].sum()
        
        flow_summary["large_buy_vol"] = int(large_buy_vol)
        flow_summary["large_sell_vol"] = int(large_sell_vol)
        flow_summary["large_net_vol"] = int(large_buy_vol - large_sell_vol)
        flow_summary["large_buy_count"] = int(len(large_buy))
        flow_summary["large_sell_count"] = int(len(large_sell))
        
        total_large_vol = large_buy_vol + large_sell_vol
        flow_summary["ratio_large"] = float(total_large_vol / total_vol)
        
        return flow_summary
        
    except Exception as e:
        logging.error(f"Lỗi phân tích dòng tiền trong phiên cho {symbol}: {e}")
        return flow_summary

if __name__ == "__main__":
    # Test thử
    df = get_stock_ohlcv("FPT", length=10)
    print("Dữ liệu FPT:")
    print(df.head(2))
    print("\nThông tin VN30:")
    print(get_vn30_symbols()[:5])
    print("\nTin tức FPT:")
    print(get_stock_news("FPT", limit=2))
    print("\nDòng tiền trong phiên FPT:")
    print(get_intraday_flow("FPT"))

