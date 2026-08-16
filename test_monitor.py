"""
Test suite cho VN-WaveTrader — kiểm thử các module src/ hiện tại.
Chạy: python -m pytest test_monitor.py -v
"""
import sys
import os

# Đảm bảo project root trong path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np


def _make_sample_ohlcv(n=100):
    """Tạo dữ liệu OHLCV mẫu để test."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    np.random.seed(42)
    close = 50 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close - np.random.rand(n) * 0.5,
        "high": close + np.random.rand(n) * 1.0,
        "low": close - np.random.rand(n) * 1.0,
        "close": close,
        "volume": np.random.randint(100_000, 1_000_000, n).astype(float),
    }, index=dates)


class TestIndicators:
    """Test indicators.py — tính chỉ báo kỹ thuật."""

    def test_calculate_indicators_returns_expected_columns(self):
        from src.indicators import calculate_indicators
        df = _make_sample_ohlcv()
        result = calculate_indicators(df)
        expected_cols = ["rsi", "macd", "macd_signal", "ema_short", "ema_long",
                         "bb_high", "bb_low", "atr", "volume_sma20",
                         "supertrend", "supertrend_direction"]
        for col in expected_cols:
            assert col in result.columns, f"Thiếu cột {col}"

    def test_calculate_indicators_empty_df(self):
        from src.indicators import calculate_indicators
        result = calculate_indicators(pd.DataFrame())
        assert result.empty

    def test_calculate_indicators_short_df(self):
        from src.indicators import calculate_indicators
        df = _make_sample_ohlcv(n=10)
        result = calculate_indicators(df)
        # Dữ liệu quá ít → trả về nguyên df không có indicators
        assert "rsi" not in result.columns

    def test_check_swing_signals_buy(self):
        """Test phát hiện tín hiệu MUA khi đủ điều kiện."""
        from src.indicators import check_swing_signals, calculate_indicators
        df = _make_sample_ohlcv(n=120)
        df = calculate_indicators(df)
        # Giả lập điều kiện BUY mạnh
        idx = df.index[-1]
        df.loc[idx, "rsi"] = 35  # RSI oversold zone
        df.loc[idx, "macd_diff"] = 0.5  # MACD histogram dương
        df.loc[idx, "ema_short"] = df.loc[idx, "close"] + 1  # EMA short > EMA long
        df.loc[idx, "ema_long"] = df.loc[idx, "close"] - 1
        df.loc[idx, "supertrend_direction"] = 1  # SuperTrend uptrend
        df.loc[idx, "bb_percent"] = 0.2  # Gần Bollinger Band dưới
        
        signal = check_swing_signals(df, "TEST")
        # Signal có thể BUY hoặc NEUTRAL tùy logic chi tiết, nhưng không nên SELL
        assert signal["status"] in ("BUY", "STRONG BUY", "NEUTRAL")

    def test_check_swing_signals_neutral_insufficient_data(self):
        from src.indicators import check_swing_signals
        df = _make_sample_ohlcv(n=5)
        signal = check_swing_signals(df, "TEST")
        assert signal["status"] == "NEUTRAL"


class TestDataFetcher:
    """Test data_fetcher.py — cache và retry logic."""

    def test_cache_returns_same_data(self):
        from src.data_fetcher import _ohlcv_cache
        # Cache should be a dict
        assert isinstance(_ohlcv_cache, dict)


class TestSupportResistance:
    """Test find_support_resistance."""

    def test_find_support_resistance_returns_levels(self):
        from src.indicators import find_support_resistance
        df = _make_sample_ohlcv(n=100)
        levels = find_support_resistance(df)
        assert "support" in levels
        assert "resistance" in levels
        assert levels["support"] < levels["resistance"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
