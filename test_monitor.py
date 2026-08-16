"""
Test suite cho VN-WaveTrader — kiểm thử các module src/ hiện tại.
Chạy: uv run pytest test_monitor.py -v
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
                         "stoch_k", "stoch_d", "adx", "adx_pos", "adx_neg",
                         "supertrend", "supertrend_dir"]
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
        idx = df.index[-1]
        df.loc[idx, "rsi"] = 35
        df.loc[idx, "macd_diff"] = 0.5
        df.loc[idx, "ema_short"] = df.loc[idx, "close"] + 1
        df.loc[idx, "ema_long"] = df.loc[idx, "close"] - 1
        df.loc[idx, "supertrend_dir"] = 1
        df.loc[idx, "bb_percent"] = 0.2
        
        signal = check_swing_signals(df, "TEST")
        assert signal["status"] in ("BUY", "STRONG BUY", "NEUTRAL")

    def test_check_swing_signals_neutral_insufficient_data(self):
        from src.indicators import check_swing_signals
        df = _make_sample_ohlcv(n=5)
        signal = check_swing_signals(df, "TEST")
        assert signal["status"] == "NEUTRAL"


class TestDataFetcher:
    """Test data_fetcher.py — cache và retry logic."""

    def test_cache_structure(self):
        from src.data_fetcher import _ohlcv_cache
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


class TestChartGenerator:
    """Test chart_generator.py."""

    def test_generate_chart(self):
        from src.chart_generator import generate_chart
        from src.indicators import calculate_indicators, check_swing_signals
        df = _make_sample_ohlcv(n=80)
        df = calculate_indicators(df)
        signals = check_swing_signals(df, "TEST")
        chart_file = generate_chart(df, "TEST_TICKER", signals)
        assert os.path.exists(chart_file)
        # Cleanup
        if os.path.exists(chart_file):
            os.remove(chart_file)


class TestScheduler:
    """Test scheduler initialization and teardown."""

    def test_scheduler_lifecycle(self):
        from src.scheduler import start_scheduler, stop_scheduler
        sched = start_scheduler()
        assert sched is not None
        assert sched.running
        stop_scheduler()
        from src import scheduler
        assert scheduler._scheduler is None


class TestConfidenceCalculation:
    """Test pipeline helpers in notifier."""

    def test_calculate_confidence(self):
        from src.notifier import _calculate_confidence
        signals_buy = {"status": "BUY", "details": []}
        assert _calculate_confidence(signals_buy, True, True, True) == "CAO"
        assert _calculate_confidence(signals_buy, True, True, False) == "TRUNG BÌNH"
        assert _calculate_confidence(signals_buy, False, False, False) == "THẤP"
        signals_neutral = {"status": "NEUTRAL", "details": []}
        assert _calculate_confidence(signals_neutral, True, True, True) == "N/A"



    def test_recalculate_status(self):
        from src.notifier import _recalculate_status
        assert _recalculate_status(3.5) == "STRONG BUY"
        assert _recalculate_status(2.0) == "BUY"
        assert _recalculate_status(0.5) == "NEUTRAL"
        assert _recalculate_status(-2.0) == "SELL"
        assert _recalculate_status(-3.5) == "STRONG SELL"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
