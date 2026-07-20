"""
Shared fixtures for the backend test suite.

The real options_data/ tree is multi-GB and daily-only, so tests build small
synthetic Parquet datasets that follow the canonical schema from PLAN.md.
"""
import sys
from datetime import date, time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.data_loader import DataLoader  # noqa: E402

CANONICAL_COLUMNS = [
    "date", "timestamp", "underlying", "expiry", "strike", "option_type",
    "open", "high", "low", "close", "volume", "oi", "settle_price",
    "source", "granularity",
]

SPOT = 20000.0
STRIKES = [19800.0, 19900.0, 20000.0, 20100.0, 20200.0]
# Enough candles to exercise a 09:20 entry and a 15:15 square-off.
INTRADAY_TIMES = [time(9, 15), time(9, 20), time(12, 0), time(15, 15), time(15, 30)]


def _price(strike: float, option_type: str, spot: float = SPOT) -> float:
    """Intrinsic + flat 100 of time value, so put-call parity recovers `spot`."""
    intrinsic = max(spot - strike, 0.0) if option_type == "CE" else max(strike - spot, 0.0)
    return round(intrinsic + 100.0, 2)


def _make_rows(days, times, expiry, granularity, underlying, spot=SPOT):
    rows = []
    for d in days:
        for t in times:
            ts = pd.Timestamp.combine(pd.Timestamp(d), t)
            for strike in STRIKES:
                for opt in ("CE", "PE"):
                    close = _price(strike, opt, spot)
                    rows.append({
                        "date": pd.Timestamp(d),
                        "timestamp": ts,
                        "underlying": underlying,
                        "expiry": str(expiry),
                        "strike": strike,
                        "option_type": opt,
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "volume": 1000.0,
                        "oi": 5000.0,
                        "settle_price": close,
                        "source": "synthetic",
                        "granularity": granularity,
                    })
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    """
    Build a synthetic options_data/parsed tree containing:
      - SYNTH  (upstox_intraday, 1min, real intraday clock) -> tradeable
      - DAILY  (historical_daily, 1d, midnight timestamps)  -> no intraday clock
      - BARE   (historical_daily, missing close/granularity) -> degenerate schema
    """
    base = tmp_path_factory.mktemp("parsed")

    days = [date(2024, 1, 2), date(2024, 1, 3)]
    expiry = date(2024, 1, 25)

    intraday_dir = base / "upstox_intraday" / "SYNTH"
    intraday_dir.mkdir(parents=True)
    _make_rows(days, INTRADAY_TIMES, expiry, "1min", "SYNTH").to_parquet(
        intraday_dir / "SYNTH_2024.parquet", index=False
    )

    daily_dir = base / "historical_daily" / "DAILY"
    daily_dir.mkdir(parents=True)
    _make_rows(days, [time(0, 0)], expiry, "1d", "DAILY").to_parquet(
        daily_dir / "DAILY_2024.parquet", index=False
    )

    # Mirrors the real FAKEIDX fixture: no close/open/high/low/timestamp/granularity.
    bare_dir = base / "historical_daily" / "BARE"
    bare_dir.mkdir(parents=True)
    pd.DataFrame([
        {"date": "2024-01-02", "expiry": "2024-01-25", "strike": s,
         "option_type": o, "volume": 10, "oi": 10}
        for s in STRIKES for o in ("CE", "PE")
    ]).to_parquet(bare_dir / "BARE_2024.parquet", index=False)

    return base


@pytest.fixture
def loader(data_dir) -> DataLoader:
    return DataLoader(str(data_dir))


@pytest.fixture
def client(data_dir, monkeypatch):
    """TestClient with the API's module-level loader pointed at synthetic data."""
    from fastapi.testclient import TestClient

    import backend.api as api_module

    monkeypatch.setattr(api_module, "loader", DataLoader(str(data_dir)))
    return TestClient(api_module.app)
