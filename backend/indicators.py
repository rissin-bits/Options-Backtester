"""
indicators.py — Technical indicator library for options backtesting.

All functions operate on pandas Series/DataFrames and return Series.
Designed for both batch computation (full history) and incremental updates.
"""
import numpy as np
import pandas as pd
from typing import Optional, Tuple


# ──────────────────────────────────────────────────────────────
# Moving Averages
# ──────────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted Moving Average — recent values get more weight."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(window=period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


# ──────────────────────────────────────────────────────────────
# Oscillators
# ──────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    """Stochastic Oscillator (%K and %D)."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100.0 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(window=d_period).mean()
    return k, d


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 14) -> pd.Series:
    """Williams %R."""
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    return -100.0 * (highest_high - close) / (highest_high - lowest_low).replace(0, np.nan)


def cci(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma_tp) / (0.015 * mad).replace(0, np.nan)


# ──────────────────────────────────────────────────────────────
# Trend Indicators
# ──────────────────────────────────────────────────────────────

def macd(series: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD — returns (macd_line, signal_line, histogram).
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    """
    SuperTrend indicator.
    Returns (supertrend_line, direction) where direction is 1 (bullish) or -1 (bearish).
    """
    atr_val = atr(high, low, close, period)
    hl2 = (high + low) / 2.0

    upper_band = hl2 + multiplier * atr_val
    lower_band = hl2 - multiplier * atr_val

    st = pd.Series(np.nan, index=close.index)
    direction = pd.Series(1, index=close.index)

    for i in range(period, len(close)):
        if i == period:
            st.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = -1
            continue

        if close.iloc[i] > st.iloc[i - 1]:
            st.iloc[i] = max(lower_band.iloc[i],
                             st.iloc[i - 1] if direction.iloc[i - 1] == 1 else lower_band.iloc[i])
            direction.iloc[i] = 1
        else:
            st.iloc[i] = min(upper_band.iloc[i],
                             st.iloc[i - 1] if direction.iloc[i - 1] == -1 else upper_band.iloc[i])
            direction.iloc[i] = -1

    return st, direction


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Average Directional Index.
    Returns (adx, plus_di, minus_di).
    """
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).where((high - prev_high) > (prev_low - low), 0.0).clip(lower=0)
    minus_dm = (prev_low - low).where((prev_low - low) > (high - prev_high), 0.0).clip(lower=0)

    atr_val = atr(high, low, close, period)

    plus_di = 100.0 * ema(plus_dm, period) / atr_val.replace(0, np.nan)
    minus_di = 100.0 * ema(minus_dm, period) / atr_val.replace(0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = ema(dx, period)

    return adx_val, plus_di, minus_di


# ──────────────────────────────────────────────────────────────
# Volatility
# ──────────────────────────────────────────────────────────────

def bollinger_bands(series: pd.Series, period: int = 20,
                    num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands — returns (upper, middle, lower).
    """
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def keltner_channels(high: pd.Series, low: pd.Series, close: pd.Series,
                     ema_period: int = 20, atr_period: int = 10,
                     multiplier: float = 1.5) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Keltner Channels — returns (upper, middle, lower)."""
    middle = ema(close, ema_period)
    atr_val = atr(high, low, close, atr_period)
    upper = middle + multiplier * atr_val
    lower = middle - multiplier * atr_val
    return upper, middle, lower


def historical_volatility(close: pd.Series, period: int = 20,
                          annualize: bool = True) -> pd.Series:
    """Historical (realized) volatility from log returns."""
    log_returns = np.log(close / close.shift(1))
    vol = log_returns.rolling(window=period).std()
    if annualize:
        vol = vol * np.sqrt(252)  # Annualize assuming 252 trading days
    return vol


# ──────────────────────────────────────────────────────────────
# Volume Indicators
# ──────────────────────────────────────────────────────────────

def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, reset_daily: bool = True,
         dates: Optional[pd.Series] = None) -> pd.Series:
    """
    Volume-Weighted Average Price.
    If reset_daily=True, resets at the start of each trading day.
    """
    tp = (high + low + close) / 3.0
    tp_vol = tp * volume

    if reset_daily and dates is not None:
        cum_tp_vol = tp_vol.groupby(dates).cumsum()
        cum_vol = volume.groupby(dates).cumsum()
    else:
        cum_tp_vol = tp_vol.cumsum()
        cum_vol = volume.cumsum()

    return cum_tp_vol / cum_vol.replace(0, np.nan)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff())
    direction.iloc[0] = 0
    return (volume * direction).cumsum()


def mfi(high: pd.Series, low: pd.Series, close: pd.Series,
        volume: pd.Series, period: int = 14) -> pd.Series:
    """Money Flow Index — volume-weighted RSI."""
    tp = (high + low + close) / 3.0
    mf = tp * volume
    tp_diff = tp.diff()

    positive_mf = mf.where(tp_diff > 0, 0.0).rolling(period).sum()
    negative_mf = mf.where(tp_diff <= 0, 0.0).rolling(period).sum()

    mfi_ratio = positive_mf / negative_mf.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + mfi_ratio))


# ──────────────────────────────────────────────────────────────
# Options-Specific Indicators
# ──────────────────────────────────────────────────────────────

def put_call_ratio(put_volume: pd.Series, call_volume: pd.Series) -> pd.Series:
    """Put-Call Ratio from volumes."""
    return put_volume / call_volume.replace(0, np.nan)


def put_call_oi_ratio(put_oi: pd.Series, call_oi: pd.Series) -> pd.Series:
    """Put-Call OI Ratio."""
    return put_oi / call_oi.replace(0, np.nan)


def iv_percentile(iv_series: pd.Series, lookback: int = 252) -> pd.Series:
    """
    IV Percentile — what percentage of the past `lookback` days had
    a lower IV than the current level.
    """
    return iv_series.rolling(window=lookback).apply(
        lambda x: (x[-1] > x[:-1]).mean() * 100, raw=True
    )


def iv_rank(iv_series: pd.Series, lookback: int = 252) -> pd.Series:
    """
    IV Rank — current IV position relative to the min/max range
    over the lookback period.
    """
    rolling_min = iv_series.rolling(window=lookback).min()
    rolling_max = iv_series.rolling(window=lookback).max()
    range_val = rolling_max - rolling_min
    return ((iv_series - rolling_min) / range_val.replace(0, np.nan)) * 100


# ──────────────────────────────────────────────────────────────
# Indicator Registry — for GUI builder
# ──────────────────────────────────────────────────────────────

INDICATOR_REGISTRY = {
    # name -> (function, parameter_defaults, description)
    "SMA": {
        "func": sma,
        "params": {"period": 20},
        "inputs": ["close"],
        "description": "Simple Moving Average",
    },
    "EMA": {
        "func": ema,
        "params": {"period": 20},
        "inputs": ["close"],
        "description": "Exponential Moving Average",
    },
    "RSI": {
        "func": rsi,
        "params": {"period": 14},
        "inputs": ["close"],
        "description": "Relative Strength Index (0-100)",
    },
    "MACD": {
        "func": macd,
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "inputs": ["close"],
        "outputs": ["macd_line", "signal_line", "histogram"],
        "description": "Moving Average Convergence Divergence",
    },
    "ATR": {
        "func": atr,
        "params": {"period": 14},
        "inputs": ["high", "low", "close"],
        "description": "Average True Range",
    },
    "Bollinger Bands": {
        "func": bollinger_bands,
        "params": {"period": 20, "num_std": 2.0},
        "inputs": ["close"],
        "outputs": ["upper", "middle", "lower"],
        "description": "Bollinger Bands (upper/middle/lower)",
    },
    "SuperTrend": {
        "func": supertrend,
        "params": {"period": 10, "multiplier": 3.0},
        "inputs": ["high", "low", "close"],
        "outputs": ["line", "direction"],
        "description": "SuperTrend trend-following indicator",
    },
    "VWAP": {
        "func": vwap,
        "params": {"reset_daily": True},
        "inputs": ["high", "low", "close", "volume"],
        "description": "Volume-Weighted Average Price",
    },
    "Stochastic": {
        "func": stochastic,
        "params": {"k_period": 14, "d_period": 3},
        "inputs": ["high", "low", "close"],
        "outputs": ["k", "d"],
        "description": "Stochastic Oscillator (%K, %D)",
    },
    "ADX": {
        "func": adx,
        "params": {"period": 14},
        "inputs": ["high", "low", "close"],
        "outputs": ["adx", "plus_di", "minus_di"],
        "description": "Average Directional Index",
    },
    "OBV": {
        "func": obv,
        "params": {},
        "inputs": ["close", "volume"],
        "description": "On-Balance Volume",
    },
    "MFI": {
        "func": mfi,
        "params": {"period": 14},
        "inputs": ["high", "low", "close", "volume"],
        "description": "Money Flow Index (volume-weighted RSI)",
    },
    "Historical Volatility": {
        "func": historical_volatility,
        "params": {"period": 20, "annualize": True},
        "inputs": ["close"],
        "description": "Annualized historical (realized) volatility",
    },
    "Put-Call Ratio": {
        "func": put_call_ratio,
        "params": {},
        "inputs": ["put_volume", "call_volume"],
        "description": "Put-Call Volume Ratio",
    },
}
