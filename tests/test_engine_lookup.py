"""
The engine replaced per-candle boolean scans (DataLoader.get_options_chain /
get_option_price, both O(rows) per call) with a binary search over a
timestamp-sorted frame. These pin the fast path to the semantics of the slow
one — equivalence matters more than the speedup, since this feeds fill prices.
"""
from datetime import date

import pandas as pd
import pytest

from backend.engine import BacktestConfig, BacktestEngine


@pytest.fixture
def engine(loader):
    cfg = BacktestConfig(
        underlying="SYNTH",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        granularity="1min",
    )
    eng = BacktestEngine(cfg, loader)
    data = loader.load_data("SYNTH", cfg.start_date, cfg.end_date, granularity="1min")
    eng._index_by_timestamp(data)
    return eng, data, loader


def _timestamps(data):
    return [pd.Timestamp(t) for t in sorted(data["timestamp"].unique())]


def test_chain_at_matches_get_options_chain(engine):
    eng, data, loader = engine
    for ts in _timestamps(data):
        fast = eng._chain_at(ts).reset_index(drop=True)
        slow = loader.get_options_chain(data, ts).reset_index(drop=True)
        pd.testing.assert_frame_equal(fast, slow)


def test_chain_at_ordering_is_expiry_strike_type(engine):
    """ATM selection reads .iloc[0], so row order is load-bearing."""
    eng, data, _ = engine
    chain = eng._chain_at(_timestamps(data)[0])
    expected = chain.sort_values(["expiry", "strike", "option_type"])
    pd.testing.assert_frame_equal(chain, expected)


def test_price_at_matches_get_option_price(engine):
    eng, data, loader = engine
    ts = _timestamps(data)[0]
    for strike in sorted(data["strike"].unique()):
        for opt in ("CE", "PE"):
            fast = eng._price_at(ts, strike, opt, "2024-01-25")
            slow = loader.get_option_price(data, ts, strike, opt, "2024-01-25")
            assert fast == slow


def test_price_at_unknown_contract_is_none(engine):
    eng, data, _ = engine
    ts = _timestamps(data)[0]
    assert eng._price_at(ts, 99999.0, "CE", "2024-01-25") is None
    assert eng._price_at(ts, 20000.0, "XX", "2024-01-25") is None
    assert eng._price_at(ts, 20000.0, "CE", "1999-01-01") is None


def test_lookup_at_unknown_timestamp_is_empty(engine):
    eng, _, _ = engine
    ghost = pd.Timestamp("2024-01-02 11:11:00")
    assert eng._chain_at(ghost).empty
    assert eng._price_at(ghost, 20000.0, "CE", "2024-01-25") is None


def test_index_handles_unsorted_input(engine):
    """load_data sorts, but the index must not silently rely on that."""
    eng, data, loader = engine
    shuffled = data.sample(frac=1.0, random_state=0)
    eng._index_by_timestamp(shuffled)

    for ts in _timestamps(data):
        fast = eng._chain_at(ts).reset_index(drop=True)
        slow = loader.get_options_chain(data, ts).reset_index(drop=True)
        pd.testing.assert_frame_equal(fast, slow)


def test_index_returns_monotonic_frame(engine):
    eng, data, _ = engine
    out = eng._index_by_timestamp(data.sample(frac=1.0, random_state=1))
    assert out["timestamp"].is_monotonic_increasing
