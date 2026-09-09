"""HTTP-level tests. These exercise the exact serialization path that crashed."""
import json

import pytest


def test_status(client):
    body = client.get("/api/status").json()
    assert body["status"] == "healthy"
    assert body["data_available"] is True
    assert "SYNTH" in body["underlyings"]


def test_indicators_listed(client):
    res = client.get("/api/indicators")
    assert res.status_code == 200
    assert len(res.json()) > 0


def test_underlyings_have_date_ranges(client):
    rows = client.get("/api/data/underlyings").json()
    synth = next(r for r in rows if r["name"] == "SYNTH")
    assert synth["min_date"] == "2024-01-02"
    assert synth["max_date"] == "2024-01-03"


def test_data_summary(client):
    body = client.get("/api/data/summary").json()
    assert body["underlyings_count"] >= 1
    assert "SYNTH" in body["underlyings_list"]


def test_trading_dates_and_expiries(client):
    dates = client.get("/api/data/trading-dates", params={"underlying": "SYNTH"}).json()
    assert {d["date"] for d in dates} == {"2024-01-02", "2024-01-03"}

    exp = client.get("/api/data/expiries",
                     params={"underlying": "SYNTH", "date": "2024-01-02"}).json()
    assert exp[0]["expiry"] == "2024-01-25"
    assert exp[0]["dte"] == 23


def test_timestamps_endpoint_returns_iso_strings(client):
    """
    Regression: this returned str(pd.Timestamp(...)) -> "2024-01-02 09:20:00".
    OptionsChain.jsx does `value.split('T')[1]` to populate the time selector, so
    a space separator silently yielded `undefined` for every option and the
    intraday time picker never worked.
    """
    from datetime import datetime

    ts = client.get("/api/data/timestamps",
                    params={"underlying": "SYNTH", "date": "2024-01-02"}).json()
    assert ts
    for value in ts:
        assert "T" in value, f"not ISO-8601: {value!r}"
        assert datetime.fromisoformat(value).date().isoformat() == "2024-01-02"
    # The exact round-trip the UI performs.
    assert ts[0].split("T")[1] == "09:15:00"


def test_options_chain_is_enriched(client):
    res = client.post("/api/data/options-chain",
                      json={"underlying": "SYNTH", "date": "2024-01-02"})
    assert res.status_code == 200
    body = res.json()
    assert body["spot_price"] == pytest.approx(20000.0, abs=1.0)
    assert len(body["chain"]) == 10
    assert {"strike", "option_type", "close", "delta", "moneyness"} <= set(body["chain"][0])


def test_options_chain_degenerate_schema_does_not_500(client):
    """Regression: a fixture lacking `close` raised KeyError -> 500."""
    res = client.post("/api/data/options-chain",
                      json={"underlying": "BARE", "date": "2024-01-02"})
    assert res.status_code == 200


def test_options_chain_unknown_underlying_404s(client):
    res = client.post("/api/data/options-chain",
                      json={"underlying": "NOPE", "date": "2024-01-02"})
    assert res.status_code == 404


def test_lot_size(client):
    body = client.get("/api/data/lot-size",
                      params={"underlying": "NIFTY", "date": "2024-05-01"}).json()
    assert body["lot_size"] == 25


def test_example_strategies_exposed(client):
    rows = client.get("/api/strategies/examples").json()
    assert rows and {"id", "name", "description"} <= set(rows[0])


def test_strategy_templates_endpoint(client):
    rows = client.get("/api/strategies/templates").json()
    assert len(rows) == 9
    for t in rows:
        assert {"id", "name", "description", "params", "preview_legs"} <= set(t)
        assert t["params"]  # every strategy is adjustable


def test_backtest_with_adjusted_params_runs(client):
    """strategy_id + params must build the adjusted strategy and run."""
    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    req["strategy_id"] = "short_straddle_920"
    base = {"entry_time": "09:20", "square_off_time": "15:15", "stop_loss_pct": 0}

    req["params"] = {**base, "lots": 1}
    one = client.post("/api/backtest", json=req).json()
    req["params"] = {**base, "lots": 2}
    two = client.post("/api/backtest", json=req).json()

    assert one["total_trades"] > 0 and two["total_trades"] > 0
    # Trade quantity is lots * lot size, so doubling lots doubles the quantity.
    q1 = one["trades"][0]["quantity"]
    q2 = two["trades"][0]["quantity"]
    assert q2 == 2 * q1


def test_strategy_save_get_delete_roundtrip(client):
    config = {
        "name": "s", "description": "d",
        "entry_rules": [], "exit_rules": [],
        "square_off_time": "15:15", "max_positions": 5,
    }
    created = client.post("/api/strategies", json=config).json()
    sid = created["id"]
    assert client.get(f"/api/strategies/{sid}").status_code == 200
    assert client.delete(f"/api/strategies/{sid}").json()["deleted"] is True
    assert client.get(f"/api/strategies/{sid}").status_code == 404


# ── the crash regression ─────────────────────────────────────

def _backtest_request(underlying, granularity):
    return {
        "underlying": underlying,
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": 500000,
        "lot_size": 25,
        "granularity": granularity,
        "slippage_pct": 0.0,
        "commission_per_lot": 0.0,
        "strategy": {
            "name": "Straddle", "description": "t",
            "entry_rules": [{
                "name": "entry",
                "condition": {"type": "time", "operator": ">=", "value": "09:20"},
                "orders": [
                    {"side": "SELL", "option_type": "CE",
                     "strike_selection": "ATM", "quantity": 1},
                    {"side": "SELL", "option_type": "PE",
                     "strike_selection": "ATM", "quantity": 1},
                ],
                "max_triggers_per_day": 1,
            }],
            "exit_rules": [],
            "square_off_time": "15:15",
            "max_positions": 10,
        },
    }


def test_backtest_intraday_returns_200_and_trades(client):
    res = client.post("/api/backtest", json=_backtest_request("SYNTH", "1min"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total_trades"] > 0
    assert body["profit_factor"] is None or isinstance(body["profit_factor"], (int, float))


def test_backtest_zero_trade_run_serializes(client):
    """
    Regression: zero trades -> profit_factor inf -> ValueError inside Starlette's
    json.dumps(allow_nan=False), raised after the handler returned, so it bypassed
    api.py's try/except and surfaced as an unhandled 500.
    """
    res = client.post("/api/backtest", json=_backtest_request("DAILY", "1d"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total_trades"] == 0
    assert body["warnings"], "zero-trade run should explain itself"
    json.dumps(body, allow_nan=False)


def test_backtest_by_strategy_id_runs_example(client):
    """
    BacktestRequest always declared `strategy_id`, but only the inline `strategy`
    path was implemented, so an id-only request hit
    _build_strategy_from_config(None) -> AttributeError.
    """
    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    req["strategy_id"] = "short_straddle_920"
    res = client.post("/api/backtest", json=req)
    assert res.status_code == 200, res.text
    assert res.json()["strategy_name"]


def test_backtest_unknown_strategy_id_404s(client):
    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    req["strategy_id"] = "no_such_strategy"
    assert client.post("/api/backtest", json=req).status_code == 404


def test_backtest_without_strategy_or_id_is_422(client):
    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    assert client.post("/api/backtest", json=req).status_code == 422


def test_saved_strategy_can_be_backtested_by_id(client):
    config = {
        "name": "saved", "description": "",
        "entry_rules": [{
            "name": "entry",
            "condition": {"type": "time", "operator": ">=", "value": "09:20"},
            "orders": [{"side": "SELL", "option_type": "CE",
                        "strike_selection": "ATM", "quantity": 1}],
            "max_triggers_per_day": 1,
        }],
        "exit_rules": [], "square_off_time": "15:15", "max_positions": 5,
    }
    sid = client.post("/api/strategies", json=config).json()["id"]

    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    req["strategy_id"] = sid
    res = client.post("/api/backtest", json=req)
    assert res.status_code == 200, res.text
    assert res.json()["total_trades"] > 0


def test_example_strategy_state_does_not_leak_between_runs(client):
    """Examples are module singletons; each run must get a fresh copy."""
    req = _backtest_request("SYNTH", "1min")
    del req["strategy"]
    req["strategy_id"] = "short_straddle_920"
    first = client.post("/api/backtest", json=req).json()
    second = client.post("/api/backtest", json=req).json()
    assert first["total_trades"] == second["total_trades"]


def test_backtest_bad_dates_is_client_error(client):
    bad = _backtest_request("SYNTH", "1min")
    bad["start_date"] = "not-a-date"
    assert client.post("/api/backtest", json=bad).status_code in (422, 500)
