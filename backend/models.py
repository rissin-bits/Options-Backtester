"""
models.py — Pydantic models for the REST API.

These models define the request/response schema for all API endpoints.
They also handle serialization between the frontend GUI and the backend engine.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────

class SideEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionTypeEnum(str, Enum):
    CE = "CE"
    PE = "PE"


class StrikeSelectionEnum(str, Enum):
    ATM = "ATM"
    ATM_PLUS_1 = "ATM+1"
    ATM_PLUS_2 = "ATM+2"
    ATM_MINUS_1 = "ATM-1"
    ATM_MINUS_2 = "ATM-2"
    FIXED = "FIXED"


# ──────────────────────────────────────────────────────────────
# Condition models (for strategy builder)
# ──────────────────────────────────────────────────────────────

class ConditionModel(BaseModel):
    """A single condition in the rule engine."""
    type: str  # "time", "price", "indicator", "position", "and", "or", "not", etc.
    operator: Optional[str] = None
    value: Optional[Any] = None
    value2: Optional[Any] = None
    field: Optional[str] = None
    indicator_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    input_field: Optional[str] = None
    output_key: Optional[str] = None
    check: Optional[str] = None
    tag: Optional[str] = None
    days: Optional[List[int]] = None
    expiry_key: Optional[str] = None
    conditions: Optional[List["ConditionModel"]] = None
    condition: Optional["ConditionModel"] = None


# Enable self-referencing
ConditionModel.model_rebuild()


class OrderModel(BaseModel):
    """An order specification."""
    side: SideEnum
    option_type: OptionTypeEnum
    strike_selection: StrikeSelectionEnum = StrikeSelectionEnum.ATM
    fixed_strike: Optional[float] = None
    quantity: int = 1
    expiry_selection: str = "nearest"
    tag: str = ""


class RuleModel(BaseModel):
    """A rule combining condition + orders."""
    name: str
    condition: ConditionModel
    orders: List[OrderModel] = []
    is_entry: bool = True
    max_triggers_per_day: int = 1


class StrategyConfigModel(BaseModel):
    """Full strategy configuration (from GUI or API)."""
    name: str = "Untitled Strategy"
    description: str = ""
    type: str = "rule_based"  # "rule_based" or "custom"
    entry_rules: List[RuleModel] = []
    exit_rules: List[RuleModel] = []
    square_off_time: Optional[str] = None  # "15:15"
    max_positions: int = 10


# ── Custom leg builder (Backtest builder) ──────────────────────

class LegModel(BaseModel):
    """One leg in the visual builder, with its own risk controls."""
    side: SideEnum = SideEnum.SELL
    option_type: OptionTypeEnum = OptionTypeEnum.CE
    moneyness: str = "ATM"            # "ATM" | "OTM" | "ITM"
    strike_offset: int = 0            # strikes away from ATM (for OTM/ITM)
    # Alternative strike selection. When strike_method is "fixed"/"premium"/
    # "delta" it overrides moneyness; strike_dir is "near"/"gte"/"lte".
    strike_method: Optional[str] = None
    strike_value: Optional[float] = None
    strike_dir: str = "near"
    expiry_selection: str = "nearest"  # "nearest" | "next" | "monthly"
    lots: int = 1
    # Per-leg risk (percent of entry premium; None = disabled)
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_sl_pct: Optional[float] = None
    move_to_cost_at_pct: Optional[float] = None
    tag: str = ""


class CaseModel(BaseModel):
    """One parallel case: its own legs, entry timing/logic and exit logic."""
    name: str = "Case"
    legs: List[LegModel] = []
    entry_time: str = "09:20"
    max_entries_per_day: int = 1
    re_entry: bool = False
    entry_conditions: List[ConditionModel] = []
    exit_conditions: List[ConditionModel] = []


class CustomStrategyModel(BaseModel):
    """A user-built multi-leg strategy assembled in the Backtest builder."""
    name: str = "Custom Strategy"
    legs: List[LegModel] = []
    entry_time: str = "09:20"
    square_off_time: str = "15:15"
    max_entries_per_day: int = 1
    re_entry: bool = False
    # Parallel cases. When non-empty, these run side by side and the top-level
    # legs/conditions above are ignored (square_off + targets stay shared).
    cases: List[CaseModel] = []
    # Positional = hold across days (exit on expiry / stop / target / condition);
    # otherwise intraday (square off every day at square_off_time).
    positional: bool = False
    # Optional Entry-When (all must hold, on top of entry_time) and Exit-When
    # (any triggers a square-off) conditions, e.g. indicator or spot thresholds.
    entry_conditions: List[ConditionModel] = []
    exit_conditions: List[ConditionModel] = []
    # Overall (per-trade) targets on the combined batch P&L, in ₹.
    overall_stop_loss: Optional[float] = None
    overall_take_profit: Optional[float] = None


# ──────────────────────────────────────────────────────────────
# Backtest request / response
# ──────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    """Request to run a backtest."""
    strategy: Optional[StrategyConfigModel] = None
    strategy_id: Optional[str] = None
    # Adjustments for a ready-made strategy identified by strategy_id, keyed by
    # the param `key`s from GET /api/strategies/templates. Ignored for inline
    # `strategy` configs.
    params: Optional[Dict[str, Any]] = None
    # A user-built multi-leg strategy from the Backtest builder.
    custom_strategy: Optional[CustomStrategyModel] = None
    underlying: str = "NIFTY"
    start_date: str  # "2024-01-01"
    end_date: str     # "2024-03-31"
    initial_capital: float = 1_000_000.0
    lot_size: int = 50
    granularity: str = "1min"
    slippage_pct: float = 0.05
    commission_per_lot: float = 20.0
    max_loss_per_day: Optional[float] = None
    max_loss_per_day_pct: Optional[float] = None
    max_profit_per_day: Optional[float] = None
    max_profit_per_day_pct: Optional[float] = None


class TradeModel(BaseModel):
    """A completed trade in results."""
    id: str
    side: str
    option_type: str
    strike: float
    expiry: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: str
    exit_time: str
    pnl: float
    pnl_pct: float
    tag: str = ""
    exit_reason: str = ""


class DailyStatsModel(BaseModel):
    """Daily statistics."""
    date: str
    pnl: float
    cumulative_pnl: float
    portfolio_value: float
    num_trades: int


class EquityCurvePoint(BaseModel):
    timestamp: str
    value: float


class BacktestResultModel(BaseModel):
    """Full backtest result response."""
    # Summary stats
    strategy_name: str
    underlying: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_pnl_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    avg_trade_duration: float
    max_consecutive_wins: int
    max_consecutive_losses: int

    # Detailed data
    trades: List[TradeModel] = []
    daily_stats: List[DailyStatsModel] = []
    equity_curve: List[EquityCurvePoint] = []


# ──────────────────────────────────────────────────────────────
# Data exploration endpoints
# ──────────────────────────────────────────────────────────────

class UnderlyingInfo(BaseModel):
    """Info about an available underlying."""
    name: str
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    granularities: List[str] = []
    total_rows: int = 0
    lot_size: int = 50


class OptionsChainRequest(BaseModel):
    """Request for historical options chain."""
    underlying: str
    date: str  # "2024-01-25"
    time: Optional[str] = None  # "09:30:00"
    expiry: Optional[str] = None


class OptionsChainRow(BaseModel):
    """A single row in the options chain."""
    strike: float
    option_type: str
    expiry: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: Optional[float] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    moneyness: Optional[str] = None  # ITM, ATM, OTM


class ExpiryInfo(BaseModel):
    """Info about a valid expiry."""
    expiry: str
    dte: Optional[int] = None  # days to expiry from ref date


class TradingDateInfo(BaseModel):
    """A single trading date."""
    date: str


class IndicatorInfo(BaseModel):
    """Info about an available indicator."""
    name: str
    description: str
    params: Dict[str, Any]
    inputs: List[str]
    outputs: Optional[List[str]] = None


class StatusResponse(BaseModel):
    """API status."""
    status: str
    version: str
    data_available: bool
    underlyings: List[str]
