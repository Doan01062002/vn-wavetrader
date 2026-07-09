import pandas as pd
import numpy as np
import logging
from pypfopt import expected_returns, risk_models
from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt.hierarchical_portfolio import HRPOpt

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def optimize_portfolio(prices_df: pd.DataFrame, target_symbols: list, method: str = 'hrp') -> tuple:
    """
    Tối ưu hóa tỷ trọng danh mục đầu tư bằng PyPortfolioOpt.
    Trả về: (dict_weights, dict_performance)
    """
    if len(target_symbols) < 2:
        # Nếu chỉ có 1 mã hoặc không có mã nào, phân bổ 100% hoặc 0%
        if len(target_symbols) == 1:
            return {target_symbols[0]: 1.0}, {"expected_return": None, "volatility": None, "sharpe": None}
        return {}, {}
        
    try:
        # Lọc dữ liệu giá của các mã đích
        available_cols = [col for col in target_symbols if col in prices_df.columns]
        if len(available_cols) < 2:
            if len(available_cols) == 1:
                return {available_cols[0]: 1.0}, {"expected_return": None, "volatility": None, "sharpe": None}
            return {}, {}
            
        df_prices = prices_df[available_cols].dropna()
        if len(df_prices) < 20:
            logging.warning("Dữ liệu giá lịch sử quá ngắn để chạy tối ưu danh mục.")
            # Phân bổ đều mặc định
            equal_weight = 1.0 / len(available_cols)
            return {sym: equal_weight for sym in available_cols}, {}
            
        if method == 'hrp':
            # Hierarchical Risk Parity (Phân bổ rủi ro phân tầng) - Cực tốt cho lướt sóng vì không yêu cầu dự báo lợi nhuận kỳ vọng (vốn rất khó dự báo ngắn hạn)
            returns = df_prices.pct_change().dropna()
            hrp = HRPOpt(returns)
            weights = hrp.optimize()
            clean_weights = hrp.clean_weights()
            
            # Tính hiệu suất danh mục
            try:
                perf = hrp.portfolio_performance(verbose=False)
                performance = {
                    "expected_return": perf[0],
                    "volatility": perf[1],
                    "sharpe": perf[2]
                }
            except Exception as perf_e:
                logging.warning(f"Không thể tính toán hiệu suất danh mục HRP: {perf_e}")
                performance = {}
                
            return dict(clean_weights), performance
            
        elif method == 'min_volatility':
            # Tối thiểu hóa biến động (Minimum Variance)
            # Tính lợi nhuận trung bình lịch sử và ma trận hiệp biến
            mu = expected_returns.mean_historical_return(df_prices)
            S = risk_models.sample_cov(df_prices)
            
            ef = EfficientFrontier(mu, S)
            # Tối thiểu hóa biến động
            weights = ef.min_volatility()
            clean_weights = ef.clean_weights()
            
            try:
                perf = ef.portfolio_performance(verbose=False)
                performance = {
                    "expected_return": perf[0],
                    "volatility": perf[1],
                    "sharpe": perf[2]
                }
            except Exception as perf_e:
                logging.warning(f"Không thể tính toán hiệu suất danh mục Min Vol: {perf_e}")
                performance = {}
                
            return dict(clean_weights), performance
            
        elif method == 'max_sharpe':
            # Tối đa hóa Sharpe ratio (Mean-Variance Optimization)
            mu = expected_returns.mean_historical_return(df_prices)
            S = risk_models.sample_cov(df_prices)
            
            ef = EfficientFrontier(mu, S)
            try:
                weights = ef.max_sharpe()
                clean_weights = ef.clean_weights()
                perf = ef.portfolio_performance(verbose=False)
                performance = {
                    "expected_return": perf[0],
                    "volatility": perf[1],
                    "sharpe": perf[2]
                }
                return dict(clean_weights), performance
            except Exception as e:
                logging.warning(f"Lỗi khi tối ưu Max Sharpe (có thể do ma trận không xác định dương): {e}. Fallback về HRP.")
                return optimize_portfolio(prices_df, target_symbols, method='hrp')
                
    except Exception as e:
        logging.error(f"Lỗi trong quá trình tối ưu danh mục: {e}")
        # Trả về phân bổ đều nếu gặp lỗi
        equal_weight = 1.0 / len(target_symbols)
        return {sym: equal_weight for sym in target_symbols}, {}
        
if __name__ == "__main__":
    # Test thử với dữ liệu giả lập
    np.random.seed(42)
    dates = pd.date_range(start="2025-01-01", periods=100)
    data = {
        "FPT": 100 + np.cumsum(np.random.normal(0.1, 1.0, 100)),
        "HPG": 50 + np.cumsum(np.random.normal(0.05, 0.8, 100)),
        "SSI": 30 + np.cumsum(np.random.normal(0.08, 1.2, 100))
    }
    df = pd.DataFrame(data, index=dates)
    w, perf = optimize_portfolio(df, ["FPT", "HPG", "SSI"], method='hrp')
    print("Trọng số tối ưu HRP:")
    print(w)
    print("Hiệu suất:")
    print(perf)
