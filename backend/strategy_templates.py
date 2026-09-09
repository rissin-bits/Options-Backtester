"""
strategy_templates.py — parameterized versions of the ready-made strategies.

Each ready-made strategy here is a *template*: a parameter schema plus a
``build(params)`` function that assembles a runnable Strategy from those
parameters. This is what lets the Backtest tab expose every strategy AND let
the user adjust it (entry/exit times, stop-loss, strike width, lots, indicator
settings, ...) before running.

The API serves the schema (`GET /api/strategies/templates`); the engine calls
`build_strategy(template_id, params)` to construct the adjusted strategy.

Design notes:
- Params are validated/coerced against the schema, and unknown keys ignored, so
  a stale frontend can't crash a backtest.
- Strike width uses the ATM_PLUS_N / ATM_MINUS_N modes with Order.strike_offset,
  so widths are arbitrary rather than limited to the ATM+1 / ATM+2 enum members.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.strategy import (
    Strategy, RuleBasedStrategy, Rule, Order,
    TimeCondition, PriceCondition, IndicatorCondition, PositionCondition,
    DayOfWeekCondition, AndCondition,
    Side, OptionType, StrikeSelection,
)
from backend.example_strategies import VWAPBreakoutStrategy


# ──────────────────────────────────────────────────────────────
# Parameter schema
# ──────────────────────────────────────────────────────────────

@dataclass
class Param:
    """One adjustable knob, rendered as a form control in the UI."""
    key: str
    label: str
    type: str                       # "time" | "number" | "int" | "select"
    default: Any
    group: str = "General"
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: Optional[List[Dict[str, Any]]] = None   # for "select"
    help: str = ""

    def to_dict(self) -> dict:
        d = {"key": self.key, "label": self.label, "type": self.type,
             "default": self.default, "group": self.group, "help": self.help}
        for k in ("min", "max", "step", "options"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    def coerce(self, raw: Any) -> Any:
        """Coerce a raw incoming value to this param's type, clamped to range."""
        if raw is None:
            return self.default
        try:
            if self.type == "int":
                v = int(round(float(raw)))
            elif self.type == "number":
                v = float(raw)
            elif self.type == "select":
                # Match against declared option values, preserving their type.
                for opt in self.options or []:
                    if str(opt["value"]) == str(raw):
                        return opt["value"]
                return self.default
            else:  # "time" and anything else -> string
                return str(raw)
        except (TypeError, ValueError):
            return self.default
        if self.min is not None:
            v = max(self.min, v)
        if self.max is not None:
            v = min(self.max, v)
        return v


WEEKDAY_OPTIONS = [
    {"value": 0, "label": "Monday"}, {"value": 1, "label": "Tuesday"},
    {"value": 2, "label": "Wednesday"}, {"value": 3, "label": "Thursday"},
    {"value": 4, "label": "Friday"},
]

# Reusable param definitions ---------------------------------------------------

def p_entry(default="09:20"):
    return Param("entry_time", "Entry Time", "time", default, group="Timing",
                 help="Enter the position at or after this time.")

def p_squareoff(default="15:15"):
    return Param("square_off_time", "Square-off Time", "time", default, group="Timing",
                 help="Force-close all positions at this time.")

def p_stoploss(default=30.0):
    return Param("stop_loss_pct", "Stop Loss (% of premium)", "number", default,
                 group="Risk", min=0, max=1000, step=5,
                 help="Exit the position when it loses this % of entry premium. 0 disables.")

def p_target(default=0.0):
    return Param("target_pct", "Profit Target (% of premium)", "number", default,
                 group="Risk", min=0, max=1000, step=5,
                 help="Exit when the position gains this % of entry premium. 0 disables.")

def p_lots(default=1):
    return Param("lots", "Lots per leg", "int", default, group="Size",
                 min=1, max=200, step=1)

def p_width(key, label, default, help=""):
    return Param(key, label, "int", default, group="Strikes",
                 min=1, max=30, step=1, help=help)


# ──────────────────────────────────────────────────────────────
# Builder helpers
# ──────────────────────────────────────────────────────────────

def _otm(option_type: OptionType, width: int):
    """(strike_selection, strike_offset) for a strike `width` steps OTM."""
    if width <= 0:
        return StrikeSelection.ATM, None
    if option_type == OptionType.CE:          # OTM call = higher strike
        return StrikeSelection.ATM_PLUS_N, width
    return StrikeSelection.ATM_MINUS_N, width  # OTM put = lower strike


def _leg(side, option_type, width, lots, tag):
    sel, off = _otm(option_type, width)
    return Order(side, option_type, sel, quantity=lots, strike_offset=off, tag=tag)


def _exit_rules(stop_loss_pct: float, target_pct: float = 0.0) -> List[Rule]:
    rules = []
    if stop_loss_pct and stop_loss_pct > 0:
        rules.append(Rule(
            name=f"Stop loss {stop_loss_pct:g}%",
            condition=PriceCondition("position_pnl_pct", "<=", -abs(stop_loss_pct)),
            orders=[], is_entry=False))
    if target_pct and target_pct > 0:
        rules.append(Rule(
            name=f"Target {target_pct:g}%",
            condition=PriceCondition("position_pnl_pct", ">=", abs(target_pct)),
            orders=[], is_entry=False))
    return rules


def _entry(name, conditions, orders) -> Rule:
    return Rule(name=name, condition=AndCondition(conditions), orders=orders)


def describe_leg(order: Order) -> Dict[str, Any]:
    """Human-readable leg summary for the UI's live preview."""
    sel = order.strike_selection
    if sel in (StrikeSelection.ATM_PLUS_N, StrikeSelection.ATM_MINUS_N):
        sign = "+" if sel == StrikeSelection.ATM_PLUS_N else "-"
        strike = f"ATM{sign}{order.strike_offset}"
    else:
        strike = sel.value
    return {
        "side": order.side.value,
        "option_type": order.option_type.value,
        "strike": strike,
        "lots": order.quantity,
        "tag": order.tag,
    }


# ──────────────────────────────────────────────────────────────
# Template registry
# ──────────────────────────────────────────────────────────────

@dataclass
class Template:
    id: str
    name: str
    description: str
    params: List[Param]
    build: Callable[[Dict[str, Any]], Strategy]
    category: str = "Options"

    def resolve(self, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        raw = raw or {}
        return {p.key: p.coerce(raw.get(p.key)) for p in self.params}

    def to_dict(self, raw: Optional[Dict[str, Any]] = None) -> dict:
        vals = self.resolve(raw)
        strat = self.build(vals)
        legs = []
        if isinstance(strat, RuleBasedStrategy):
            for rule in strat.entry_rules:
                legs.extend(describe_leg(o) for o in rule.orders)
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "params": [p.to_dict() for p in self.params],
            "preview_legs": legs,
        }


# --- individual template builders ---------------------------------------------

def _straddle(v):
    return RuleBasedStrategy(
        name="9:20 Short Straddle",
        description="Sell ATM CE + PE, square off intraday.",
        entry_rules=[_entry("Enter straddle",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.SELL, OptionType.CE, 0, v["lots"], "straddle_ce"),
             _leg(Side.SELL, OptionType.PE, 0, v["lots"], "straddle_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _expiry_straddle(v):
    return RuleBasedStrategy(
        name="Expiry Day Short Straddle",
        description="Sell ATM straddle on the chosen weekday.",
        entry_rules=[_entry("Enter on weekday",
            [DayOfWeekCondition(days=[v["expiry_weekday"]]),
             TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.SELL, OptionType.CE, 0, v["lots"], "straddle_ce"),
             _leg(Side.SELL, OptionType.PE, 0, v["lots"], "straddle_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _strangle(v):
    w = v["otm_width"]
    return RuleBasedStrategy(
        name="Short Strangle",
        description="Sell OTM CE + OTM PE.",
        entry_rules=[_entry("Enter strangle",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.SELL, OptionType.CE, w, v["lots"], "short_ce"),
             _leg(Side.SELL, OptionType.PE, w, v["lots"], "short_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _iron_condor(v):
    sw, ww = v["short_width"], v["wing_width"]
    return RuleBasedStrategy(
        name="Iron Condor",
        description="Sell OTM strangle, buy further-OTM wings for defined risk.",
        entry_rules=[_entry("Enter iron condor",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.SELL, OptionType.CE, sw, v["lots"], "short_ce"),
             _leg(Side.BUY, OptionType.CE, sw + ww, v["lots"], "long_ce"),
             _leg(Side.SELL, OptionType.PE, sw, v["lots"], "short_pe"),
             _leg(Side.BUY, OptionType.PE, sw + ww, v["lots"], "long_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _iron_butterfly(v):
    ww = v["wing_width"]
    return RuleBasedStrategy(
        name="Iron Butterfly",
        description="Sell ATM straddle, buy OTM wings for defined risk.",
        entry_rules=[_entry("Enter iron butterfly",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.SELL, OptionType.CE, 0, v["lots"], "short_ce"),
             _leg(Side.SELL, OptionType.PE, 0, v["lots"], "short_pe"),
             _leg(Side.BUY, OptionType.CE, ww, v["lots"], "long_ce"),
             _leg(Side.BUY, OptionType.PE, ww, v["lots"], "long_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _bull_call(v):
    w = v["spread_width"]
    return RuleBasedStrategy(
        name="Bull Call Spread",
        description="Buy ATM CE, sell OTM CE. Defined-risk bullish.",
        entry_rules=[_entry("Enter bull call spread",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.BUY, OptionType.CE, 0, v["lots"], "long_ce"),
             _leg(Side.SELL, OptionType.CE, w, v["lots"], "short_ce")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _bear_put(v):
    w = v["spread_width"]
    return RuleBasedStrategy(
        name="Bear Put Spread",
        description="Buy ATM PE, sell OTM PE. Defined-risk bearish.",
        entry_rules=[_entry("Enter bear put spread",
            [TimeCondition(">=", v["entry_time"]), PositionCondition("no_position")],
            [_leg(Side.BUY, OptionType.PE, 0, v["lots"], "long_pe"),
             _leg(Side.SELL, OptionType.PE, w, v["lots"], "short_pe")])],
        exit_rules=_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        square_off_time=v["square_off_time"])


def _rsi(v):
    period = v["rsi_period"]
    return RuleBasedStrategy(
        name="RSI Mean Reversion",
        description="Buy ATM CE when RSI is oversold; exit when overbought.",
        entry_rules=[_entry("RSI oversold entry",
            [IndicatorCondition("RSI", {"period": period}, "close", "<", v["rsi_oversold"]),
             PositionCondition("no_position"),
             TimeCondition("between", v["entry_start"], v["entry_end"])],
            [_leg(Side.BUY, OptionType.CE, 0, v["lots"], "rsi_ce")])],
        exit_rules=[
            Rule(name="RSI overbought exit",
                 condition=IndicatorCondition("RSI", {"period": period}, "close", ">", v["rsi_overbought"]),
                 orders=[], is_entry=False),
            *_exit_rules(v["stop_loss_pct"], v["target_pct"]),
        ],
        square_off_time=v["square_off_time"])


def _vwap(v):
    return VWAPBreakoutStrategy(
        entry_after=v["entry_time"],
        square_off_time=v["square_off_time"],
        stop_loss_pct=v["stop_loss_pct"],
        target_pct=v["target_pct"],
        lots=v["lots"])


TEMPLATES: Dict[str, Template] = {
    "short_straddle_920": Template(
        "short_straddle_920", "9:20 Short Straddle",
        "Sell ATM CE + PE at the entry time, square off intraday. Classic theta-decay play.",
        [p_entry("09:20"), p_squareoff("15:15"), p_stoploss(30), p_target(0), p_lots()],
        _straddle),
    "expiry_day_straddle": Template(
        "expiry_day_straddle", "Expiry Day Short Straddle",
        "Short straddle restricted to a chosen weekday (weekly expiry).",
        [Param("expiry_weekday", "Expiry Weekday", "select", 3, group="Timing",
               options=WEEKDAY_OPTIONS),
         p_entry("09:20"), p_squareoff("15:20"), p_stoploss(20), p_target(0), p_lots()],
        _expiry_straddle),
    "short_strangle": Template(
        "short_strangle", "Short Strangle",
        "Sell an OTM call and an OTM put a chosen number of strikes wide.",
        [p_width("otm_width", "OTM Width (strikes)", 2), p_entry("09:30"),
         p_squareoff("15:15"), p_stoploss(50), p_target(0), p_lots()],
        _strangle),
    "iron_condor": Template(
        "iron_condor", "Iron Condor",
        "Sell an OTM strangle and buy further-OTM wings for defined risk.",
        [p_width("short_width", "Short Strike Width", 2,
                 "Strikes from ATM for the sold options."),
         p_width("wing_width", "Wing Width", 2,
                 "Extra strikes out to the protective bought options."),
         p_entry("09:30"), p_squareoff("15:10"), p_stoploss(100), p_target(50), p_lots()],
        _iron_condor),
    "iron_butterfly": Template(
        "iron_butterfly", "Iron Butterfly",
        "Sell an ATM straddle and buy OTM wings for defined risk.",
        [p_width("wing_width", "Wing Width (strikes)", 2), p_entry("09:30"),
         p_squareoff("15:15"), p_stoploss(50), p_target(0), p_lots()],
        _iron_butterfly),
    "bull_call_spread": Template(
        "bull_call_spread", "Bull Call Spread",
        "Buy an ATM call and sell an OTM call. Defined-risk bullish.",
        [p_width("spread_width", "Spread Width (strikes)", 2), p_entry("09:30"),
         p_squareoff("15:15"), p_stoploss(50), p_target(0), p_lots()],
        _bull_call),
    "bear_put_spread": Template(
        "bear_put_spread", "Bear Put Spread",
        "Buy an ATM put and sell an OTM put. Defined-risk bearish.",
        [p_width("spread_width", "Spread Width (strikes)", 2), p_entry("09:30"),
         p_squareoff("15:15"), p_stoploss(50), p_target(0), p_lots()],
        _bear_put),
    "rsi_mean_reversion": Template(
        "rsi_mean_reversion", "RSI Mean Reversion",
        "Buy ATM CE when RSI is oversold, exit when overbought or on stop/target.",
        [Param("rsi_period", "RSI Period", "int", 14, group="Indicator", min=2, max=100),
         Param("rsi_oversold", "Oversold Level", "number", 30, group="Indicator", min=1, max=50),
         Param("rsi_overbought", "Overbought Level", "number", 70, group="Indicator", min=50, max=99),
         Param("entry_start", "Entry Window Start", "time", "09:30", group="Timing"),
         Param("entry_end", "Entry Window End", "time", "14:30", group="Timing"),
         p_squareoff("15:15"), p_stoploss(5), p_target(0), p_lots()],
        _rsi),
    "vwap_breakout": Template(
        "vwap_breakout", "VWAP Breakout",
        "Buy CE/PE on a VWAP crossover after the entry time.",
        [p_entry("09:30"), p_squareoff("15:15"), p_stoploss(3), p_target(5), p_lots()],
        _vwap, category="Directional"),
}


def list_templates(raw_params: Optional[Dict[str, Dict]] = None) -> List[dict]:
    return [t.to_dict() for t in TEMPLATES.values()]


def build_strategy(template_id: str, params: Optional[Dict[str, Any]]) -> Strategy:
    """Build an adjusted strategy from a template id + raw params. Raises KeyError
    if the id is unknown so the caller can return a clean 404."""
    template = TEMPLATES[template_id]
    return template.build(template.resolve(params))
