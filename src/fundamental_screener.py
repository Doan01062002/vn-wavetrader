import re
import time
import logging
import pandas as pd
from vnstock import Fundamental, Market
from src.data_fetcher import get_stock_ohlcv

# Khởi tạo logger
logger = logging.getLogger(__name__)

_vnindex_cache = None

def get_vnindex_data(market):
    global _vnindex_cache
    if _vnindex_cache is None or _vnindex_cache.empty:
        try:
            logger.info("Đang tải dữ liệu VNINDEX để đối chiếu sức mạnh giá (RS)...")
            _vnindex_cache = market.equity("VNINDEX").ohlcv(length=60, interval="1D")
        except Exception as e:
            logger.error(f"Lỗi tải VNINDEX: {e}")
            _vnindex_cache = pd.DataFrame()
    return _vnindex_cache

def calculate_canslim_score(symbol: str) -> dict:
    """
    Tính toán điểm số CANSLIM & Minervini cho một mã cổ phiếu (thang điểm 100).
    Trả về: dict chứa điểm tổng, điểm từng tiêu chí, thông số chi tiết và đánh giá.
    """
    logger.info(f"Đang phân tích CANSLIM cho mã {symbol}...")
    
    # Khởi tạo các đối tượng API
    fun = Fundamental()
    market = Market()
    
    # Kết quả mặc định khi có lỗi hoặc thiếu dữ liệu
    result = {
        "symbol": symbol,
        "total_score": 50,
        "rating": "NEUTRAL",
        "details": {
            "C": {"score": 10, "desc": "Thiếu dữ liệu tăng trưởng quý YoY", "value": None},
            "A": {"score": 10, "desc": "Thiếu dữ liệu tăng trưởng năm hoặc ROE", "value": None},
            "N": {"score": 10, "desc": "Thiếu dữ liệu giá đỉnh 52 tuần", "value": None},
            "S": {"score": 10, "desc": "Thiếu dữ liệu thanh khoản", "value": None},
            "L": {"score": 10, "desc": "Thiếu dữ liệu so sánh VNINDEX", "value": None},
            "I": {"score": 10, "desc": "Thiếu dữ liệu giao dịch khối ngoại", "value": None}
        },
        "financial_metrics": {
            "roe": 0.0,
            "pe": 0.0,
            "pb": 0.0,
            "net_margin": 0.0
        }
    }
    
    try:
        # 1. Tải và xử lý Ratios (Chỉ số tài chính)
        df_r = fun.equity(symbol).ratio()
        ratios_dict = {}
        if not df_r.empty and "item_id" in df_r.columns:
            # Lấy các cột không phải item, item_id (cột kỳ báo cáo gần nhất)
            date_cols = [col for col in df_r.columns if col not in ["item", "item_id"]]
            if date_cols:
                latest_period = date_cols[0] # Kỳ gần nhất (ví dụ '2026-Q1')
                for _, row in df_r.iterrows():
                    item_id = row["item_id"]
                    val = row[latest_period]
                    try:
                        ratios_dict[item_id] = float(val)
                    except:
                        ratios_dict[item_id] = val
        
        # Cập nhật thông số tài chính cơ bản
        result["financial_metrics"]["roe"] = ratios_dict.get("roe", ratios_dict.get("roe_trailling", 0.0))
        result["financial_metrics"]["pe"] = ratios_dict.get("pe_ratio", 0.0)
        result["financial_metrics"]["pb"] = ratios_dict.get("pb_ratio", 0.0)
        result["financial_metrics"]["net_margin"] = ratios_dict.get("net_margin", 0.0)
        
        # ----------------- C: Current Quarterly Earnings (Tăng trưởng Quý - Max 20đ) -----------------
        score_c = 10
        desc_c = "Tăng trưởng quý trung bình hoặc thiếu dữ liệu"
        q_growth_val = None
        
        df_q = fun.equity(symbol).income_statement(period="quarter", orient="time_series")
        if not df_q.empty and len(df_q) >= 5:
            df_q = df_q.sort_values(by="period").reset_index(drop=True)
            latest_row = df_q.iloc[-1]
            latest_period = latest_row["period"] # e.g. "2026-Q1"
            
            # Tìm kỳ cùng kỳ năm ngoái (ví dụ: 2026-Q1 đối chiếu 2025-Q1)
            match = re.match(r"(\d{4})-Q(\d)", latest_period)
            if match:
                y = int(match.group(1))
                q = int(match.group(2))
                yoy_period = f"{y-1}-Q{q}"
                yoy_df = df_q[df_q["period"] == yoy_period]
                
                if not yoy_df.empty:
                    yoy_row = yoy_df.iloc[0]
                    latest_profit = latest_row["net_profit"]
                    yoy_profit = yoy_row["net_profit"]
                    
                    if yoy_profit > 0:
                        q_growth_val = ((latest_profit - yoy_profit) / yoy_profit) * 100
                        if q_growth_val >= 25.0:
                            score_c = 20
                            desc_c = f"Tăng trưởng LN Quý YoY cực mạnh: +{q_growth_val:.1f}% (Đạt tiêu chuẩn CANSLIM)"
                        elif q_growth_val >= 15.0:
                            score_c = 15
                            desc_c = f"Tăng trưởng LN Quý YoY tốt: +{q_growth_val:.1f}%"
                        elif q_growth_val >= 0:
                            score_c = 10
                            desc_c = f"Tăng trưởng LN Quý YoY dương nhưng yếu: +{q_growth_val:.1f}%"
                        else:
                            score_c = 0
                            desc_c = f"LN Quý YoY suy giảm: {q_growth_val:.1f}% (Cảnh báo)"
                    else:
                        q_growth_val = 100.0 if latest_profit > 0 else 0.0
                        score_c = 10
                        desc_c = "Lợi nhuận cùng kỳ năm ngoái âm, LN quý này đã dương trở lại."
        
        result["details"]["C"] = {"score": score_c, "desc": desc_c, "value": q_growth_val}
        
        # ----------------- A: Annual Earnings Growth (Tăng trưởng Năm & ROE - Max 20đ) -----------------
        score_a = 10
        desc_a = "ROE ở mức trung bình hoặc thiếu dữ liệu"
        a_growth_val = None
        
        df_a = fun.equity(symbol).income_statement(period="year", orient="time_series")
        # Tính tăng trưởng năm
        if not df_a.empty and len(df_a) >= 2:
            df_a = df_a.sort_values(by="period").reset_index(drop=True)
            latest_year_profit = df_a.iloc[-1]["net_profit"]
            prev_year_profit = df_a.iloc[-2]["net_profit"]
            if prev_year_profit > 0:
                a_growth_val = ((latest_year_profit - prev_year_profit) / prev_year_profit) * 100
        
        # Tính điểm dựa trên ROE và Tăng trưởng năm
        roe_val = result["financial_metrics"]["roe"]
        
        # Điểm ROE (Max 10đ)
        sub_roe_score = 2
        if roe_val >= 15.0:
            sub_roe_score = 10
        elif roe_val >= 10.0:
            sub_roe_score = 6
            
        # Điểm tăng trưởng năm (Max 10đ)
        sub_a_score = 5
        if a_growth_val is not None:
            if a_growth_val >= 15.0:
                sub_a_score = 10
            elif a_growth_val >= 0:
                sub_a_score = 5
            else:
                sub_a_score = 0
                
        score_a = sub_roe_score + sub_a_score
        desc_a = f"ROE: {roe_val:.1f}% (Yêu cầu >=15%). Tăng trưởng LN Năm: {f'+{a_growth_val:.1f}%' if a_growth_val is not None else 'N/A'}"
        result["details"]["A"] = {"score": score_a, "desc": desc_a, "value": {"roe": roe_val, "growth": a_growth_val}}
        
        # ----------------- N: New Highs / New Products (Giá gần đỉnh - Max 15đ) -----------------
        score_n = 5
        desc_n = "Giá ở xa đỉnh 52 tuần"
        dist_from_high = None
        
        df_ohlcv = get_stock_ohlcv(symbol, length=260) # 260 phiên là 1 năm
        if not df_ohlcv.empty:
            high_52w = df_ohlcv["high"].max()
            current_price = df_ohlcv.iloc[-1]["close"]
            dist_from_high = ((high_52w - current_price) / high_52w) * 100
            
            if dist_from_high <= 15.0:
                score_n = 15
                desc_n = f"Giá đang sát đỉnh 52 tuần (Cách đỉnh {dist_from_high:.1f}%) - Cơ hội Breakout"
            elif dist_from_high <= 30.0:
                score_n = 10
                desc_n = f"Giá tích lũy kênh trên (Cách đỉnh {dist_from_high:.1f}%)"
            else:
                score_n = 3
                desc_n = f"Giá đang nằm sâu dưới đỉnh 52 tuần (Cách đỉnh {dist_from_high:.1f}%) - Yếu"
                
        result["details"]["N"] = {"score": score_n, "desc": desc_n, "value": dist_from_high}
        
        # ----------------- S: Supply and Demand (Thanh khoản khớp lệnh - Max 15đ) -----------------
        score_s = 10
        desc_s = "Thanh khoản khớp lệnh trung bình"
        vol_ratio = None
        
        if not df_ohlcv.empty:
            vol_last = df_ohlcv.iloc[-1]["volume"]
            vol_sma20 = df_ohlcv["volume"].tail(20).mean()
            vol_ratio = vol_last / vol_sma20 if vol_sma20 > 0 else 1.0
            
            if vol_ratio >= 1.5:
                score_s = 15
                desc_s = f"Khối lượng đột biến: Gấp {vol_ratio:.1f} lần trung bình 20 phiên (Dòng tiền lớn vào)"
            elif vol_ratio >= 1.0:
                score_s = 10
                desc_s = f"Thanh khoản duy trì ổn định: Gấp {vol_ratio:.1f} lần trung bình"
            else:
                score_s = 5
                desc_s = f"Thanh khoản ảm đạm: Chỉ bằng {vol_ratio*100:.1f}% trung bình"
                
        result["details"]["S"] = {"score": score_s, "desc": desc_s, "value": vol_ratio}
        
        # ----------------- L: Leader or Laggard (Độ khỏe so với VNINDEX - Max 15đ) -----------------
        score_l = 10
        desc_l = "Sức mạnh tương đối tương đương thị trường"
        rel_strength = None
        
        df_vnindex = get_vnindex_data(market)
        if not df_ohlcv.empty and not df_vnindex.empty and len(df_ohlcv) >= 60:
            # Tính hiệu suất 3 tháng qua (60 phiên)
            stock_ret = ((df_ohlcv.iloc[-1]["close"] - df_ohlcv.iloc[-60]["close"]) / df_ohlcv.iloc[-60]["close"]) * 100
            vnindex_ret = ((df_vnindex.iloc[-1]["close"] - df_vnindex.iloc[-60]["close"]) / df_vnindex.iloc[-60]["close"]) * 100
            rel_strength = stock_ret - vnindex_ret
            
            if rel_strength >= 15.0:
                score_l = 15
                desc_l = f"Cổ phiếu Dẫn dắt (Leader): Hiệu suất vượt VNINDEX +{rel_strength:.1f}% trong 3 tháng"
            elif rel_strength >= 0.0:
                score_l = 10
                desc_l = f"Khỏe hơn thị trường: Hiệu suất vượt VNINDEX +{rel_strength:.1f}%"
            else:
                score_l = 3
                desc_l = f"Cổ phiếu yếu (Laggard): Kém hơn VNINDEX {rel_strength:.1f}%"
                
        result["details"]["L"] = {"score": score_l, "desc": desc_l, "value": rel_strength}
        
        # ----------------- I: Institutional Sponsorship (Khối ngoại / Tổ chức - Max 15đ) -----------------
        score_i = 10
        desc_i = "Giao dịch tổ chức/khối ngoại bình thường"
        foreign_ratio = None
        
        try:
            df_quote = market.equity(symbol).quote()
            if not df_quote.empty:
                f_buy = df_quote.iloc[0].get("foreign_buy_volume", 0)
                f_sell = df_quote.iloc[0].get("foreign_sell_volume", 0)
                total_vol = df_quote.iloc[0].get("volume_accumulated", 1)
                
                f_net = f_buy - f_sell
                foreign_ratio = (f_buy / total_vol) * 100 if total_vol > 0 else 0
                
                # Check beta ổn định
                beta_val = ratios_dict.get("beta", 1.0)
                sub_beta = 5 if (0.7 <= beta_val <= 1.5) else 3
                
                sub_foreign = 5
                if f_net > 0 and foreign_ratio >= 5.0:
                    sub_foreign = 10
                    desc_i = f"Khối ngoại gom ròng mạnh: Chiếm {foreign_ratio:.1f}% tổng KLGD phiên"
                elif f_net > 0:
                    sub_foreign = 7
                    desc_i = "Khối ngoại mua ròng nhẹ"
                elif f_net < 0:
                    sub_foreign = 3
                    desc_i = "Khối ngoại đang bán ròng"
                    
                score_i = sub_beta + sub_foreign
        except Exception as e:
            logger.error(f"Lỗi chấm điểm Institutional cho {symbol}: {e}")
            
        result["details"]["I"] = {"score": score_i, "desc": desc_i, "value": foreign_ratio}
        
        # ----------------- TÍNH ĐIỂM TỔNG CỘNG & XẾP HẠNG -----------------
        total = score_c + score_a + score_n + score_s + score_l + score_i
        result["total_score"] = total
        
        if total >= 80:
            result["rating"] = "SUPERB (Cực kỳ xuất sắc)"
        elif total >= 70:
            result["rating"] = "STRONG (Rất tốt)"
        elif total >= 55:
            result["rating"] = "NEUTRAL (Trung bình)"
        else:
            result["rating"] = "WEAK (Yếu - Tránh mua)"
            
    except Exception as e:
        logger.error(f"Lỗi tổng thể khi chấm điểm CANSLIM cho {symbol}: {e}")
        
    return result
