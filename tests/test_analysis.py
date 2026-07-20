"""Tests for Greeks, Monte Carlo and stress-test analytics."""
import math

import pytest

from backend.greeks import black_scholes, implied_volatility
from backend.monte_carlo import calculate_strategy_payoff, run_monte_carlo
from backend.stress_test import SCENARIOS, run_stress_tests

LEGS = [{"side": "SELL", "type": "CE", "strike": 20000.0, "premium": 100.0, "qty": 1}]


# ── Greeks ───────────────────────────────────────────────────

def test_black_scholes_call_delta_bounds():
    g = black_scholes("c", 20000, 20000, 30 / 365, 0.065, 0.15)
    assert 0.0 <= g["delta"] <= 1.0
    assert g["gamma"] >= 0
    assert g["price"] > 0


def test_black_scholes_put_delta_is_negative():
    g = black_scholes("p", 20000, 20000, 30 / 365, 0.065, 0.15)
    assert -1.0 <= g["delta"] <= 0.0


def test_deep_itm_call_delta_approaches_one():
    g = black_scholes("c", 25000, 20000, 30 / 365, 0.065, 0.15)
    assert g["delta"] > 0.9


def test_implied_volatility_roundtrip():
    sigma = 0.18
    price = black_scholes("c", 20000, 20000, 30 / 365, 0.065, sigma)["price"]
    assert implied_volatility("c", price, 20000, 20000, 30 / 365, 0.065) == pytest.approx(sigma, abs=0.01)


# ── Monte Carlo ──────────────────────────────────────────────

def test_short_call_payoff_capped_at_premium():
    import numpy as np
    prices = np.array([15000.0, 20000.0, 25000.0])
    pnl = calculate_strategy_payoff(prices, LEGS, lot_size=1)
    assert pnl[0] == pytest.approx(100.0)      # expires worthless -> keep premium
    assert pnl[2] == pytest.approx(-4900.0)    # 5000 intrinsic - 100 premium


def test_monte_carlo_shape_and_finiteness():
    res = run_monte_carlo(20000, 0.15, 7, LEGS, lot_size=50, n_simulations=500)
    assert 0.0 <= res["prob_profit"] <= 100.0
    assert len(res["histogram"]) == 50
    for key in ("expected_value", "max_loss", "max_profit"):
        assert math.isfinite(res[key])
    assert res["max_loss"] <= res["max_profit"]


def test_monte_carlo_lot_size_scales_pnl():
    small = run_monte_carlo(20000, 0.15, 7, LEGS, lot_size=1, n_simulations=500)
    large = run_monte_carlo(20000, 0.15, 7, LEGS, lot_size=50, n_simulations=500)
    assert abs(large["max_loss"]) > abs(small["max_loss"])


# ── Stress tests ─────────────────────────────────────────────

def test_stress_tests_cover_all_scenarios():
    res = run_stress_tests(20000, 0.15, 7, LEGS, lot_size=50)
    assert len(res) == len(SCENARIOS)
    assert {r["name"] for r in res} == {s["name"] for s in SCENARIOS}


def test_stress_scenario_shape_and_shock_applied():
    res = run_stress_tests(20000, 0.15, 7, LEGS, lot_size=50)
    black_swan = next(r for r in res if r["name"] == "Black Swan")
    assert black_swan["result"]["spot"] == pytest.approx(16000.0)
    assert set(black_swan["result"]["greeks"]) == {"delta", "gamma", "theta", "vega"}
    assert math.isfinite(black_swan["result"]["pnl"])


def test_iv_is_floored_at_one_percent():
    res = run_stress_tests(20000, 0.15, 7, LEGS, custom_scenarios=[
        {"name": "IV Wipeout", "spot_shock": 0.0, "iv_shock": -5.0},
    ])
    assert next(r for r in res if r["name"] == "IV Wipeout")["result"]["iv"] >= 0.01


# ── API contract ─────────────────────────────────────────────

def _payload(legs):
    return {"spot_price": 20000, "current_iv": 0.15, "days_to_expiry": 7,
            "legs": legs, "lot_size": 50}


@pytest.mark.parametrize("endpoint", ["/api/analysis/monte-carlo", "/api/analysis/stress-test"])
def test_analysis_endpoints_accept_frontend_leg_shape(client, endpoint):
    """The shape StrategyBuilder.jsx actually builds: side/type/strike/premium."""
    assert client.post(endpoint, json=_payload(LEGS)).status_code == 200


@pytest.mark.parametrize("endpoint", ["/api/analysis/monte-carlo", "/api/analysis/stress-test"])
def test_malformed_leg_is_422_not_500(client, endpoint):
    """Regression: a leg missing `type` produced an opaque 500 {'detail': "'type'"}."""
    res = client.post(endpoint, json=_payload([{"side": "SELL", "strike": 20000, "premium": 100}]))
    assert res.status_code == 422
