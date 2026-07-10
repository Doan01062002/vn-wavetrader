import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = "virtual_portfolio.json"

def init_portfolio():
    """Khởi tạo tài khoản ví ảo với 100 triệu VNĐ mặc định."""
    return {
        "cash": 100000000.0,  # 100 triệu VNĐ
        "positions": [],      # Danh sách vị thế đang nắm giữ
        "history": []         # Lịch sử giao dịch đã đóng
    }

from src.database import load_portfolio_data, save_portfolio_data

def load_portfolio() -> dict:
    """Tải dữ liệu ví ảo từ Database hoặc JSON dự phòng."""
    return load_portfolio_data()

def save_portfolio(portfolio: dict):
    """Lưu dữ liệu ví ảo lên Database hoặc JSON dự phòng."""
    save_portfolio_data(portfolio)

def get_atr_for_symbol(symbol: str) -> float:
    """Tính toán ATR của cổ phiếu 20 phiên gần nhất."""
    try:
        from src.data_fetcher import get_stock_ohlcv
        from src.indicators import calculate_indicators
        df = get_stock_ohlcv(symbol, length=100)
        if not df.empty:
            df = calculate_indicators(df, symbol=symbol)
            if 'atr' in df.columns and not df['atr'].empty:
                return float(df['atr'].iloc[-1])
    except Exception as e:
        logger.error(f"Lỗi tính ATR cho {symbol}: {e}")
    return 0.0

def buy_stock(symbol: str, price: float, quantity: int, stop_loss: float = None, take_profit: float = None) -> dict:
    """
    Thực hiện lệnh Mua ảo.
    Lưu ý: Giá cổ phiếu trên VNSTOCK đơn vị là nghìn VNĐ (Ví dụ: FPT giá 135.0 = 135,000 VNĐ)
    Nên tổng giá trị giao dịch = price * quantity * 1000
    """
    portfolio = load_portfolio()
    cost = price * quantity * 1000
    
    if portfolio["cash"] < cost:
        return {"success": False, "message": f"Không đủ tiền mặt để mua! Chi phí: {cost:,.0f}đ | Tiền mặt có sẵn: {portfolio['cash']:,.0f}đ"}
        
    portfolio["cash"] -= cost
    
    # Tính toán chốt lời/cắt lỗ theo ATR nếu không truyền vào
    if stop_loss is None or take_profit is None:
        atr = get_atr_for_symbol(symbol)
        if atr > 0:
            if stop_loss is None:
                stop_loss = round(price - 2 * atr, 2)
            if take_profit is None:
                take_profit = round(price + 4 * atr, 2)
        else:
            # Fallback về tỉ lệ phần trăm mặc định (-6% / +15%)
            if stop_loss is None:
                stop_loss = round(price * 0.94, 2)
            if take_profit is None:
                take_profit = round(price * 1.15, 2)
                
    # Kiểm tra xem đã có vị thế của mã này chưa để cộng dồn giá trung bình
    existing_pos = None
    for pos in portfolio["positions"]:
        if pos["symbol"] == symbol:
            existing_pos = pos
            break
            
    if existing_pos:
        # Tính toán giá trung bình mới
        total_qty = existing_pos["quantity"] + quantity
        total_cost = (existing_pos["buy_price"] * existing_pos["quantity"] * 1000) + cost
        existing_pos["buy_price"] = (total_cost / total_qty) / 1000
        existing_pos["quantity"] = total_qty
        # Cập nhật chốt lời/cắt lỗ mới nếu được cung cấp
        if stop_loss is not None:
            existing_pos["stop_loss"] = stop_loss
        if take_profit is not None:
            existing_pos["take_profit"] = take_profit
        # Reset highest_price về giá mua trung bình mới
        existing_pos["highest_price"] = existing_pos["buy_price"]
    else:
        new_pos = {
            "symbol": symbol,
            "buy_price": price,
            "quantity": quantity,
            "buy_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "highest_price": price
        }
        portfolio["positions"].append(new_pos)
        
    save_portfolio(portfolio)
    return {"success": True, "message": f"Mua ảo thành công {quantity:,} cổ phiếu {symbol} tại giá {price:,.2f} (Tổng: {cost:,.0f}đ)"}

def sell_stock(symbol: str, price: float, quantity: int, reason: str = "MANUAL") -> dict:
    """Thực hiện lệnh Bán ảo."""
    portfolio = load_portfolio()
    
    target_pos = None
    for pos in portfolio["positions"]:
        if pos["symbol"] == symbol:
            target_pos = pos
            break
            
    if not target_pos:
        return {"success": False, "message": f"Bạn không nắm giữ cổ phiếu {symbol} trong danh mục ảo!"}
        
    if target_pos["quantity"] < quantity:
        return {"success": False, "message": f"Số lượng nắm giữ không đủ để bán! Nắm giữ: {target_pos['quantity']:,} | Cần bán: {quantity:,}"}
        
    revenue = price * quantity * 1000
    cost = target_pos["buy_price"] * quantity * 1000
    pnl_amount = revenue - cost
    pnl_percent = ((price - target_pos["buy_price"]) / target_pos["buy_price"]) * 100
    
    # Cập nhật tiền mặt
    portfolio["cash"] += revenue
    
    # Cập nhật số lượng nắm giữ hoặc xóa vị thế
    if target_pos["quantity"] == quantity:
        portfolio["positions"].remove(target_pos)
    else:
        target_pos["quantity"] -= quantity
        
    # Ghi nhận lịch sử giao dịch
    history_entry = {
        "symbol": symbol,
        "buy_price": target_pos["buy_price"],
        "sell_price": price,
        "quantity": quantity,
        "buy_date": target_pos["buy_date"],
        "sell_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pnl_amount": pnl_amount,
        "pnl_percent": pnl_percent,
        "reason": reason
    }
    portfolio["history"].append(history_entry)
    
    save_portfolio(portfolio)
    return {
        "success": True, 
        "message": f"Bán ảo thành công {quantity:,} {symbol} tại giá {price:,.2f} ({reason}). Lãi/Lỗ: {pnl_amount:+,.0f}đ ({pnl_percent:+.2f}%)",
        "pnl_amount": pnl_amount,
        "pnl_percent": pnl_percent
    }

def check_and_execute_auto_orders(current_prices: dict) -> list:
    """
    Quét danh mục và tự động kích hoạt lệnh bán khi chạm chốt lời hoặc cắt lỗ.
    Hàm này được gọi từ background monitor.
    Trả về danh sách các tin nhắn cảnh báo để gửi Telegram.
    """
    portfolio = load_portfolio()
    triggered_alerts = []
    
    # Để tránh sửa đổi danh sách đang duyệt, tạo một bản sao của positions
    positions_to_check = list(portfolio["positions"])
    
    for pos in positions_to_check:
        sym = pos["symbol"]
        if sym in current_prices:
            curr_price = current_prices[sym]
            
            # 1. Cập nhật Trailing Stop-loss (Chặn lãi động)
            if "highest_price" not in pos:
                pos["highest_price"] = pos["buy_price"]
                
            if curr_price > pos["highest_price"]:
                pos["highest_price"] = curr_price
                new_sl = round(curr_price * 0.95, 2)  # Dừng lỗ kéo theo cách đỉnh 5%
                if new_sl > (pos.get("stop_loss") or 0):
                    pos["stop_loss"] = new_sl
                    alert = f"🔄 *[VÍ ẢO - CHẶN LÃI ĐỘNG]* 🔄\n" \
                            f"Nâng dừng lỗ vị thế **{sym}** lên **{new_sl:.2f}** (Giá đỉnh mới: **{curr_price:.2f}**)"
                    triggered_alerts.append(alert)
                    
                    # Đồng bộ thay đổi vào portfolio chính
                    for p_orig in portfolio["positions"]:
                        if p_orig["symbol"] == sym:
                            p_orig["highest_price"] = curr_price
                            p_orig["stop_loss"] = new_sl
                            break
                    save_portfolio(portfolio)
            
            # 2. Kiểm tra Cắt lỗ cứng (hoặc chặn lãi động vừa cập nhật)
            if pos.get("stop_loss") and curr_price <= pos["stop_loss"]:
                res = sell_stock(sym, curr_price, pos["quantity"], reason="CẮT LỖ (Stop-loss)")
                if res["success"]:
                    portfolio = load_portfolio()  # Nạp lại để đồng bộ số dư tiền mặt
                    alert = f"⚠️ *[VÍ ẢO - CẮT LỖ]*\n🔥 Đã tự động BÁN toàn bộ vị thế *{sym}* do giá chạm ngưỡng cắt lỗ!\n" \
                            f"- Số lượng: {pos['quantity']:,} cp\n" \
                            f"- Giá mua TB: {pos['buy_price']:.2f}\n" \
                            f"- Giá bán khớp: {curr_price:.2f} (SL: {pos['stop_loss']:.2f})\n" \
                            f"- Hiệu suất: *{res['pnl_percent']:.2f}%* ({res['pnl_amount']:+,.0f}đ)"
                    triggered_alerts.append(alert)
                    
            # 3. Kiểm tra Chốt lời (Scaling Out - Chốt lời từng phần)
            elif pos.get("take_profit") and curr_price >= pos["take_profit"]:
                qty = pos["quantity"]
                if qty >= 2 and not pos.get("tp1_triggered"):
                    qty_to_sell = qty // 2
                    res = sell_stock(sym, curr_price, qty_to_sell, reason="CHỐT LỜI 50% (TP1)")
                    if res["success"]:
                        portfolio = load_portfolio()  # Nạp lại để đồng bộ số dư tiền mặt
                        alert = f"🚀 *[VÍ ẢO - CHỐT LỜI 50% (TP1)]* 🚀\n" \
                                f"Đã tự động BÁN chốt lời **50% vị thế** ({qty_to_sell:,} cp) mã **{sym}** tại giá **{curr_price:.2f}**!\n" \
                                f"- Lợi nhuận khóa: *{res['pnl_amount']:+,.0f}đ* ({res['pnl_percent']:+.2f}%)\n" \
                                f"- **50% còn lại** được nâng dừng lỗ về giá vốn **{pos['buy_price']:.2f}** (hòa vốn) và tiếp tục chạy lãi động bằng Trailing Stop-loss!"
                        triggered_alerts.append(alert)
                        
                        # Cập nhật vị thế trong portfolio chính
                        for p_orig in portfolio["positions"]:
                            if p_orig["symbol"] == sym:
                                p_orig["tp1_triggered"] = True
                                p_orig["stop_loss"] = p_orig["buy_price"]  # Nâng dừng lỗ về giá vốn để bảo toàn
                                p_orig["take_profit"] = None  # Để 50% còn lại chạy theo Trailing Stop
                                break
                        save_portfolio(portfolio)
                else:
                    # Nếu số lượng nhỏ hoặc đã kích hoạt chốt lời từng phần, bán toàn bộ
                    res = sell_stock(sym, curr_price, qty, reason="CHỐT LỜI TOÀN BỘ")
                    if res["success"]:
                        portfolio = load_portfolio()  # Nạp lại để đồng bộ số dư tiền mặt
                        alert = f"🚀 *[VÍ ẢO - CHỐT LỜI TOÀN BỘ]* 🚀\n" \
                                f"💰 Đã tự động BÁN toàn bộ vị thế *{sym}* tại giá **{curr_price:.2f}**!\n" \
                                f"- Số lượng: {qty:,} cp\n" \
                                f"- Hiệu suất: *{res['pnl_percent']:+.2f}%* ({res['pnl_amount']:+,.0f}đ)"
                        triggered_alerts.append(alert)
                    
    return triggered_alerts

def calculate_kelly_sizing(symbol: str) -> dict:
    """
    Tính toán tỷ lệ phân bổ đi vốn tối ưu theo công thức Kelly Criterion (áp dụng Half-Kelly làm biên an toàn).
    """
    portfolio = load_portfolio()
    history = portfolio.get("history", [])
    
    # Lọc lịch sử của mã này
    symbol_history = [h for h in history if h["symbol"] == symbol]
    
    # Nếu lịch sử riêng của mã quá ít (<3 lệnh), dùng lịch sử chung của toàn bộ ví làm mốc cơ bản
    active_history = symbol_history if len(symbol_history) >= 3 else history
    
    if not active_history:
        # Nếu chưa có lịch sử nào cả, gợi ý đi vốn 10% mặc định (baseline)
        return {
            "suggested_pct": 10.0,
            "win_rate": 50.0,
            "win_loss_ratio": 1.5,
            "details": "Chưa có đủ lịch sử giao dịch. Đi vốn 10% mặc định."
        }
        
    wins = [h for h in active_history if h["pnl_amount"] > 0]
    losses = [h for h in active_history if h["pnl_amount"] <= 0]
    
    p = len(wins) / len(active_history)
    
    avg_win = sum(h["pnl_percent"] for h in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(h["pnl_percent"] for h in losses) / len(losses)) if losses else 0.0
    
    b = avg_win / avg_loss if avg_loss > 0 else 1.5
    
    # Công thức Kelly: f = p - (1-p)/b
    if b > 0:
        kelly_f = p - ((1 - p) / b)
    else:
        kelly_f = 0.0
        
    # Áp dụng Half-Kelly để bảo vệ rủi ro và giới hạn tối đa 25% danh mục cho 1 mã để phân tán rủi ro
    half_kelly = max(0.0, kelly_f * 0.5)
    suggested_pct = min(0.25, half_kelly) * 100 # Chuyển sang %
    
    # Fallback nếu Kelly âm hoặc quá nhỏ thì gợi ý 5% rủi ro thấp
    if suggested_pct < 5.0:
        suggested_pct = 5.0
        
    return {
        "suggested_pct": round(suggested_pct, 1),
        "win_rate": round(p * 100, 1),
        "win_loss_ratio": round(b, 2),
        "details": f"Dựa trên {len(active_history)} lệnh lịch sử. Win Rate: {p*100:.1f}%, Lãi/Lỗ: {b:.2f}"
    }

def calculate_fixed_risk_qty(symbol: str, price: float, stop_loss: float) -> int:
    """
    Tính số lượng cổ phiếu cần mua sao cho nếu chạm cắt lỗ thì tổng lỗ bằng đúng 2% tài sản ròng (Net Worth).
    Giới hạn làm tròn xuống theo lô 100 cổ phiếu (chuẩn sàn HOSE).
    """
    try:
        portfolio = load_portfolio()
        pos_val = 0.0
        for pos in portfolio.get("positions", []):
            pos_val += pos["quantity"] * pos["buy_price"] * 1000
        net_worth = portfolio["cash"] + pos_val
        
        # Rủi ro cố định = 2% tài sản ròng
        risk_amount = net_worth * 0.02
        
        # Giá trị chênh lệch trên mỗi cổ phiếu (đơn vị: VNĐ)
        price_diff_vnd = (price - stop_loss) * 1000
        
        if price_diff_vnd > 0:
            qty = int(risk_amount // price_diff_vnd)
            # Làm tròn xuống lô 100 cp
            qty = (qty // 100) * 100
            return max(100, qty)
    except Exception as e:
        logging.error(f"Lỗi tính toán số lượng mua theo rủi ro 2% cho {symbol}: {e}")
    return 100
