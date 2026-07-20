"""
Tests for the backtest engine.

The headline regression here is `json_safe`: profit_factor legitimately becomes
inf (no losing trades) or NaN, and Starlette serializes with
json.dumps(allow_nan=False), so a non-finite value crashed the request *after*
the route handler returned — outside its try/except, as an opaque 500.
"""
import json
import math
from datetime import date

import pytest

from backend.engine import BacktestConfig, BacktestEngine, json_safe
from backend.example_strategies import EXAMPLE_STRATEGIES
from backend.strategy import (
    AndCondition, Order, OptionType, PositionCondition, Rule,
    RuleBasedStrategy, Side, StrikeSelection, TimeCondition,
)


def _straddle(square_off="15:15"):
    return RuleBasedStrategy(
        name="Test Straddle",
        description="Sell ATM CE+PE at 09:20",
        entry_rules=[Rule(
            name="entry",
            condition=AndCondition([
                TimeCondition(">=", "09:20"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM, tag="ce"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM, tag="pe"),
            ],
        )],
        exit_rules=[],
        square_off_time=square_off,
    )


def _config(underlying, granularity):
    return BacktestConfig(
        underlying=underlying,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        initial_capital=500_000.0,
        lot_size=25,
        granularity=granularity,
    )


# ── json_safe ────────────────────────────────────────────────

@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_json_safe_replaces_non_finite_scalars(value):
    assert json_safe(value) is None


def test_json_safe_recurses_into_containers():
    payload = {"a": [1.0, float("inf")], "b": {"c": float("nan")}, "d": "ok"}
    assert json_safe(payload) == {"a": [1.0, None], "b": {"c": None}, "d": "ok"}


def test_json_safe_output_is_strict_json_serializable():
    """This is exactly what Starlette's JSONResponse does."""
    json.dumps(json_safe({"pf": float("inf")}), allow_nan=False)


def test_json_safe_preserves_finite_values():
    assert json_safe({"x": 1.5, "y": 3, "z": "s"}) == {"x": 1.5, "y": 3, "z": "s"}


# ── engine behaviour ─────────────────────────────────────────

def test_intraday_backtest_produces_trades(loader):
    engine = BacktestEngine(_config("SYNTH", "1min"), loader)
    result = engine.run(_straddle())
    assert result.total_trades > 0, "09:20 entry should fire on intraday data"
    assert result.warnings == []


def test_result_is_json_serializable_with_trades(loader):
    engine = BacktestEngine(_config("SYNTH", "1min"), loader)
    result = engine.run(_straddle())
    json.dumps(result.to_dict(), allow_nan=False)


def test_zero_loss_run_yields_finite_profit_factor(loader):
    """
    Regression: gross_loss == 0 set profit_factor to inf, which is not JSON
    compliant. to_dict must never emit a non-finite float.
    """
    engine = BacktestEngine(_config("SYNTH", "1min"), loader)
    payload = engine.run(_straddle()).to_dict()
    pf = payload["profit_factor"]
    assert pf is None or math.isfinite(pf)


def test_daily_data_zero_trades_is_explained(loader):
    """
    Daily bhavcopy candles are dated midnight, so a 09:20 rule can never fire.
    The run must say so rather than silently reporting a clean zero-trade result.
    """
    engine = BacktestEngine(_config("DAILY", "1d"), loader)
    result = engine.run(_straddle())
    assert result.total_trades == 0
    assert result.warnings, "zero-trade daily run must carry a diagnostic"
    assert "intraday" in result.warnings[0].lower()


def test_no_data_returns_empty_result_with_warning(loader):
    engine = BacktestEngine(_config("NOT_THERE", "1min"), loader)
    result = engine.run(_straddle())
    assert result.total_trades == 0
    assert any("No data" in w for w in result.warnings)
    json.dumps(result.to_dict(), allow_nan=False)


def test_progress_callback_is_invoked(loader):
    seen = []
    engine = BacktestEngine(_config("SYNTH", "1min"), loader)
    engine.run(_straddle(), lambda pct, msg: seen.append((pct, msg)))
    assert seen
    assert all(0 <= pct <= 100 for pct, _ in seen)


def test_square_off_closes_all_positions(loader):
    engine = BacktestEngine(_config("SYNTH", "1min"), loader)
    result = engine.run(_straddle())
    assert result.total_trades > 0
    assert engine.positions == [], "no position may survive the final square-off"


def test_example_strategies_are_loadable():
    assert EXAMPLE_STRATEGIES
    for key, strat in EXAMPLE_STRATEGIES.items():
        assert strat.name, f"{key} missing a name"
