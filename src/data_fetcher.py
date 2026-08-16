import pandas as pd
import logging
import socket
import threading
import time
socket.setdefaulttimeout(30) # NgÄƒn cháº·n ngháº½n socket máº¡ng vĂ´ háº¡n khi gá»i API (tÄƒng lĂªn 30s trĂ¡nh káº¿t ná»‘i cháº­m)
from vnstock import Market, Reference, Fundamental

logger = logger.getLogger(__name__)

# Cache dá»¯ liá»‡u OHLCV Ä‘á»ƒ trĂ¡nh rate limit
_ohlcv_cache = {}
CACHE_DURATION_SECONDS = 1800  # LÆ°u cache trong 30 phĂºt

def _get_stock_ohlcv_internal(symbol: str, length: int = 365, interval: str = "1D") -> pd.DataFrame:
    """
    HĂ m ná»™i bá»™ thá»±c hiá»‡n táº£i dá»¯ liá»‡u lá»‹ch sá»­ giĂ¡ OHLCV cá»§a cá»• phiáº¿u báº±ng vnstock.
    """
    try:
        logger.info(f"Äang táº£i dá»¯ liá»‡u lá»‹ch sá»­ {symbol} ({length} ngĂ y, interval={interval})...")
        market = Market()
        # Äá»‘i vá»›i vnstock v4+, gá»i qua market.equity(symbol).ohlcv
        df = market.equity(symbol).ohlcv(length=length, interval=interval)
        
        if df is None or df.empty:
            logger.warning(f"KhĂ´ng cĂ³ dá»¯ liá»‡u tráº£ vá» cho {symbol}")
            return pd.DataFrame()
            
        # Chuáº©n hĂ³a cá»™t vá» chá»¯ thÆ°á»ng hoáº·c tĂªn chuáº©n Ä‘á»ƒ cĂ¡c thÆ° viá»‡n khĂ¡c (ta, backtesting) dá»… dĂ¹ng
        # vnstock v4+ tráº£ vá» cá»™t dáº¡ng: time, open, high, low, close, volume...
        # Äá»•i tĂªn cá»™t 'time' thĂ nh 'Date' hoáº·c Ä‘áº·t lĂ m Index
        df = df.copy()
        if 'time' in df.columns:
            df['Date'] = pd.to_datetime(df['time'])
            df.set_index('Date', inplace=True)
            df.drop(columns=['time'], inplace=True, errors='ignore')
        
        # Äáº£m báº£o cĂ¡c cá»™t giĂ¡ lĂ  kiá»ƒu sá»‘
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # Sáº¯p xáº¿p theo ngĂ y tÄƒng dáº§n (cá»±c ká»³ quan trá»ng cho phĂ¢n tĂ­ch ká»¹ thuáº­t)
        df.sort_index(ascending=True, inplace=True)
        return df
        
    except Exception as e:
        logger.error(f"Lá»—i khi táº£i dá»¯ liá»‡u {symbol}: {e}")
        # Thá»­ fallback vá» cĂ¡ch gá»i cÅ© náº¿u cĂ³ lá»—i
        try:
            logger.info(f"Äang thá»­ phÆ°Æ¡ng thá»©c cÅ© cho {symbol}...")
            # Trong má»™t sá»‘ phiĂªn báº£n vnstock cÅ©, dĂ¹ng stock_historical_data
            from vnstock import stock_historical_data
            # TĂ­nh toĂ¡n start_date vĂ  end_date tá»« length
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
            logger.error(f"Fallback thất bại cho {symbol}: {fallback_e}")
            return pd.DataFrame()

def get_stock_ohlcv(symbol: str, length: int = 365, interval: str = "1D") -> pd.DataFrame:
    """
    Tải dữ liệu lịch sử giá OHLCV của cổ phiếu bằng vnstock (có cache, retry và bảo vệ chống treo).
    
    Cải tiến v2:
    - Retry 3 lần với exponential backoff khi API fail
    - Không cache kết quả lỗi dài hạn (chỉ cache negative 5 phút thay vì 30 phút)
    - Cache thành công 30 phút như cũ
    """
    cache_key = (symbol, length, interval)
    current_time = time.time()
    
    # Kiểm tra cache trước để tránh rate limit
    if cache_key in _ohlcv_cache:
        cached_time, cached_df = _ohlcv_cache[cache_key]
        if current_time - cached_time < CACHE_DURATION_SECONDS:
            logger.info(f"🔄 [CACHE HIT] Sử dụng dữ liệu cache của {symbol} (khung {interval})")
            return cached_df.copy()
    
    # Kiểm tra negative cache (tránh gọi lại API liên tục khi lỗi)
    negative_cache_key = f"_neg_{symbol}_{length}_{interval}"
    if negative_cache_key in _ohlcv_cache:
        neg_time, _ = _ohlcv_cache[negative_cache_key]
        if current_time - neg_time < 300:  # Negative cache chỉ 5 phút
            logger.info(f"⏳ [NEG CACHE] Bỏ qua {symbol} — API lỗi gần đây, chờ 5 phút...")
            return pd.DataFrame()
    
    # Retry với exponential backoff (tối đa 3 lần)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        result = []
        exception_container = []
        
        def target():
            try:
                df = _get_stock_ohlcv_internal(symbol, length, interval)
                result.append(df)
            except Exception as e:
                exception_container.append(e)
                
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout=25.0)
        
        if thread.is_alive():
            logger.warning(f"⚠️ [{symbol}] Timeout lần {attempt}/{max_retries} (25s)")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            _ohlcv_cache[negative_cache_key] = (current_time, None)
            return pd.DataFrame()
            
        if exception_container:
            logger.error(f"[{symbol}] Lỗi lần {attempt}/{max_retries}: {exception_container[0]}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            _ohlcv_cache[negative_cache_key] = (current_time, None)
            return pd.DataFrame()
            
        if result and not result[0].empty:
            _ohlcv_cache[cache_key] = (current_time, result[0])
            _ohlcv_cache.pop(negative_cache_key, None)
            if attempt > 1:
                logger.info(f"✅ [{symbol}] Thành công sau {attempt} lần retry")
            return result[0].copy()
        
        if attempt < max_retries:
            logger.warning(f"[{symbol}] Dữ liệu rỗng lần {attempt}/{max_retries}, retry...")
            time.sleep(2 ** attempt)
            
    _ohlcv_cache[negative_cache_key] = (current_time, None)
    return pd.DataFrame()


def get_company_info(symbol: str) -> dict:
    """
    Láº¥y thĂ´ng tin cÆ¡ báº£n vĂ  giá»›i thiá»‡u vá»  doanh nghiá»‡p.
    """
    try:
        ref = Reference()
        df_info = ref.company(symbol).info()
        if df_info is not None and not df_info.empty:
            # Chuyá»ƒn DataFrame thĂ´ng tin thĂ nh dict
            # ThĂ´ng thÆ°á»ng káº¿t quáº£ tráº£ vá» dáº¡ng báº£ng 1 dĂ²ng hoáº·c dáº¡ng key-value
            return df_info.to_dict(orient='records')[0]
    except Exception as e:
        logger.error(f"Lá»—i láº¥y thĂ´ng tin doanh nghiá»‡p {symbol}: {e}")
    return {}

def get_company_ratios(symbol: str) -> pd.DataFrame:
    """
    Láº¥y cĂ¡c chá»‰ sá»‘ tĂ i chĂ­nh cÆ¡ báº£n (P/E, P/B, ROE, ROA, Debt/Equity...).
    """
    try:
        fa = Fundamental()
        df_ratios = fa.equity(symbol).ratio()
        return df_ratios
    except Exception as e:
        logger.error(f"Lá»—i láº¥y chá»‰ sá»‘ tĂ i chĂ­nh {symbol}: {e}")
        return pd.DataFrame()

def _get_vn30_symbols_internal() -> list:
    try:
        ref = Reference()
        # Thá»­ láº¥y danh sĂ¡ch VN30 (vnstock v4+ tráº£ vá» pandas.Series)
        res = ref.equity.list_by_group("VN30")
        if res is not None and not res.empty:
            if isinstance(res, pd.Series):
                return res.tolist()
            elif hasattr(res, 'columns') and 'symbol' in res.columns:
                return res['symbol'].tolist()
            else:
                return list(res)
    except Exception as e:
        logger.error(f"Lá»—i láº¥y danh sĂ¡ch VN30 tá»« Reference: {e}")
    return []

def get_vn30_symbols() -> list:
    """
    Láº¥y danh sĂ¡ch cĂ¡c mĂ£ cá»• phiáº¿u trong nhĂ³m VN30 (cĂ³ báº£o vá»‡ chá»‘ng treo báº±ng Thread).
    """
    result = []
    
    def target():
        res = _get_vn30_symbols_internal()
        result.append(res)
            
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout=15.0) # Giá»›i háº¡n cá»©ng 15 giĂ¢y
    
    if thread.is_alive():
        logger.warning("â ï¸ Láº¥y danh sĂ¡ch VN30 bá»‹ quĂ¡ thá»i gian chá» (timeout 15s). Sá»­ dá»¥ng danh sĂ¡ch cá»©ng dá»± phĂ²ng.")
        # Danh sĂ¡ch VN30 cá»©ng lĂ m dá»± phĂ²ng Ä‘á»ƒ Ä‘áº£m báº£o há»‡ thá»‘ng luĂ´n hoáº¡t Ä‘á»™ng
        return [
            "ACB", "BCG", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", 
            "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB", 
            "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
        ]
        
    if result and result[0]:
        return result[0]
        
    # Tráº£ vá» danh sĂ¡ch tÄ©nh dá»± phĂ²ng náº¿u cĂ³ lá»—i
    return [
        "ACB", "BCG", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", 
        "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB", 
        "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
    ]

def get_stock_news(symbol: str, limit: int = 5) -> list:
    """
    Láº¥y danh sĂ¡ch tin tá»©c má»›i nháº¥t cá»§a cá»• phiáº¿u tá»« vnstock.
    """
    try:
        logger.info(f"Äang táº£i tin tá»©c cho mĂ£ {symbol} (tá»‘i Ä‘a {limit} tin)...")
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
        logger.error(f"Lá»—i khi láº¥y tin tá»©c cá»§a {symbol}: {e}")
        return []

def get_intraday_flow(symbol: str) -> dict:
    """
    PhĂ¢n tĂ­ch dĂ²ng tiá»n mua/bĂ¡n chá»§ Ä‘á»™ng vĂ  lá»‡nh lá»›n cĂ¡ máº­p trong phiĂªn giao dá»‹ch gáº§n nháº¥t.
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
        logger.info(f"Äang táº£i vĂ  phĂ¢n tĂ­ch khá»›p lá»‡nh thá»i gian thá»±c cá»§a {symbol}...")
        mkt = Market()
        df_trades = mkt.equity(symbol).trades()
        
        if df_trades is None or df_trades.empty:
            logger.warning(f"KhĂ´ng cĂ³ dá»¯ liá»‡u khá»›p lá»‡nh trong phiĂªn cho {symbol}")
            return flow_summary
            
        # Äáº£m báº£o kiá»ƒu dá»¯ liá»‡u chuáº©n
        df_trades = df_trades.copy()
        df_trades['volume'] = pd.to_numeric(df_trades['volume'], errors='coerce')
        df_trades['price'] = pd.to_numeric(df_trades['price'], errors='coerce')
        df_trades.dropna(subset=['volume', 'price'], inplace=True)
        
        # 1. Tá»•ng khá»‘i lÆ°á»£ng khá»›p lá»‡nh
        total_vol = df_trades['volume'].sum()
        flow_summary["total_volume"] = int(total_vol)
        
        if total_vol == 0:
            return flow_summary
            
        # 2. TĂ­nh khá»‘i lÆ°á»£ng mua / bĂ¡n chá»§ Ä‘á»™ng
        df_buy = df_trades[df_trades['match_type'].str.lower() == 'buy']
        df_sell = df_trades[df_trades['match_type'].str.lower() == 'sell']
        
        buy_vol = df_buy['volume'].sum()
        sell_vol = df_sell['volume'].sum()
        
        flow_summary["buy_volume"] = int(buy_vol)
        flow_summary["sell_volume"] = int(sell_vol)
        flow_summary["net_volume"] = int(buy_vol - sell_vol)
        flow_summary["ratio_buy"] = float(buy_vol / total_vol)
        
        # 3. PhĂ¢n tĂ­ch lá»‡nh lá»›n (CĂ¡ máº­p)
        # Äá»‹nh nghÄ©a giĂ¡ trá»‹ lá»‡nh lá»›n: >= 50 triá»‡u VNÄ (giĂ¡ Ä‘Æ¡n vá»‹: nghĂ¬n VNÄ, nĂªn giĂ¡ * vol >= 50,000)
        df_trades['value_vnd'] = df_trades['price'] * df_trades['volume'] * 1000
        df_large = df_trades[df_trades['value_vnd'] >= 50000000] # >= 50 triá»‡u VNÄ
        
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
        logger.error(f"Lá»—i phĂ¢n tĂ­ch dĂ²ng tiá»n trong phiĂªn cho {symbol}: {e}")
        return flow_summary

if __name__ == "__main__":
    # Test thá»­
    df = get_stock_ohlcv("FPT", length=10)
    print("Dá»¯ liá»‡u FPT:")
    print(df.head(2))
    print("\nThĂ´ng tin VN30:")
    print(get_vn30_symbols()[:5])
    print("\nTin tá»©c FPT:")
    print(get_stock_news("FPT", limit=2))
    print("\nDĂ²ng tiá»n trong phiĂªn FPT:")
    print(get_intraday_flow("FPT"))

