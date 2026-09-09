"""
strategy.py — Strategy framework for the options backtester.

Provides:
  - Condition system: TimeCondition, PriceCondition, IndicatorCondition
  - Composable conditions with AND/OR/NOT logic
  - Strategy base class with event hooks
  - RuleBasedStrategy for GUI-driven backtesting
  - Order/Action types

The condition system is designed to be serializable to/from JSON so that
strategies built in the GUI can be executed by the engine.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from backend.indicators import INDICATOR_REGISTRY

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Enums & Data Classes
# ──────────────────────────────────────────────────────────────

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Moneyness(str, Enum):
    ATM = "ATM"
    ITM = "ITM"
    OTM = "OTM"


class StrikeSelection(str, Enum):
    ATM = "ATM"
    ATM_PLUS_1 = "ATM+1"
    ATM_PLUS_2 = "ATM+2"
    ATM_PLUS_N = "ATM+N"
    ATM_MINUS_1 = "ATM-1"
    ATM_MINUS_2 = "ATM-2"
    ATM_MINUS_N = "ATM-N"
    FIXED = "FIXED"
    CLOSEST_DELTA = "CLOSEST_DELTA"
    PREMIUM_BASED = "PREMIUM_BASED"
    PERCENT_OTM = "PERCENT_OTM"
    POINTS_OTM = "POINTS_OTM"
    DELTA_BASED = "DELTA_BASED"


@dataclass
class Order:
    """An order to be placed by the strategy."""
    side: Side
    option_type: OptionType
    strike_selection: StrikeSelection = StrikeSelection.ATM
    fixed_strike: Optional[float] = None
    quantity: int = 1  # In lots
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    expiry_selection: str = "nearest"  # "nearest", "next", "monthly", or explicit
    tag: str = ""  # Custom label for this leg
    # Number of strikes away from ATM for the ATM_PLUS_N / ATM_MINUS_N modes.
    # Lets a strategy pick an arbitrary width (e.g. a 5-strike-wide strangle)
    # instead of being limited to the ATM+1 / ATM+2 enum members.
    strike_offset: Optional[int] = None


@dataclass
class Position:
    """A currently open position."""
    id: str
    side: Side
    option_type: str
    strike: float
    expiry: str
    quantity: int
    entry_price: float
    entry_time: datetime
    tag: str = ""
    current_price: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def notional_value(self) -> float:
        return self.entry_price * self.quantity

    def mark_to_market(self, current_price: float):
        self.current_price = current_price
        if self.side == Side.BUY:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity


@dataclass
class Trade:
    """A completed trade (entry + exit)."""
    id: str
    side: Side
    option_type: str
    strike: float
    expiry: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    tag: str = ""
    exit_reason: str = ""


@dataclass
class MarketContext:
    """
    Snapshot of market state at a given timestamp.
    Passed to strategy on every candle for decision-making.
    """
    timestamp: datetime
    underlying: str
    spot_price: float
    options_chain: pd.DataFrame  # Full chain at this timestamp
    positions: List[Position]    # Currently open positions
    portfolio_value: float       # Initial capital + cumulative P&L
    day_pnl: float
    total_pnl: float
    indicators: Dict[str, Any]   # Pre-computed indicator values
    trading_day: date
    candle_index: int            # Index within the day
    total_candles: int           # Total candles in the day
    days_to_expiry: Dict[str, int]  # expiry -> trading days remaining

    @property
    def is_first_candle(self) -> bool:
        return self.candle_index == 0

    @property
    def is_last_candle(self) -> bool:
        return self.candle_index == self.total_candles - 1

    @property
    def time_of_day(self) -> time:
        return self.timestamp.time()


# ──────────────────────────────────────────────────────────────
# Conditions — the heart of the rule engine
# ──────────────────────────────────────────────────────────────

class Condition(ABC):
    """Base class for all conditions."""

    @abstractmethod
    def evaluate(self, ctx: MarketContext) -> bool:
        """Return True if the condition is met."""
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict (for GUI persistence)."""
        pass

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        """Deserialize from dict."""
        cond_type = d.get("type")
        mapping = {
            "time": TimeCondition,
            "price": PriceCondition,
            "indicator": IndicatorCondition,
            "position": PositionCondition,
            "and": AndCondition,
            "or": OrCondition,
            "not": NotCondition,
            "day_of_week": DayOfWeekCondition,
            "days_to_expiry": DaysToExpiryCondition,
            "greeks": GreeksCondition,
            "iv": IVCondition,
            "premium": PremiumCondition,
            "spot_move": SpotMoveCondition,
            "trailing_sl": TrailingStopLossCondition,
        }
        klass = mapping.get(cond_type)
        if klass is None:
            raise ValueError(f"Unknown condition type: {cond_type}")
        return klass.from_dict(d)

    def __and__(self, other: "Condition") -> "AndCondition":
        return AndCondition([self, other])

    def __or__(self, other: "Condition") -> "OrCondition":
        return OrCondition([self, other])

    def __invert__(self) -> "NotCondition":
        return NotCondition(self)


class TrailingStopLossCondition(Condition):
    """
    Evaluates to True if the current PNL has dropped by `trail_pct` or `trail_pts`
    from its highest recorded value since entry.
    """
    def __init__(
        self,
        trail_type: str = "pct",  # 'pct' or 'pts'
        trail_value: float = 10.0
    ):
        self.trail_type = trail_type
        self.trail_value = trail_value
        self.max_pnl = None

    def evaluate(self, ctx: MarketContext) -> bool:
        if not ctx.positions:
            self.max_pnl = None
            return False
            
        current_pnl = sum(p.unrealized_pnl for p in ctx.positions)
        
        if self.max_pnl is None or current_pnl > self.max_pnl:
            self.max_pnl = current_pnl
            
        if self.trail_type == "pts":
            if self.max_pnl - current_pnl >= self.trail_value:
                return True
        elif self.trail_type == "pct":
            # Trail by % drop from max PNL (if max_pnl > 0)
            if self.max_pnl > 0 and ((self.max_pnl - current_pnl) / self.max_pnl) * 100 >= self.trail_value:
                return True
        return False
        
    def to_dict(self) -> dict:
        return {
            "type": "trailing_sl",
            "trail_type": self.trail_type,
            "trail_value": self.trail_value
        }
        
    @classmethod
    def from_dict(cls, d: dict) -> "TrailingStopLossCondition":
        return cls(d.get("trail_type", "pct"), d.get("trail_value", 10.0))


class GreeksCondition(Condition):
    """Evaluate portfolio Greeks against a threshold."""
    def __init__(self, greek: str, operator: str, value: float):
        self.greek = greek.lower()  # delta, gamma, theta, vega, rho
        self.operator = operator
        self.value = value

    def evaluate(self, ctx: MarketContext) -> bool:
        if not ctx.positions:
            return False
        
        val = sum(getattr(p, self.greek, 0.0) or 0.0 for p in ctx.positions)
        return _compare(val, self.operator, self.value)
        
    def to_dict(self) -> dict:
        return {
            "type": "greeks",
            "greek": self.greek,
            "operator": self.operator,
            "value": self.value
        }
        
    @classmethod
    def from_dict(cls, d: dict) -> "GreeksCondition":
        return cls(d["greek"], d["operator"], d["value"])


class IVCondition(Condition):
    """Evaluate implied volatility against a threshold."""
    def __init__(self, operator: str, value: float):
        self.operator = operator
        self.value = value

    def evaluate(self, ctx: MarketContext) -> bool:
        iv_val = getattr(ctx, "current_iv", None)
        if iv_val is None:
            return False
        return _compare(iv_val, self.operator, self.value)
        
    def to_dict(self) -> dict:
        return {
            "type": "iv",
            "operator": self.operator,
            "value": self.value
        }
        
    @classmethod
    def from_dict(cls, d: dict) -> "IVCondition":
        return cls(d["operator"], d["value"])


class PremiumCondition(Condition):
    """Evaluate option premium against a threshold."""
    def __init__(self, option_type: OptionType, strike_sel: StrikeSelection, operator: str, value: float):
        self.option_type = option_type
        self.strike_sel = strike_sel
        self.operator = operator
        self.value = value

    def evaluate(self, ctx: MarketContext) -> bool:
        if ctx.options_chain is None or ctx.options_chain.empty:
            return False
            
        chain = ctx.options_chain
        # Use nearest expiry
        nearest_expiry = sorted(chain["expiry"].unique())[0]
        chain = chain[chain["expiry"] == nearest_expiry]
        
        type_chain = chain[chain["option_type"] == self.option_type.value]
        if type_chain.empty:
            return False
            
        strikes = sorted(type_chain["strike"].unique())
        if not strikes:
            return False
            
        atm_idx = int(np.argmin([abs(s - ctx.spot_price) for s in strikes]))
        sel = self.strike_sel.value
        offset = 0
        if "+" in sel:
            offset = int(sel.split("+")[1])
        elif "-" in sel:
            offset = -int(sel.split("-")[1])
            
        if "OTM" in sel:
            if self.option_type == OptionType.CE:
                target_idx = atm_idx + offset + 1
            else:
                target_idx = atm_idx - offset - 1
        elif "ITM" in sel:
            if self.option_type == OptionType.CE:
                target_idx = atm_idx - offset - 1
            else:
                target_idx = atm_idx + offset + 1
        else:
            target_idx = atm_idx + offset
            
        target_idx = max(0, min(target_idx, len(strikes) - 1))
        target_strike = strikes[target_idx]
        
        row = type_chain[type_chain["strike"] == target_strike]
        if row.empty:
            return False
            
        premium = float(row.iloc[0]["close"])
        return _compare(premium, self.operator, self.value)
        
    def to_dict(self) -> dict:
        return {
            "type": "premium",
            "option_type": self.option_type.value,
            "strike_sel": self.strike_sel.value,
            "operator": self.operator,
            "value": self.value
        }
        
    @classmethod
    def from_dict(cls, d: dict) -> "PremiumCondition":
        return cls(OptionType(d["option_type"]), StrikeSelection(d["strike_sel"]), d["operator"], d["value"])


class SpotMoveCondition(Condition):
    """Evaluate movement of spot price from a reference point (e.g. open)."""
    def __init__(self, ref_point: str, move_type: str, operator: str, value: float):
        self.ref_point = ref_point # 'open', 'prev_close', 'entry'
        self.move_type = move_type # 'pct', 'pts'
        self.operator = operator
        self.value = value
        self.entry_spot = None

    def evaluate(self, ctx: MarketContext) -> bool:
        if self.ref_point == 'open':
            if ctx.is_first_candle:
                self.day_open_spot = ctx.spot_price
            if getattr(self, 'day_open_spot', None) is None:
                return False
            ref_price = self.day_open_spot
        elif self.ref_point == 'entry':
            if not ctx.positions:
                self.entry_spot = None
                return False
            if self.entry_spot is None:
                self.entry_spot = ctx.spot_price
            ref_price = self.entry_spot
        else:
            return False 

        if self.move_type == 'pct':
            move = ((ctx.spot_price - ref_price) / ref_price) * 100
        else:
            move = ctx.spot_price - ref_price

        return _compare(move, self.operator, self.value)
        
    def to_dict(self) -> dict:
        return {
            "type": "spot_move",
            "ref_point": self.ref_point,
            "move_type": self.move_type,
            "operator": self.operator,
            "value": self.value
        }
        
    @classmethod
    def from_dict(cls, d: dict) -> "SpotMoveCondition":
        return cls(d["ref_point"], d["move_type"], d["operator"], d["value"])


class TimeCondition(Condition):
    """
    Time-based condition: checks if current time is at/after/before/between.

    Examples:
      - TimeCondition(operator=">=", value="09:20")  -> entry at or after 9:20
      - TimeCondition(operator="==", value="15:15")  -> exactly at 3:15 PM
      - TimeCondition(operator="between", value="09:20", value2="15:15")
    """

    OPERATORS = {"==", ">=", "<=", ">", "<", "between"}

    def __init__(self, operator: str, value: str, value2: Optional[str] = None):
        if operator not in self.OPERATORS:
            raise ValueError(f"Invalid operator: {operator}")
        self.operator = operator
        self.value = time.fromisoformat(value)
        self.value2 = time.fromisoformat(value2) if value2 else None
        self._value_str = value
        self._value2_str = value2

    def evaluate(self, ctx: MarketContext) -> bool:
        current = ctx.time_of_day
        if self.operator == "==":
            return current == self.value
        elif self.operator == ">=":
            return current >= self.value
        elif self.operator == "<=":
            return current <= self.value
        elif self.operator == ">":
            return current > self.value
        elif self.operator == "<":
            return current < self.value
        elif self.operator == "between":
            return self.value <= current <= self.value2
        return False

    def to_dict(self) -> dict:
        return {
            "type": "time",
            "operator": self.operator,
            "value": self._value_str,
            "value2": self._value2_str,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimeCondition":
        return cls(d["operator"], d["value"], d.get("value2"))


class DayOfWeekCondition(Condition):
    """
    Day-of-week filter. 0=Monday, 4=Friday.
    Example: DayOfWeekCondition(days=[3]) -> Thursday only (expiry day)
    """

    DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday",
                 3: "Thursday", 4: "Friday"}

    def __init__(self, days: List[int]):
        self.days = days

    def evaluate(self, ctx: MarketContext) -> bool:
        return ctx.trading_day.weekday() in self.days

    def to_dict(self) -> dict:
        return {"type": "day_of_week", "days": self.days}

    @classmethod
    def from_dict(cls, d: dict) -> "DayOfWeekCondition":
        return cls(d["days"])


class DaysToExpiryCondition(Condition):
    """
    Condition based on days remaining to expiry.
    Example: DaysToExpiryCondition(operator="<=", value=2) -> 2 DTE or less
    """

    def __init__(self, operator: str, value: int, expiry_key: str = "nearest"):
        self.operator = operator
        self.value = value
        self.expiry_key = expiry_key

    def evaluate(self, ctx: MarketContext) -> bool:
        if not ctx.days_to_expiry:
            return False
        if self.expiry_key == "nearest":
            dte = min(ctx.days_to_expiry.values()) if ctx.days_to_expiry else None
        else:
            dte = ctx.days_to_expiry.get(self.expiry_key)
        if dte is None:
            return False
        return _compare(dte, self.operator, self.value)

    def to_dict(self) -> dict:
        return {
            "type": "days_to_expiry",
            "operator": self.operator,
            "value": self.value,
            "expiry_key": self.expiry_key,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DaysToExpiryCondition":
        return cls(d["operator"], d["value"], d.get("expiry_key", "nearest"))


class PriceCondition(Condition):
    """
    Price-based condition on spot, option premium, or portfolio.

    field options:
      - "spot" -> ctx.spot_price
      - "portfolio_value" -> ctx.portfolio_value
      - "day_pnl" -> ctx.day_pnl
      - "total_pnl" -> ctx.total_pnl
      - "position_pnl_pct" -> unrealized P&L % of first position
      - "position_pnl_abs" -> unrealized P&L absolute
    """

    def __init__(self, field: str, operator: str, value: float):
        self.field = field
        self.operator = operator
        self.value = value

    def evaluate(self, ctx: MarketContext) -> bool:
        actual = self._get_field_value(ctx)
        if actual is None:
            return False
        return _compare(actual, self.operator, self.value)

    def _get_field_value(self, ctx: MarketContext) -> Optional[float]:
        if self.field == "spot":
            return ctx.spot_price
        elif self.field == "portfolio_value":
            return ctx.portfolio_value
        elif self.field == "day_pnl":
            return ctx.day_pnl
        elif self.field == "total_pnl":
            return ctx.total_pnl
        elif self.field == "day_pnl_pct":
            if ctx.portfolio_value > 0:
                return (ctx.day_pnl / ctx.portfolio_value) * 100
            return 0.0
        elif self.field == "position_pnl_pct":
            if ctx.positions:
                pos = ctx.positions[0]
                if pos.entry_price > 0:
                    if pos.side == Side.BUY:
                        return ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
                    else:
                        return ((pos.entry_price - pos.current_price) / pos.entry_price) * 100
            return None
        elif self.field == "position_pnl_abs":
            if ctx.positions:
                return ctx.positions[0].unrealized_pnl
            return None
        else:
            return None

    def to_dict(self) -> dict:
        return {
            "type": "price",
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PriceCondition":
        return cls(d["field"], d["operator"], d["value"])


class IndicatorCondition(Condition):
    """
    Indicator-based condition.

    Compares a technical indicator value against a threshold or another indicator.

    Examples:
      - IndicatorCondition("RSI", {"period": 14}, "close", ">", 70)
      - IndicatorCondition("SMA", {"period": 20}, "close", "crossover", "SMA_50")
    """

    def __init__(self, indicator_name: str, params: Dict[str, Any],
                 input_field: str, operator: str, value: Union[float, str],
                 output_key: Optional[str] = None):
        self.indicator_name = indicator_name
        self.params = params
        self.input_field = input_field
        self.operator = operator
        self.value = value
        self.output_key = output_key  # For multi-output indicators

    def evaluate(self, ctx: MarketContext) -> bool:
        # The indicator value should be pre-computed and stored in ctx.indicators
        key = self._make_key()
        actual = ctx.indicators.get(key)
        if actual is None:
            return False

        if isinstance(self.value, str):
            # Compare against another indicator
            compare_val = ctx.indicators.get(self.value)
            if compare_val is None:
                return False
        else:
            compare_val = self.value

        if self.operator == "crossover":
            # Check if indicator just crossed above the compare value
            prev_key = f"{key}_prev"
            prev_actual = ctx.indicators.get(prev_key)
            prev_compare = ctx.indicators.get(f"{self.value}_prev", compare_val)
            if prev_actual is None:
                return False
            return prev_actual <= prev_compare and actual > compare_val
        elif self.operator == "crossunder":
            prev_key = f"{key}_prev"
            prev_actual = ctx.indicators.get(prev_key)
            prev_compare = ctx.indicators.get(f"{self.value}_prev", compare_val)
            if prev_actual is None:
                return False
            return prev_actual >= prev_compare and actual < compare_val
        else:
            return _compare(actual, self.operator, compare_val)

    def _make_key(self) -> str:
        param_str = "_".join(f"{k}{v}" for k, v in sorted(self.params.items()))
        base = f"{self.indicator_name}_{param_str}"
        if self.output_key:
            base += f"_{self.output_key}"
        return base

    def to_dict(self) -> dict:
        return {
            "type": "indicator",
            "indicator_name": self.indicator_name,
            "params": self.params,
            "input_field": self.input_field,
            "operator": self.operator,
            "value": self.value,
            "output_key": self.output_key,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IndicatorCondition":
        return cls(
            d["indicator_name"], d["params"], d["input_field"],
            d["operator"], d["value"], d.get("output_key"),
        )


class PositionCondition(Condition):
    """
    Condition based on current position state.
    Useful for exit logic: "exit if I have a position."
    """

    def __init__(self, check: str = "has_position", tag: Optional[str] = None):
        """
        check options:
          - "has_position": True if any position is open
          - "no_position": True if no positions
          - "position_count_gte": True if positions >= value
        """
        self.check = check
        self.tag = tag

    def evaluate(self, ctx: MarketContext) -> bool:
        positions = ctx.positions
        if self.tag:
            positions = [p for p in positions if p.tag == self.tag]

        if self.check == "has_position":
            return len(positions) > 0
        elif self.check == "no_position":
            return len(positions) == 0
        return False

    def to_dict(self) -> dict:
        return {"type": "position", "check": self.check, "tag": self.tag}

    @classmethod
    def from_dict(cls, d: dict) -> "PositionCondition":
        return cls(d["check"], d.get("tag"))


# ──────────────────────────────────────────────────────────────
# Composite Conditions
# ──────────────────────────────────────────────────────────────

class AndCondition(Condition):
    def __init__(self, conditions: List[Condition]):
        self.conditions = conditions

    def evaluate(self, ctx: MarketContext) -> bool:
        return all(c.evaluate(ctx) for c in self.conditions)

    def to_dict(self) -> dict:
        return {"type": "and", "conditions": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, d: dict) -> "AndCondition":
        return cls([Condition.from_dict(c) for c in d["conditions"]])


class OrCondition(Condition):
    def __init__(self, conditions: List[Condition]):
        self.conditions = conditions

    def evaluate(self, ctx: MarketContext) -> bool:
        return any(c.evaluate(ctx) for c in self.conditions)

    def to_dict(self) -> dict:
        return {"type": "or", "conditions": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, d: dict) -> "OrCondition":
        return cls([Condition.from_dict(c) for c in d["conditions"]])


class NotCondition(Condition):
    def __init__(self, condition: Condition):
        self.condition = condition

    def evaluate(self, ctx: MarketContext) -> bool:
        return not self.condition.evaluate(ctx)

    def to_dict(self) -> dict:
        return {"type": "not", "condition": self.condition.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "NotCondition":
        return cls(Condition.from_dict(d["condition"]))


# ──────────────────────────────────────────────────────────────
# Rules — combine conditions with actions
# ──────────────────────────────────────────────────────────────

@dataclass
class Rule:
    """A rule: when condition is met, execute these orders."""
    name: str
    condition: Condition
    orders: List[Order]
    is_entry: bool = True  # True for entry rules, False for exit rules
    max_triggers_per_day: int = 1  # Prevent repeated entries
    _trigger_count: int = field(default=0, repr=False)

    def should_fire(self, ctx: MarketContext) -> bool:
        if self._trigger_count >= self.max_triggers_per_day:
            return False
        return self.condition.evaluate(ctx)

    def fire(self):
        self._trigger_count += 1

    def reset_daily(self):
        self._trigger_count = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "condition": self.condition.to_dict(),
            "orders": [
                {
                    "side": o.side.value,
                    "option_type": o.option_type.value,
                    "strike_selection": o.strike_selection.value,
                    "fixed_strike": o.fixed_strike,
                    "quantity": o.quantity,
                    "order_type": o.order_type.value,
                    "limit_price": o.limit_price,
                    "expiry_selection": o.expiry_selection,
                    "tag": o.tag,
                }
                for o in self.orders
            ],
            "is_entry": self.is_entry,
            "max_triggers_per_day": self.max_triggers_per_day,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        orders = []
        for o in d.get("orders", []):
            orders.append(Order(
                side=Side(o["side"]),
                option_type=OptionType(o["option_type"]),
                strike_selection=StrikeSelection(o.get("strike_selection", "ATM")),
                fixed_strike=o.get("fixed_strike"),
                quantity=o.get("quantity", 1),
                order_type=OrderType(o.get("order_type", "MARKET")),
                limit_price=o.get("limit_price"),
                expiry_selection=o.get("expiry_selection", "nearest"),
                tag=o.get("tag", ""),
            ))
        return cls(
            name=d["name"],
            condition=Condition.from_dict(d["condition"]),
            orders=orders,
            is_entry=d.get("is_entry", True),
            max_triggers_per_day=d.get("max_triggers_per_day", 1),
        )


# ──────────────────────────────────────────────────────────────
# Strategy base class
# ──────────────────────────────────────────────────────────────

class Strategy(ABC):
    """
    Abstract base class for strategies.

    Subclass this to write custom strategies in code:

        class MyStrategy(Strategy):
            def on_candle(self, ctx):
                if ctx.time_of_day == time(9, 20) and not ctx.positions:
                    return [Order(Side.SELL, OptionType.CE)]
                if ctx.time_of_day >= time(15, 15) and ctx.positions:
                    return "SQUARE_OFF_ALL"
                return []
    """

    name: str = "Unnamed Strategy"
    description: str = ""

    def on_init(self, config: dict):
        """Called once before the backtest starts. Override for setup."""
        pass

    @abstractmethod
    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        """
        Called on every candle. Must return one of:
          - List[Order]: orders to place
          - "SQUARE_OFF_ALL": close all positions
          - None or []: no action
        """
        pass

    def on_day_start(self, ctx: MarketContext):
        """Called at the start of each trading day."""
        pass

    def on_day_end(self, ctx: MarketContext):
        """Called at the end of each trading day."""
        pass

    def on_trade(self, trade: Trade, ctx: MarketContext):
        """Called when a trade is completed (position closed)."""
        pass

    def required_indicators(self) -> List[dict]:
        """
        Return list of indicator configs needed by this strategy.
        The engine will pre-compute these and make them available in ctx.indicators.

        Example:
            return [
                {"name": "RSI", "params": {"period": 14}, "input": "close"},
                {"name": "SMA", "params": {"period": 20}, "input": "close"},
            ]
        """
        return []

    def to_dict(self) -> dict:
        """Serialize strategy config (for API/GUI)."""
        return {
            "name": self.name,
            "description": self.description,
            "type": "custom",
        }


class RuleBasedStrategy(Strategy):
    """
    A strategy defined by entry/exit rules — used by the GUI builder.
    No code writing needed; everything is configured through JSON rules.

    Example:
        strategy = RuleBasedStrategy(
            name="9:20 Short Straddle",
            entry_rules=[
                Rule("Enter at 9:20", TimeCondition("==", "09:20"), [
                    Order(Side.SELL, OptionType.CE, StrikeSelection.ATM),
                    Order(Side.SELL, OptionType.PE, StrikeSelection.ATM),
                ])
            ],
            exit_rules=[
                Rule("Exit at 15:15", TimeCondition(">=", "15:15"), [], is_entry=False),
                Rule("Stop Loss", PriceCondition("position_pnl_pct", "<=", -2.0), [], is_entry=False),
            ]
        )
    """

    def __init__(self, name: str = "Rule-Based Strategy",
                 description: str = "",
                 entry_rules: Optional[List[Rule]] = None,
                 exit_rules: Optional[List[Rule]] = None,
                 square_off_time: Optional[str] = None,
                 max_positions: int = 10):
        self.name = name
        self.description = description
        self.entry_rules = entry_rules or []
        self.exit_rules = exit_rules or []
        self.square_off_time = time.fromisoformat(square_off_time) if square_off_time else None
        self.max_positions = max_positions

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        # Check auto square-off time
        if self.square_off_time and ctx.time_of_day >= self.square_off_time:
            if ctx.positions:
                return "SQUARE_OFF_ALL"
            return None

        # Check exit rules first (risk management)
        if ctx.positions:
            for rule in self.exit_rules:
                if rule.should_fire(ctx):
                    rule.fire()
                    log.info(f"EXIT RULE fired: {rule.name} at {ctx.timestamp}")
                    return "SQUARE_OFF_ALL"

        # Check entry rules
        if len(ctx.positions) < self.max_positions:
            for rule in self.entry_rules:
                if rule.should_fire(ctx):
                    rule.fire()
                    log.info(f"ENTRY RULE fired: {rule.name} at {ctx.timestamp}")
                    return rule.orders

        return None

    def on_day_start(self, ctx: MarketContext):
        for rule in self.entry_rules + self.exit_rules:
            rule.reset_daily()

    def required_indicators(self) -> List[dict]:
        """Collect all indicators needed by all rules."""
        indicators = []
        for rule in self.entry_rules + self.exit_rules:
            indicators.extend(self._collect_indicators(rule.condition))
        return indicators

    def _collect_indicators(self, condition: Condition) -> List[dict]:
        if isinstance(condition, IndicatorCondition):
            return [{
                "name": condition.indicator_name,
                "params": condition.params,
                "input": condition.input_field,
                "output_key": condition.output_key,
            }]
        elif isinstance(condition, (AndCondition, OrCondition)):
            result = []
            for c in condition.conditions:
                result.extend(self._collect_indicators(c))
            return result
        elif isinstance(condition, NotCondition):
            return self._collect_indicators(condition.condition)
        return []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": "rule_based",
            "entry_rules": [r.to_dict() for r in self.entry_rules],
            "exit_rules": [r.to_dict() for r in self.exit_rules],
            "square_off_time": self.square_off_time.isoformat() if self.square_off_time else None,
            "max_positions": self.max_positions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuleBasedStrategy":
        return cls(
            name=d.get("name", "Untitled"),
            description=d.get("description", ""),
            entry_rules=[Rule.from_dict(r) for r in d.get("entry_rules", [])],
            exit_rules=[Rule.from_dict(r) for r in d.get("exit_rules", [])],
            square_off_time=d.get("square_off_time"),
            max_positions=d.get("max_positions", 10),
        )


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _compare(a: float, operator: str, b: float) -> bool:
    """Generic comparison helper."""
    if operator == "==":
        return a == b
    elif operator == "!=":
        return a != b
    elif operator == ">":
        return a > b
    elif operator == ">=":
        return a >= b
    elif operator == "<":
        return a < b
    elif operator == "<=":
        return a <= b
    return False
