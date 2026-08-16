import pandas as pd
import numpy as np
import logging
from pypfopt import expected_returns, risk_models
from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt.hierarchical_portfolio import HRPOpt

logger = logging.getLogger(__name__)

def optimize_portfolio(prices_df: pd.DataFrame, target_symbols: list, method: str = 'hrp') -> tuple:
    """
    Tá»‘i Æ°u hĂ³a tá»· trá»ng danh má»¥c Ä‘áº§u tÆ° báº±ng PyPortfolioOpt.
    Tráº£ vá»: (dict_weights, dict_performance)
    """
    if len(target_symbols) < 2:
        # Náº¿u chá»‰ cĂ³ 1 mĂ£ hoáº·c khĂ´ng cĂ³ mĂ£ nĂ o, phĂ¢n bá»• 100% hoáº·c 0%
        if len(target_symbols) == 1:
            return {target_symbols[0]: 1.0}, {"expected_return": None, "volatility": None, "sharpe": None}
        return {}, {}
        
    try:
        # Lá»c dá»¯ liá»‡u giĂ¡ cá»§a cĂ¡c mĂ£ Ä‘Ă­ch
        available_cols = [col for col in target_symbols if col in prices_df.columns]
        if len(available_cols) < 2:
            if len(available_cols) == 1:
                return {available_cols[0]: 1.0}, {"expected_return": None, "volatility": None, "sharpe": None}
            return {}, {}
            
        df_prices = prices_df[available_cols].dropna()
        if len(df_prices) < 20:
            logger.warning("Dá»¯ liá»‡u giĂ¡ lá»‹ch sá»­ quĂ¡ ngáº¯n Ä‘á»ƒ cháº¡y tá»‘i Æ°u danh má»¥c.")
            # PhĂ¢n bá»• Ä‘á»u máº·c Ä‘á»‹nh
            equal_weight = 1.0 / len(available_cols)
            return {sym: equal_weight for sym in available_cols}, {}
            
        if method == 'hrp':
            # Hierarchical Risk Parity (PhĂ¢n bá»• rá»§i ro phĂ¢n táº§ng) - Cá»±c tá»‘t cho lÆ°á»›t sĂ³ng vĂ¬ khĂ´ng yĂªu cáº§u dá»± bĂ¡o lá»£i nhuáº­n ká»³ vá»ng (vá»‘n ráº¥t khĂ³ dá»± bĂ¡o ngáº¯n háº¡n)
            returns = df_prices.pct_change().dropna()
            hrp = HRPOpt(returns)
            weights = hrp.optimize()
            clean_weights = hrp.clean_weights()
            
            # TĂ­nh hiá»‡u suáº¥t danh má»¥c
            try:
                perf = hrp.portfolio_performance(verbose=False)
                performance = {
                    "expected_return": perf[0],
                    "volatility": perf[1],
                    "sharpe": perf[2]
                }
            except Exception as perf_e:
                logger.warning(f"KhĂ´ng thá»ƒ tĂ­nh toĂ¡n hiá»‡u suáº¥t danh má»¥c HRP: {perf_e}")
                performance = {}
                
            return dict(clean_weights), performance
            
        elif method == 'min_volatility':
            # Tá»‘i thiá»ƒu hĂ³a biáº¿n Ä‘á»™ng (Minimum Variance)
            # TĂ­nh lá»£i nhuáº­n trung bĂ¬nh lá»‹ch sá»­ vĂ  ma tráº­n hiá»‡p biáº¿n
            mu = expected_returns.mean_historical_return(df_prices)
            S = risk_models.sample_cov(df_prices)
            
            ef = EfficientFrontier(mu, S)
            # Tá»‘i thiá»ƒu hĂ³a biáº¿n Ä‘á»™ng
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
                logger.warning(f"KhĂ´ng thá»ƒ tĂ­nh toĂ¡n hiá»‡u suáº¥t danh má»¥c Min Vol: {perf_e}")
                performance = {}
                
            return dict(clean_weights), performance
            
        elif method == 'max_sharpe':
            # Tá»‘i Ä‘a hĂ³a Sharpe ratio (Mean-Variance Optimization)
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
                logger.warning(f"Lá»—i khi tá»‘i Æ°u Max Sharpe (cĂ³ thá»ƒ do ma tráº­n khĂ´ng xĂ¡c Ä‘á»‹nh dÆ°Æ¡ng): {e}. Fallback vá» HRP.")
                return optimize_portfolio(prices_df, target_symbols, method='hrp')
                
    except Exception as e:
        logger.error(f"Lá»—i trong quĂ¡ trĂ¬nh tá»‘i Æ°u danh má»¥c: {e}")
        # Tráº£ vá» phĂ¢n bá»• Ä‘á»u náº¿u gáº·p lá»—i
        equal_weight = 1.0 / len(target_symbols)
        return {sym: equal_weight for sym in target_symbols}, {}
        
if __name__ == "__main__":
    # Test thá»­ vá»›i dá»¯ liá»‡u giáº£ láº­p
    np.random.seed(42)
    dates = pd.date_range(start="2025-01-01", periods=100)
    data = {
        "FPT": 100 + np.cumsum(np.random.normal(0.1, 1.0, 100)),
        "HPG": 50 + np.cumsum(np.random.normal(0.05, 0.8, 100)),
        "SSI": 30 + np.cumsum(np.random.normal(0.08, 1.2, 100))
    }
    df = pd.DataFrame(data, index=dates)
    w, perf = optimize_portfolio(df, ["FPT", "HPG", "SSI"], method='hrp')
    print("Trá»ng sá»‘ tá»‘i Æ°u HRP:")
    print(w)
    print("Hiá»‡u suáº¥t:")
    print(perf)
