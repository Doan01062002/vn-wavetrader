import sys
import os

# Add parent dir to path
sys.path.append(os.getcwd())

from src.data_fetcher import get_stock_ohlcv, get_vn30_symbols, get_stock_news, get_intraday_flow
from src.indicators import calculate_indicators, check_swing_signals, find_support_resistance

print("=== KIỂM TRA HỆ THỐNG VN-WAVETRADER (PHIÊN BẢN NÂNG CẤP) ===")

print("\n1. Kiểm tra lấy danh sách VN30:")
try:
    vn30 = get_vn30_symbols()
    print("Thành công! Số lượng mã:", len(vn30))
    print("Một số mã tiêu biểu:", vn30[:5])
except Exception as e:
    print("LỖI:", e)

print("\n2. Kiểm tra tải tin tức doanh nghiệp (FPT):")
try:
    news = get_stock_news("FPT", limit=3)
    print("Thành công! Số lượng tin tải được:", len(news))
    for i, n in enumerate(news):
        print(f"  [{i+1}] ({n['time']}): {n['title'][:60]}...")
except Exception as e:
    print("LỖI:", e)

print("\n3. Kiểm tra phân tích dòng tiền trong phiên (FPT):")
try:
    flow = get_intraday_flow("FPT")
    print("Thành công!")
    print(f"  - Tổng KL khớp: {flow['total_volume']:,} cổ phiếu")
    print(f"  - Tỷ lệ Mua chủ động: {flow['ratio_buy']*100:.1f}%")
    print(f"  - Số lệnh Cá mập Mua: {flow['large_buy_count']} | Bán: {flow['large_sell_count']}")
    print(f"  - Tỷ lệ dòng tiền Cá mập: {flow['ratio_large']*100:.1f}%")
except Exception as e:
    print("LỖI:", e)

print("\n4. Kiểm tra tải dữ liệu lịch sử và tính chỉ báo nâng cao (FPT):")
try:
    df = get_stock_ohlcv("FPT", length=100)
    if not df.empty:
        df_ind = calculate_indicators(df)
        print("Thành công!")
        print("  - Đã tính các chỉ báo cơ bản:")
        print("    Cột:", [col for col in ['rsi', 'macd', 'ema_short'] if col in df_ind.columns])
        print("  - Đã tính chỉ báo SuperTrend:")
        print("    Cột:", [col for col in ['supertrend', 'supertrend_dir'] if col in df_ind.columns])
        print("    Giá trị SuperTrend nến cuối:", df_ind.iloc[-1]['supertrend'])
        
        print("\n5. Kiểm tra tự động tính Hỗ trợ/Kháng cự (FPT):")
        sr = find_support_resistance(df_ind)
        print(f"  - Mức Hỗ trợ cứng: {sr['support']}")
        print(f"  - Mức Kháng cự cứng: {sr['resistance']}")
        
        print("\n6. Kiểm tra quét tín hiệu lướt sóng tổng hợp:")
        signals = check_swing_signals(df_ind)
        print(f"  - Trạng thái đề xuất: {signals['status']} (Score: {signals['score']})")
        print("  - Chi tiết tín hiệu:")
        for det in signals['details']:
            print(f"    * {det}")
except Exception as e:
    print("LỖI:", e)
