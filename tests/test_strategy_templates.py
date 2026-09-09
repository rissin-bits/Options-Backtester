"""
Tests for the adjustable ready-made strategy templates.

Every strategy in the Backtest tab is built from a template + user params, so
these pin down that (a) all templates build, (b) adjustments actually change the
resulting strategy, and (c) bad/partial params degrade to defaults instead of
crashing a backtest.
"""
import pytest

from backend.strategy import (
    RuleBasedStrategy, Side, OptionType, StrikeSelection, PriceCondition,
)
from backend.strategy_templates import (
    TEMPLATES, build_strategy, list_templates, describe_leg,
)
from backend.example_strategies import EXAMPLE_STRATEGIES, VWAPBreakoutStrategy


ALL_IDS = list(TEMPLATES.keys())


def test_templates_cover_every_example_strategy():
    # Every registered example must be adjustable via a template.
    assert set(TEMPLATES) == set(EXAMPLE_STRATEGIES)


@pytest.mark.parametrize("tid", ALL_IDS)
def test_every_template_builds_with_defaults(tid):
    strat = build_strategy(tid, None)
    assert strat.name


@pytest.mark.parametrize("tid", ALL_IDS)
def test_schema_is_serializable_and_complete(tid):
    d = TEMPLATES[tid].to_dict()
    assert d["id"] == tid and d["name"] and d["params"]
    for p in d["params"]:
        assert {"key", "label", "type", "default"} <= set(p)
        assert p["type"] in {"time", "number", "int", "select"}


def test_list_templates_returns_all():
    rows = list_templates()
    assert {r["id"] for r in rows} == set(TEMPLATES)


# ── adjustments actually take effect ─────────────────────────

def test_stop_loss_adjustment_changes_exit_rule():
    s = build_strategy("short_straddle_920", {"stop_loss_pct": 45})
    sl = [r for r in s.exit_rules if isinstance(r.condition, PriceCondition)]
    assert sl and sl[0].condition.value == -45


def test_zero_stop_loss_removes_the_rule():
    s = build_strategy("short_straddle_920", {"stop_loss_pct": 0, "target_pct": 0})
    assert s.exit_rules == []


def test_target_adds_a_profit_exit():
    s = build_strategy("short_straddle_920", {"target_pct": 60})
    assert any(r.condition.value == 60 for r in s.exit_rules
               if isinstance(r.condition, PriceCondition))


def test_lots_adjustment_flows_to_every_leg():
    s = build_strategy("iron_condor", {"lots": 7})
    orders = s.entry_rules[0].orders
    assert len(orders) == 4
    assert all(o.quantity == 7 for o in orders)


def test_strangle_width_sets_arbitrary_otm_offset():
    s = build_strategy("short_strangle", {"otm_width": 6})
    ce = next(o for o in s.entry_rules[0].orders if o.option_type == OptionType.CE)
    pe = next(o for o in s.entry_rules[0].orders if o.option_type == OptionType.PE)
    assert ce.strike_selection == StrikeSelection.ATM_PLUS_N and ce.strike_offset == 6
    assert pe.strike_selection == StrikeSelection.ATM_MINUS_N and pe.strike_offset == 6


def test_iron_condor_wings_are_further_out_than_shorts():
    s = build_strategy("iron_condor", {"short_width": 2, "wing_width": 3})
    legs = {o.tag: o for o in s.entry_rules[0].orders}
    assert legs["short_ce"].strike_offset == 2
    assert legs["long_ce"].strike_offset == 5      # 2 + 3
    assert legs["short_pe"].strike_offset == 2
    assert legs["long_pe"].strike_offset == 5


def test_square_off_and_entry_time_adjust():
    s = build_strategy("short_straddle_920",
                       {"entry_time": "09:45", "square_off_time": "14:00"})
    # RuleBasedStrategy normalizes square_off_time to a datetime.time.
    assert str(s.square_off_time).startswith("14:00")
    # entry time lives in the AndCondition's TimeCondition
    tc = s.entry_rules[0].condition.conditions[0]
    assert tc.to_dict().get("value") == "09:45"


def test_expiry_weekday_select():
    s = build_strategy("expiry_day_straddle", {"expiry_weekday": 1})
    dow = s.entry_rules[0].condition.conditions[0]
    assert dow.to_dict().get("days") == [1]


def test_rsi_params_adjust():
    s = build_strategy("rsi_mean_reversion",
                       {"rsi_period": 21, "rsi_oversold": 25, "rsi_overbought": 75})
    entry_cond = s.entry_rules[0].condition.conditions[0].to_dict()
    assert entry_cond.get("params", {}).get("period") == 21
    assert entry_cond.get("value") == 25


def test_vwap_params_adjust():
    v = build_strategy("vwap_breakout",
                       {"stop_loss_pct": 2, "target_pct": 9, "lots": 5})
    assert isinstance(v, VWAPBreakoutStrategy)
    assert v.stop_loss_pct == 2 and v.target_pct == 9 and v.lots == 5


# ── robustness ───────────────────────────────────────────────

def test_unknown_param_keys_ignored():
    build_strategy("short_straddle_920", {"nonsense": 999, "lots": 2})


def test_bad_typed_values_fall_back_to_defaults():
    s = build_strategy("short_strangle", {"otm_width": "abc", "stop_loss_pct": None})
    ce = next(o for o in s.entry_rules[0].orders if o.option_type == OptionType.CE)
    assert ce.strike_offset == 2      # default width


def test_int_params_are_clamped_to_range():
    s = build_strategy("short_strangle", {"otm_width": 999})
    ce = next(o for o in s.entry_rules[0].orders if o.option_type == OptionType.CE)
    assert ce.strike_offset == 30     # clamped to max


def test_unknown_template_id_raises_keyerror():
    with pytest.raises(KeyError):
        build_strategy("no_such_strategy", {})


def test_describe_leg_labels_width():
    s = build_strategy("iron_condor", {"short_width": 2, "wing_width": 2})
    labels = {describe_leg(o)["tag"]: describe_leg(o)["strike"]
              for o in s.entry_rules[0].orders}
    assert labels["short_ce"] == "ATM+2"
    assert labels["long_pe"] == "ATM-4"
