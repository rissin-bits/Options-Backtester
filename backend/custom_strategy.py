"""
custom_strategy.py — user-built multi-leg strategies for the Backtest builder.

Unlike the ready-made templates (fixed shapes with a few knobs), a
CustomLegStrategy is assembled leg-by-leg in the UI: each leg has its own
side / option type / strike method / expiry / lots and its own risk controls
(stop-loss, take-profit, trailing, move-to-cost). The engine enforces the
per-leg risk on the resulting positions; this class only decides *when* to open
the batch, when to square off, and whether to re-enter.
"""
from __future__ import annotations

from datetime import time
from typing import List, Optional, Union

from backend.strategy import (
    Strategy, MarketContext, Order, Condition,
    IndicatorCondition, AndCondition, OrCondition, NotCondition,
)


def _collect_indicators(condition: Optional[Condition]) -> List[dict]:
    """Recursively gather the indicators a condition tree needs pre-computed."""
    if condition is None:
        return []
    if isinstance(condition, IndicatorCondition):
        return [{
            "name": condition.indicator_name,
            "params": condition.params,
            "input": condition.input_field,
            "output_key": condition.output_key,
        }]
    if isinstance(condition, (AndCondition, OrCondition)):
        out = []
        for c in condition.conditions:
            out.extend(_collect_indicators(c))
        return out
    if isinstance(condition, NotCondition):
        return _collect_indicators(condition.condition)
    return []


def _hhmm(value, fallback: time) -> time:
    if isinstance(value, time):
        return value
    try:
        h, m = str(value).split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return fallback


class CustomLegStrategy(Strategy):
    """A batch of legs entered together, with optional re-entry."""

    def __init__(
        self,
        name: str = "Custom Strategy",
        description: str = "",
        legs: Optional[List[Order]] = None,
        entry_time: str = "09:20",
        square_off_time: str = "15:15",
        max_entries_per_day: int = 1,
        re_entry: bool = False,
        entry_condition: Optional[Condition] = None,
        exit_condition: Optional[Condition] = None,
        overall_stop_loss: Optional[float] = None,   # ₹ loss on the combined batch
        overall_take_profit: Optional[float] = None,  # ₹ profit on the combined batch
    ):
        self.name = name
        self.description = description
        self.legs = legs or []
        self.entry_after = _hhmm(entry_time, time(9, 20))
        self.square_off = _hhmm(square_off_time, time(15, 15))
        # Re-entry lets the batch be re-opened after it fully closes, up to the
        # per-day cap. Without it, one batch per day.
        self.re_entry = bool(re_entry)
        self.max_entries = max(1, int(max_entries_per_day)) if re_entry else 1
        self.entry_condition = entry_condition   # extra gate on top of entry_time
        self.exit_condition = exit_condition     # when true, square off the batch
        self.overall_sl = overall_stop_loss
        self.overall_tp = overall_take_profit
        self._entries_today = 0

    def required_indicators(self):
        # Indicators referenced by either the entry or exit condition tree.
        return (_collect_indicators(self.entry_condition)
                + _collect_indicators(self.exit_condition))

    def on_day_start(self, ctx: MarketContext):
        self._entries_today = 0

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        t = ctx.time_of_day

        # End of the trade window → flatten and stop for the day.
        if t >= self.square_off:
            return "SQUARE_OFF_ALL" if ctx.positions else None

        # Overall (per-trade) target: close the whole batch when its combined
        # open P&L crosses the ₹ stop-loss or take-profit.
        if ctx.positions and (self.overall_sl is not None or self.overall_tp is not None):
            combined = sum(p.unrealized_pnl for p in ctx.positions)
            if self.overall_tp is not None and combined >= abs(self.overall_tp):
                return "SQUARE_OFF_ALL"
            if self.overall_sl is not None and combined <= -abs(self.overall_sl):
                return "SQUARE_OFF_ALL"

        # Exit-When: a live batch is squared off as soon as the exit rule fires.
        if ctx.positions and self.exit_condition is not None:
            if self.exit_condition.evaluate(ctx):
                return "SQUARE_OFF_ALL"

        # Not yet in the entry window.
        if t < self.entry_after:
            return None

        # A batch is already live — leave it to the per-leg risk / square-off.
        if ctx.positions:
            return None

        # Flat inside the window: open a (re-)entry if we still have budget.
        if self._entries_today >= self.max_entries:
            return None
        if self.entry_condition is not None and not self.entry_condition.evaluate(ctx):
            return None

        self._entries_today += 1
        return list(self.legs)
