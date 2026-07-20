"""
example_strategies.py — Sample strategies demonstrating the framework.

These can be used directly via code or serve as templates for the GUI.
"""
from datetime import time

from backend.strategy import (
    Strategy, RuleBasedStrategy, Rule, Order, MarketContext,
    TimeCondition, PriceCondition, IndicatorCondition, PositionCondition,
    DayOfWeekCondition, DaysToExpiryCondition, AndCondition,
    Side, OptionType, StrikeSelection,
)
from typing import List, Union, Optional


# ──────────────────────────────────────────────────────────────
# 1. Short Straddle — sell ATM CE + PE at 9:20, exit at 15:15
# ──────────────────────────────────────────────────────────────

short_straddle_920 = RuleBasedStrategy(
    name="9:20 Short Straddle",
    description="Sell ATM CE + PE at 9:20 AM, square off at 3:15 PM. "
                "Classic intraday theta decay strategy.",
    entry_rules=[
        Rule(
            name="Enter at 9:20 AM",
            condition=AndCondition([
                TimeCondition(">=", "09:20"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM, tag="straddle_ce"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM, tag="straddle_pe"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 30% of premium",
            condition=PriceCondition("position_pnl_pct", "<=", -30.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)


# ──────────────────────────────────────────────────────────────
# 2. Expiry Day Straddle — Thursday only
# ──────────────────────────────────────────────────────────────

expiry_day_straddle = RuleBasedStrategy(
    name="Expiry Day Short Straddle",
    description="Sell ATM straddle only on Thursday (weekly expiry), "
                "with tighter stop loss.",
    entry_rules=[
        Rule(
            name="Enter on Thursday at 9:20",
            condition=AndCondition([
                DayOfWeekCondition(days=[3]),  # Thursday
                TimeCondition(">=", "09:20"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss 20%",
            condition=PriceCondition("position_pnl_pct", "<=", -20.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:20",
)


# ──────────────────────────────────────────────────────────────
# 3. Iron Condor — OTM CE + OTM PE sell with protection
# ──────────────────────────────────────────────────────────────

iron_condor = RuleBasedStrategy(
    name="Iron Condor",
    description="Sell OTM CE + OTM PE, buy further OTM for protection. "
                "Defined risk, limited reward.",
    entry_rules=[
        Rule(
            name="Enter Iron Condor at 9:30",
            condition=AndCondition([
                TimeCondition(">=", "09:30"),
                PositionCondition("no_position"),
            ]),
            orders=[
                # Sell OTM CE (ATM+2)
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM_PLUS_2, tag="short_ce"),
                # Buy further OTM CE for protection
                Order(Side.BUY, OptionType.CE, StrikeSelection.ATM_PLUS_2, tag="long_ce"),
                # Sell OTM PE (ATM-2)
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM_MINUS_2, tag="short_pe"),
                # Buy further OTM PE for protection
                Order(Side.BUY, OptionType.PE, StrikeSelection.ATM_MINUS_2, tag="long_pe"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 100% of credit",
            condition=PriceCondition("position_pnl_pct", "<=", -100.0),
            orders=[],
            is_entry=False,
        ),
        Rule(
            name="Profit target 50% of max",
            condition=PriceCondition("position_pnl_pct", ">=", 50.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:10",
)


# ──────────────────────────────────────────────────────────────
# 4. RSI Mean Reversion — buy when RSI < 30, sell when RSI > 70
# ──────────────────────────────────────────────────────────────

rsi_mean_reversion = RuleBasedStrategy(
    name="RSI Mean Reversion",
    description="Buy ATM CE when RSI(14) drops below 30, exit when RSI > 70 "
                "or at square-off time. Contrarian intraday strategy.",
    entry_rules=[
        Rule(
            name="RSI Oversold Entry",
            condition=AndCondition([
                IndicatorCondition("RSI", {"period": 14}, "close", "<", 30),
                PositionCondition("no_position"),
                TimeCondition("between", "09:30", "14:30"),
            ]),
            orders=[
                Order(Side.BUY, OptionType.CE, StrikeSelection.ATM),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="RSI Overbought Exit",
            condition=IndicatorCondition("RSI", {"period": 14}, "close", ">", 70),
            orders=[],
            is_entry=False,
        ),
        Rule(
            name="Stop Loss 5%",
            condition=PriceCondition("position_pnl_pct", "<=", -5.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)


# ──────────────────────────────────────────────────────────────
# 5. Short Strangle — sell OTM CE + PE at 9:30
# ──────────────────────────────────────────────────────────────

short_strangle = RuleBasedStrategy(
    name="Short Strangle",
    description="Sell OTM CE + OTM PE. Benefits from theta decay and flat markets.",
    entry_rules=[
        Rule(
            name="Enter Strangle at 9:30",
            condition=AndCondition([
                TimeCondition(">=", "09:30"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM_PLUS_2, tag="short_ce"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM_MINUS_2, tag="short_pe"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 50% of premium",
            condition=PriceCondition("position_pnl_pct", "<=", -50.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)

# ──────────────────────────────────────────────────────────────
# 6. Bull Call Spread — Buy ATM CE, Sell OTM CE
# ──────────────────────────────────────────────────────────────

bull_call_spread = RuleBasedStrategy(
    name="Bull Call Spread",
    description="Buy ATM CE, Sell OTM CE. Defined risk bullish strategy.",
    entry_rules=[
        Rule(
            name="Enter Bull Call Spread at 9:30",
            condition=AndCondition([
                TimeCondition(">=", "09:30"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.BUY, OptionType.CE, StrikeSelection.ATM, tag="long_ce"),
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM_PLUS_2, tag="short_ce"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 50% of premium",
            condition=PriceCondition("position_pnl_pct", "<=", -50.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)

# ──────────────────────────────────────────────────────────────
# 7. Bear Put Spread — Buy ATM PE, Sell OTM PE
# ──────────────────────────────────────────────────────────────

bear_put_spread = RuleBasedStrategy(
    name="Bear Put Spread",
    description="Buy ATM PE, Sell OTM PE. Defined risk bearish strategy.",
    entry_rules=[
        Rule(
            name="Enter Bear Put Spread at 9:30",
            condition=AndCondition([
                TimeCondition(">=", "09:30"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.BUY, OptionType.PE, StrikeSelection.ATM, tag="long_pe"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM_MINUS_2, tag="short_pe"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 50% of premium",
            condition=PriceCondition("position_pnl_pct", "<=", -50.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)

# ──────────────────────────────────────────────────────────────
# 8. Iron Butterfly — Sell ATM CE/PE, Buy OTM CE/PE
# ──────────────────────────────────────────────────────────────

iron_butterfly = RuleBasedStrategy(
    name="Iron Butterfly",
    description="Sell ATM straddle, buy OTM strangles for protection.",
    entry_rules=[
        Rule(
            name="Enter Iron Butterfly at 9:30",
            condition=AndCondition([
                TimeCondition(">=", "09:30"),
                PositionCondition("no_position"),
            ]),
            orders=[
                Order(Side.SELL, OptionType.CE, StrikeSelection.ATM, tag="short_ce"),
                Order(Side.SELL, OptionType.PE, StrikeSelection.ATM, tag="short_pe"),
                Order(Side.BUY, OptionType.CE, StrikeSelection.ATM_PLUS_2, tag="long_ce"),
                Order(Side.BUY, OptionType.PE, StrikeSelection.ATM_MINUS_2, tag="long_pe"),
            ],
        ),
    ],
    exit_rules=[
        Rule(
            name="Stop Loss at 50% of premium",
            condition=PriceCondition("position_pnl_pct", "<=", -50.0),
            orders=[],
            is_entry=False,
        ),
    ],
    square_off_time="15:15",
)


# ──────────────────────────────────────────────────────────────
# 9. Custom code strategy — VWAP Breakout
# ──────────────────────────────────────────────────────────────

class VWAPBreakoutStrategy(Strategy):
    """
    Example of a fully custom strategy written in code.

    Logic:
      - After 9:30, if spot crosses above VWAP → buy ATM CE
      - If spot crosses below VWAP → buy ATM PE
      - Stop loss: 3% of premium
      - Target: 5% of premium
      - Square off at 15:15
    """

    name = "VWAP Breakout"
    description = "Buy CE/PE based on VWAP crossover direction."

    def __init__(self):
        self.prev_spot = None
        self.prev_vwap = None

    def required_indicators(self):
        return [
            {"name": "VWAP", "params": {"reset_daily": True},
             "input": "close"},
        ]

    def on_candle(self, ctx: MarketContext) -> Union[List[Order], str, None]:
        vwap_val = ctx.indicators.get("VWAP_reset_dailyTrue")
        if vwap_val is None:
            return None

        # Square off time
        if ctx.time_of_day >= time(15, 15):
            if ctx.positions:
                return "SQUARE_OFF_ALL"
            return None

        # Too early
        if ctx.time_of_day < time(9, 30):
            self.prev_spot = ctx.spot_price
            self.prev_vwap = vwap_val
            return None

        # Check stop loss / target on existing positions
        if ctx.positions:
            for pos in ctx.positions:
                if pos.entry_price > 0:
                    if pos.side == Side.BUY:
                        pnl_pct = ((pos.current_price - pos.entry_price)
                                   / pos.entry_price) * 100
                    else:
                        pnl_pct = ((pos.entry_price - pos.current_price)
                                   / pos.entry_price) * 100

                    if pnl_pct <= -3.0:  # Stop loss
                        return "SQUARE_OFF_ALL"
                    if pnl_pct >= 5.0:   # Target
                        return "SQUARE_OFF_ALL"
            self.prev_spot = ctx.spot_price
            self.prev_vwap = vwap_val
            return None

        # Crossover detection
        if self.prev_spot is not None and self.prev_vwap is not None:
            # Bullish crossover: prev below VWAP, now above
            if self.prev_spot <= self.prev_vwap and ctx.spot_price > vwap_val:
                self.prev_spot = ctx.spot_price
                self.prev_vwap = vwap_val
                return [Order(Side.BUY, OptionType.CE, StrikeSelection.ATM)]

            # Bearish crossover: prev above VWAP, now below
            if self.prev_spot >= self.prev_vwap and ctx.spot_price < vwap_val:
                self.prev_spot = ctx.spot_price
                self.prev_vwap = vwap_val
                return [Order(Side.BUY, OptionType.PE, StrikeSelection.ATM)]

        self.prev_spot = ctx.spot_price
        self.prev_vwap = vwap_val
        return None

    def on_day_start(self, ctx):
        self.prev_spot = None
        self.prev_vwap = None


# ──────────────────────────────────────────────────────────────
# Strategy registry — for API
# ──────────────────────────────────────────────────────────────

EXAMPLE_STRATEGIES = {
    "short_straddle_920": short_straddle_920,
    "expiry_day_straddle": expiry_day_straddle,
    "iron_condor": iron_condor,
    "rsi_mean_reversion": rsi_mean_reversion,
    "short_strangle": short_strangle,
    "bull_call_spread": bull_call_spread,
    "bear_put_spread": bear_put_spread,
    "iron_butterfly": iron_butterfly,
    "vwap_breakout": VWAPBreakoutStrategy(),
}
