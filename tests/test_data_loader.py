"""Tests for the unified Parquet access layer."""
from datetime import date

import pandas as pd
import pytest

from backend.data_loader import DataLoader


def test_available_underlyings(loader):
    assert loader.available_underlyings() == ["BARE", "DAILY", "SYNTH"]


def test_load_data_returns_canonical_columns(loader):
    data = loader.load_data("SYNTH")
    assert not data.empty
    for col in ("timestamp", "strike", "option_type", "close", "expiry"):
        assert col in data.columns
    assert pd.api.types.is_datetime64_any_dtype(data["timestamp"])


def test_load_data_filters_by_date_range(loader):
    data = loader.load_data("SYNTH", date(2024, 1, 2), date(2024, 1, 2))
    assert set(data["timestamp"].dt.date.unique()) == {date(2024, 1, 2)}


def test_load_data_filters_by_granularity(loader):
    assert not loader.load_data("SYNTH", granularity="1min").empty
    assert loader.load_data("SYNTH", granularity="1d").empty


def test_load_data_missing_granularity_column_does_not_raise(loader):
    """
    Regression: the BARE fixture has no `granularity` column. Filtering used to
    raise KeyError instead of degrading gracefully.
    """
    data = loader.load_data("BARE", granularity="1d")
    assert not data.empty


def test_missing_underlying_returns_empty(loader):
    assert loader.load_data("DOES_NOT_EXIST").empty


# ── year-based partition pruning ─────────────────────────────

@pytest.mark.parametrize("start,end,expected", [
    (None, None, True),                                  # unfiltered: read everything
    (date(2024, 1, 1), date(2024, 12, 31), True),        # same year
    (date(2023, 1, 1), date(2025, 1, 1), True),          # spans the year
    (date(2025, 1, 1), date(2025, 12, 31), False),       # entirely after
    (date(2022, 1, 1), date(2022, 12, 31), False),       # entirely before
    (date(2024, 6, 1), None, True),                      # open-ended end
    (None, date(2020, 1, 1), False),                     # open-ended start, before
])
def test_file_in_range_prunes_by_filename_year(start, end, expected):
    from pathlib import Path
    assert DataLoader._file_in_range(Path("NIFTY_2024.parquet"), start, end) is expected


def test_unrecognized_filename_is_never_pruned():
    """A file we can't date must be read, not silently skipped."""
    from pathlib import Path
    assert DataLoader._file_in_range(
        Path("weird_name.parquet"), date(1999, 1, 1), date(1999, 12, 31)) is True


def test_pruning_does_not_drop_in_range_rows(loader):
    """Filtering by a date range must return the same rows as filtering in memory."""
    pruned = loader.load_data("SYNTH", date(2024, 1, 2), date(2024, 1, 2))
    everything = loader.load_data("SYNTH")
    expected = everything[everything["timestamp"].dt.date == date(2024, 1, 2)]
    assert len(pruned) == len(expected)


def test_out_of_range_query_returns_empty(loader):
    assert loader.load_data("SYNTH", date(2019, 1, 1), date(2019, 12, 31)).empty


def test_estimate_spot_price_recovers_spot_via_parity(loader):
    data = loader.load_data("SYNTH")
    ts = sorted(data["timestamp"].unique())[0]
    chain = loader.get_options_chain(data, pd.Timestamp(ts))
    assert loader.estimate_spot_price(chain) == pytest.approx(20000.0, abs=1.0)


def test_estimate_spot_price_without_close_column_does_not_raise(loader):
    """
    Regression: a chain lacking a `close` column raised KeyError('close') and
    surfaced as a 500 on /api/data/options-chain.
    """
    data = loader.load_data("BARE")
    chain = loader.get_options_chain(data, pd.Timestamp(data["timestamp"].iloc[0]))
    spot = loader.estimate_spot_price(chain)
    assert spot is None or isinstance(spot, float)


def test_estimate_spot_price_empty_chain_returns_none(loader):
    assert loader.estimate_spot_price(pd.DataFrame()) is None


def test_select_strike_atm_and_offsets(loader):
    data = loader.load_data("SYNTH")
    chain = loader.get_options_chain(data, pd.Timestamp(sorted(data["timestamp"].unique())[0]))
    assert loader.select_strike(chain, 20000.0, "CE", "ATM") == 20000.0
    assert loader.select_strike(chain, 20000.0, "CE", "OTM") == 20100.0
    assert loader.select_strike(chain, 20000.0, "PE", "OTM") == 19900.0


def test_select_strike_clamps_beyond_range(loader):
    data = loader.load_data("SYNTH")
    chain = loader.get_options_chain(data, pd.Timestamp(sorted(data["timestamp"].unique())[0]))
    assert loader.select_strike(chain, 20000.0, "CE", "OTM", offset=99) == 20200.0


def test_get_option_price_roundtrip(loader):
    data = loader.load_data("SYNTH")
    ts = pd.Timestamp(sorted(data["timestamp"].unique())[0])
    price = loader.get_option_price(data, ts, 20000.0, "CE", "2024-01-25")
    assert price == pytest.approx(100.0)


def test_get_option_price_missing_returns_none(loader):
    data = loader.load_data("SYNTH")
    ts = pd.Timestamp(sorted(data["timestamp"].unique())[0])
    assert loader.get_option_price(data, ts, 12345.0, "CE", "2024-01-25") is None


@pytest.mark.parametrize("underlying,day,expected", [
    ("NIFTY", date(2024, 5, 1), 25),
    ("NIFTY", date(2022, 1, 1), 50),
    ("NIFTY", date(2020, 1, 1), 75),
    ("BANKNIFTY", date(2024, 1, 1), 15),
    ("SENSEX", date(2024, 1, 1), 10),
    ("UNKNOWN", date(2024, 1, 1), 50),
])
def test_historical_lot_size(underlying, day, expected):
    assert DataLoader.get_historical_lot_size(underlying, day) == expected


# ── cheap date scanning ──────────────────────────────────────

@pytest.mark.parametrize("underlying", ["SYNTH", "DAILY", "BARE"])
def test_trading_dates_match_full_load(loader, underlying):
    """
    The column-only scan must agree with deriving dates from a full load_data().
    Equivalence matters more than the speedup — this path feeds the date pickers.
    """
    fast = loader.get_available_trading_dates(underlying)

    full = loader.load_data(underlying)
    expected = sorted({str(d) for d in full["timestamp"].dt.date.unique()})

    assert fast == expected


@pytest.mark.parametrize("underlying", ["SYNTH", "DAILY", "BARE"])
def test_date_range_matches_full_load(loader, underlying):
    lo, hi = loader.available_date_range(underlying)
    full = loader.load_data(underlying)
    dates = full["timestamp"].dt.date
    assert (lo, hi) == (dates.min(), dates.max())


def test_date_range_of_unknown_underlying_is_none(loader):
    assert loader.available_date_range("NOPE") == (None, None)
    assert loader.get_available_trading_dates("NOPE") == []


def test_trading_dates_are_cached(loader):
    first = loader.get_available_trading_dates("SYNTH")
    second = loader.get_available_trading_dates("SYNTH")
    assert first == second
    loader.clear_cache()
    assert loader.get_available_trading_dates("SYNTH") == first


def test_valid_expiries_and_trading_dates(loader):
    assert loader.get_available_trading_dates("SYNTH") == ["2024-01-02", "2024-01-03"]
    assert loader.get_valid_expiries("SYNTH", "2024-01-02") == ["2024-01-25"]
    assert loader.get_valid_expiries("SYNTH", "1999-01-01") == []
