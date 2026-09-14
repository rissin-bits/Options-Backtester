"""
engine.py — Core backtesting engine for options.

Orchestrates:
  1. Data loading and chronological iteration
  2. Options chain reconstruction per timestamp
  3. Indicator pre-computation
  4. Strategy evaluation (entry/exit conditions)
  5. Order execution and position management
  6. P&L tracking and result aggregation

Supports both 1-minute and daily granularity backtests.
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.data_loader import DataLoader
from backend.indicators import INDICATOR_REGISTRY
from backend.strategy import (
    MarketContext, Order, Position, Trade, Side, Strategy,
    StrikeSelection, OptionType,
)

log = logging.getLogger(__name__)


def json_safe(obj):
    """
    Recursively replace non-finite floats (inf, -inf, NaN) with None.

    Starlette's JSONResponse serializes with json.dumps(allow_nan=False), so a
    single inf/NaN anywhere in the payload raises ValueError *after* the route
    handler has returned — i.e. outside its try/except, surfacing as an opaque
    unhandled 500. Metrics like profit_factor legitimately become inf (no losing
    trades) or NaN (no trades at all), so sanitize on the way out.
    """
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    underlying: str = "NIFTY"
    start_date: date = date(2024, 1, 1)
    end_date: date = date(2024, 3, 31)
    initial_capital: float = 1_000_000.0
    lot_size: int = 50  # NIFTY lot size
    granularity: str = "1min"  # "1min" or "1d"
    slippage_pct: float = 0.05  # 0.05% slippage per trade
    commission_per_lot: float = 20.0  # ₹20 per lot
    data_tracks: Optional[List[str]] = None  # None = all tracks

    # Trading hours (IST)
    market_open: time = time(9, 15)
    market_close: time = time(15, 30)

    # Risk management (daily). Hitting either limit stops trading for the day.
    max_loss_per_day: Optional[float] = None       # absolute ₹ loss limit
    max_loss_per_day_pct: Optional[float] = None   # loss as % of capital
    max_profit_per_day: Optional[float] = None     # absolute ₹ profit target
    max_profit_per_day_pct: Optional[float] = None  # profit as % of capital


# ──────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────

@dataclass
class DailyStats:
    """Statistics for a single trading day."""
    date: date
    pnl: float
    cumulative_pnl: float
    portfolio_value: float
    num_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown: float


@dataclass
class BacktestResult:
    """Complete backtest output."""
    # Summary
    strategy_name: str
    underlying: str
    start_date: date
    end_date: date
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
    avg_trade_duration: float  # in minutes
    max_consecutive_wins: int
    max_consecutive_losses: int

    # Detailed data
    trades: List[Trade] = field(default_factory=list)
    daily_stats: List[DailyStats] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)

    # Non-fatal diagnostics explaining a suspicious (e.g. zero-trade) run
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return json_safe({
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "avg_profit": round(self.avg_profit, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "avg_trade_duration": round(self.avg_trade_duration, 2),
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "trades": [
                {
                    "id": t.id,
                    "side": t.side.value if hasattr(t.side, 'value') else t.side,
                    "option_type": t.option_type,
                    "strike": t.strike,
                    "expiry": t.expiry,
                    "quantity": t.quantity,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "entry_time": str(t.entry_time),
                    "exit_time": str(t.exit_time),
                    "pnl": round(t.pnl, 2),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "tag": t.tag,
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ],
            "daily_stats": [
                {
                    "date": str(d.date),
                    "pnl": round(d.pnl, 2),
                    "cumulative_pnl": round(d.cumulative_pnl, 2),
                    "portfolio_value": round(d.portfolio_value, 2),
                    "num_trades": d.num_trades,
                }
                for d in self.daily_stats
            ],
            "equity_curve": [
                {"timestamp": str(t), "value": round(v, 2)}
                for t, v in self.equity_curve
            ],
            "warnings": list(self.warnings),
        })


# ──────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Event-driven options backtesting engine.

    For each timestamp:
      1. Reconstruct the options chain
      2. Mark-to-market all open positions
      3. Compute required indicators
      4. Build MarketContext
      5. Call strategy.on_candle()
      6. Process returned orders
      7. Record equity curve data point

    At day boundaries: call on_day_start / on_day_end,
    handle auto square-off, check daily loss limits.
    """

    def __init__(self, config: BacktestConfig, loader: Optional[DataLoader] = None):
        self.config = config
        self.loader = loader or DataLoader()
        self.current_iv = None
        self.positions: List[Position] = []
        self.completed_trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_stats: List[DailyStats] = []
        self.warnings: List[str] = []
        self._intraday_clock_available = True

        self.capital = config.initial_capital
        self.total_pnl = 0.0
        self.day_pnl = 0.0
        self.current_day: Optional[date] = None
        self.day_trade_count = 0
        self.day_hit_loss_limit = False
        self._day_stop_reason = "daily_loss_limit"
        self.peak_portfolio = config.initial_capital
        self.max_drawdown = 0.0

        # Progress tracking
        self.progress: float = 0.0
        self.status: str = "idle"

    def run(self, strategy: Strategy,
            progress_callback=None) -> BacktestResult:
        """
        Execute the backtest.

        Args:
            strategy: Strategy instance to test
            progress_callback: Optional callable(progress_pct, status_msg)

        Returns:
            BacktestResult with full statistics
        """
        self.status = "loading_data"
        if progress_callback:
            progress_callback(0, "Loading data...")

        # Load all data for the date range
        data = self.loader.load_data(
            self.config.underlying,
            self.config.start_date,
            self.config.end_date,
            granularity=self.config.granularity,
            tracks=self.config.data_tracks,
        )

        if data.empty:
            log.warning("No data available for the specified range")
            return self._build_empty_result(strategy)

        # Build the timestamp index before anything looks a candle up.
        data = self._index_by_timestamp(data)

        # Pre-compute indicators on spot price series
        self.status = "computing_indicators"
        if progress_callback:
            progress_callback(5, "Computing indicators...")

        spot_series = self._build_spot_series(data)
        indicator_values = self._precompute_indicators(strategy, spot_series, data)

        # Initialize strategy
        strategy.on_init({})

        # Get unique timestamps
        timestamps = sorted(data["timestamp"].unique())
        total_ts = len(timestamps)

        # Daily (bhavcopy) rows carry a date with no time-of-day, so every
        # candle parses to midnight. Any intraday time rule ("enter at 09:20")
        # is then unsatisfiable and the run silently produces zero trades —
        # record that up front so the result can explain itself.
        self._intraday_clock_available = any(
            pd.Timestamp(ts).time() != time(0, 0) for ts in timestamps
        )

        self.status = "running"
        log.info(f"Running backtest: {total_ts} timestamps, "
                 f"{self.config.start_date} to {self.config.end_date}")

        # Group timestamps by day
        ts_by_day: Dict[date, List] = {}
        for ts in timestamps:
            ts_dt = pd.Timestamp(ts)
            day = ts_dt.date()
            if day not in ts_by_day:
                ts_by_day[day] = []
            ts_by_day[day].append(ts)

        processed = 0
        for day in sorted(ts_by_day.keys()):
            day_timestamps = ts_by_day[day]

            # Day start
            self._handle_day_start(day, strategy, data, indicator_values,
                                   day_timestamps)

            for candle_idx, ts in enumerate(day_timestamps):
                ts_pd = pd.Timestamp(ts)

                # Build context
                chain = self._chain_at(ts_pd)
                spot = self.loader.estimate_spot_price(chain)
                if spot is None:
                    continue

                # Mark to market (reuse the spot we just computed)
                self._mark_to_market(chain, data, ts_pd, spot)

                # Per-leg risk exits (each leg's own SL / TP / trailing / move-to-cost)
                self._check_leg_exits(data, ts_pd)

                # Build indicator snapshot for this timestamp
                ind_snapshot = self._get_indicator_snapshot(
                    indicator_values, ts_pd
                )

                # Compute days to expiry
                dte = {}
                for exp in chain["expiry"].unique():
                    exp_date = pd.to_datetime(exp).date()
                    dte[exp] = max(0, (exp_date - day).days)

                ctx = MarketContext(
                    timestamp=ts_pd.to_pydatetime(),
                    underlying=self.config.underlying,
                    spot_price=spot,
                    options_chain=chain,
                    positions=list(self.positions),
                    portfolio_value=self.capital + self.total_pnl,
                    day_pnl=self.day_pnl,
                    total_pnl=self.total_pnl,
                    indicators=ind_snapshot,
                    trading_day=day,
                    candle_index=candle_idx,
                    total_candles=len(day_timestamps),
                    days_to_expiry=dte,
                )

                # Daily limit already hit today → flatten and skip (no new trades)
                if self.day_hit_loss_limit:
                    if self.positions:
                        self._square_off_all(data, ts_pd, self._day_stop_reason)
                    continue

                # Call strategy
                result = strategy.on_candle(ctx)

                # Process result. A strategy may return:
                #   "SQUARE_OFF_ALL"          -> close everything
                #   [Order, ...]              -> open these legs
                #   {"close_tags": [...],       -> close legs whose tag starts with
                #    "open": [Order, ...]}         a prefix, then open (parallel cases)
                if result == "SQUARE_OFF_ALL":
                    self._square_off_all(data, ts_pd, "strategy_exit")
                elif isinstance(result, dict):
                    for prefix in result.get("close_tags", []):
                        self._close_by_tag(data, ts_pd, prefix, "case_exit")
                    if result.get("open"):
                        self._process_orders(result["open"], data, ts_pd, chain, spot, ctx)
                elif isinstance(result, list) and result:
                    self._process_orders(result, data, ts_pd, chain, spot, ctx)

                # Record equity
                portfolio_val = self.capital + self.total_pnl
                self.equity_curve.append((ts_pd.to_pydatetime(), portfolio_val))

                # Track peak and drawdown
                if portfolio_val > self.peak_portfolio:
                    self.peak_portfolio = portfolio_val
                dd = self.peak_portfolio - portfolio_val
                if dd > self.max_drawdown:
                    self.max_drawdown = dd

                # Daily limits — hitting a loss cap OR a profit target ends the
                # trading day (positions are flattened on the next candle).
                day_pct = (self.day_pnl / self.capital) * 100 if self.capital else 0
                if self.config.max_loss_per_day and self.day_pnl <= -abs(self.config.max_loss_per_day):
                    self.day_hit_loss_limit = True; self._day_stop_reason = "daily_loss_limit"
                elif self.config.max_loss_per_day_pct and day_pct <= -abs(self.config.max_loss_per_day_pct):
                    self.day_hit_loss_limit = True; self._day_stop_reason = "daily_loss_limit"
                elif self.config.max_profit_per_day and self.day_pnl >= abs(self.config.max_profit_per_day):
                    self.day_hit_loss_limit = True; self._day_stop_reason = "daily_profit_target"
                elif self.config.max_profit_per_day_pct and day_pct >= abs(self.config.max_profit_per_day_pct):
                    self.day_hit_loss_limit = True; self._day_stop_reason = "daily_profit_target"
                if self.day_hit_loss_limit:
                    log.info(f"Daily limit hit ({self._day_stop_reason}): ₹{self.day_pnl:.0f}")

                processed += 1
                if progress_callback and processed % 100 == 0:
                    pct = (processed / total_ts) * 90 + 5  # 5% to 95%
                    progress_callback(pct, f"Processing {day} candle {candle_idx+1}/{len(day_timestamps)}")

            # Day end
            self._handle_day_end(day, strategy, data, indicator_values,
                                 day_timestamps)

        # Final square-off
        if self.positions:
            last_ts = pd.Timestamp(timestamps[-1])
            self._square_off_all(data, last_ts, "backtest_end")

        self.status = "completed"
        if progress_callback:
            progress_callback(100, "Backtest complete")

        return self._build_result(strategy)

    # ── Order execution ──────────────────────────────────────

    def _process_orders(self, orders: List[Order], data: pd.DataFrame,
                        timestamp: pd.Timestamp, chain: pd.DataFrame,
                        spot: float, ctx: MarketContext):
        """Execute a list of orders."""
        for order in orders:
            strike = self._resolve_strike(order, chain, spot)
            if strike is None:
                log.warning(f"Could not resolve strike for {order} at {timestamp}")
                continue

            expiry = self._resolve_expiry(order, chain, timestamp)
            if expiry is None:
                log.warning(f"Could not resolve expiry for {order} at {timestamp}")
                continue

            # Get entry price
            fill_price = self._price_at(
                timestamp, strike, order.option_type.value, expiry
            )
            if fill_price is None:
                log.warning(f"No price for {order.option_type.value} "
                            f"{strike} {expiry} at {timestamp}")
                continue

            # Apply slippage
            price = fill_price
            if order.side == Side.BUY:
                price *= (1 + self.config.slippage_pct / 100)
            else:
                price *= (1 - self.config.slippage_pct / 100)

            # Create position
            pos = Position(
                id=str(uuid.uuid4())[:8],
                side=order.side,
                option_type=order.option_type.value,
                strike=strike,
                expiry=expiry,
                quantity=order.quantity * self.loader.get_historical_lot_size(ctx.underlying, ctx.timestamp.date()),
                entry_price=fill_price,
                entry_time=timestamp.to_pydatetime(),
                tag=order.tag,
                current_price=price,
                stop_loss_pct=order.stop_loss_pct,
                take_profit_pct=order.take_profit_pct,
                trailing_sl_pct=order.trailing_sl_pct,
                move_to_cost_at_pct=order.move_to_cost_at_pct,
            )
            self.positions.append(pos)

            # Deduct commission
            commission = self.config.commission_per_lot * order.quantity
            self.total_pnl -= commission
            self.day_pnl -= commission

            log.debug(f"OPENED: {order.side.value} {pos.quantity}x "
                      f"{order.option_type.value} {strike} {expiry} "
                      f"@ ₹{price:.2f}")

    def _check_leg_exits(self, data: pd.DataFrame, timestamp: pd.Timestamp):
        """
        Close individual legs whose own risk controls have triggered.

        Each Position may carry its own stop-loss / take-profit / trailing-stop /
        move-to-cost (set from the leg it was opened with). This runs every candle
        after mark-to-market and closes just the legs that breached — unlike a
        strategy-level SQUARE_OFF_ALL, which closes everything at once.
        """
        for pos in list(self.positions):
            pnl = pos.pnl_pct()

            # Move-to-cost: once profit crosses the trigger, lock the stop at
            # breakeven so the leg can't turn into a loss.
            if (pos.move_to_cost_at_pct and not pos.breakeven_locked
                    and pnl >= pos.move_to_cost_at_pct):
                pos.breakeven_locked = True

            reason = None
            if pos.take_profit_pct is not None and pnl >= pos.take_profit_pct:
                reason = "leg_take_profit"
            elif pos.breakeven_locked and pnl <= 0:
                reason = "leg_move_to_cost"
            elif (pos.trailing_sl_pct is not None
                  and pos.peak_pnl_pct - pnl >= pos.trailing_sl_pct):
                reason = "leg_trailing_sl"
            elif pos.stop_loss_pct is not None and pnl <= -abs(pos.stop_loss_pct):
                reason = "leg_stop_loss"

            if reason:
                self._close_position(pos, data, timestamp, reason)
                self.positions.remove(pos)

    def _close_by_tag(self, data: pd.DataFrame, timestamp: pd.Timestamp,
                      prefix: str, reason: str = ""):
        """Close positions whose tag starts with `prefix` (one parallel case)."""
        for pos in list(self.positions):
            if pos.tag and pos.tag.startswith(prefix):
                self._close_position(pos, data, timestamp, reason)
                self.positions.remove(pos)

    def _square_off_all(self, data: pd.DataFrame, timestamp: pd.Timestamp,
                        reason: str = ""):
        """Close all open positions."""
        for pos in list(self.positions):
            self._close_position(pos, data, timestamp, reason)
        self.positions.clear()

    def _close_position(self, pos: Position, data: pd.DataFrame,
                        timestamp: pd.Timestamp, reason: str = ""):
        """Close a specific position."""
        exit_price = self._price_at(
            timestamp, pos.strike, pos.option_type, pos.expiry
        )
        if exit_price is None:
            # Use last known price
            exit_price = pos.current_price
            log.warning(f"No exit price for {pos.option_type} {pos.strike} "
                        f"at {timestamp}, using last known: {exit_price:.2f}")

        # Apply slippage (reverse direction)
        if pos.side == Side.BUY:
            exit_price *= (1 - self.config.slippage_pct / 100)
        else:
            exit_price *= (1 + self.config.slippage_pct / 100)

        # Calculate P&L
        if pos.side == Side.BUY:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pnl_pct = (pnl / (pos.entry_price * pos.quantity)) * 100 if pos.entry_price > 0 else 0

        # Commission on exit
        current_lot_size = DataLoader.get_historical_lot_size(self.config.underlying, timestamp.date())
        lots = pos.quantity / current_lot_size
        commission = self.config.commission_per_lot * lots
        pnl -= commission

        self.total_pnl += pnl
        self.day_pnl += pnl
        self.day_trade_count += 1

        trade = Trade(
            id=pos.id,
            side=pos.side,
            option_type=pos.option_type,
            strike=pos.strike,
            expiry=pos.expiry,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=timestamp.to_pydatetime(),
            pnl=pnl,
            pnl_pct=pnl_pct,
            tag=pos.tag,
            exit_reason=reason,
        )
        self.completed_trades.append(trade)

        log.debug(f"CLOSED: {pos.side} {pos.quantity}x {pos.option_type} "
                  f"{pos.strike} @ ₹{exit_price:.2f} | P&L: ₹{pnl:.2f} "
                  f"({reason})")

    # ── Resolution helpers ───────────────────────────────────

    def _resolve_strike(self, order: Order, chain: pd.DataFrame,
                        spot: float) -> Optional[float]:
        """Resolve strike selection to actual strike."""
        # If custom fixed strike
        if order.strike_selection == StrikeSelection.FIXED and order.fixed_strike is not None:
            return order.fixed_strike

        sel = order.strike_selection.value
        offset = 0
        if sel in ("ATM+N", "ATM-N"):
            # Arbitrary width carried on the order (see Order.strike_offset).
            n = abs(int(order.strike_offset or 0))
            offset = n if sel == "ATM+N" else -n
        elif "+" in sel:
            offset = int(sel.split("+")[1])
        elif "-" in sel:
            offset = -int(sel.split("-")[1])

        return self.loader.select_strike(
            chain, spot, order.option_type.value, "ATM", offset
        )

    def _resolve_expiry(self, order: Order, chain: pd.DataFrame,
                        timestamp: pd.Timestamp) -> Optional[str]:
        """Resolve expiry selection."""
        trading_day = timestamp.date()
        if order.expiry_selection == "nearest":
            return self.loader.get_nearest_expiry(chain, trading_day)
        elif order.expiry_selection == "next":
            expiries = self.loader.get_expiries(chain, trading_day)
            if len(expiries) >= 2:
                return expiries[1]
            return expiries[0] if expiries else None
        else:
            # Assume it's a specific date string
            return order.expiry_selection

    # ── Indicator computation ────────────────────────────────

    def _build_spot_series(self, data: pd.DataFrame) -> pd.DataFrame:
        """Build a time-series of approximate spot prices."""
        # Group by timestamp, estimate spot from ATM options
        timestamps = sorted(data["timestamp"].unique())
        spots = []
        for ts in timestamps:
            chain = self._chain_at(pd.Timestamp(ts))
            spot = self.loader.estimate_spot_price(chain)
            if spot is not None:
                spots.append({"timestamp": ts, "close": spot})

        if not spots:
            return pd.DataFrame()

        df = pd.DataFrame(spots)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        # Add OHLC approximation (for indicators that need it)
        df["open"] = df["close"]
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0
        return df

    def _precompute_indicators(self, strategy: Strategy,
                                spot_df: pd.DataFrame,
                                data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Pre-compute all indicators needed by the strategy."""
        required = strategy.required_indicators()
        results = {}

        if spot_df.empty or not required:
            return results

        for ind_config in required:
            name = ind_config["name"]
            params = ind_config.get("params", {})
            input_field = ind_config.get("input", "close")
            output_key = ind_config.get("output_key")

            registry_entry = INDICATOR_REGISTRY.get(name)
            if registry_entry is None:
                log.warning(f"Unknown indicator: {name}")
                continue

            func = registry_entry["func"]
            inputs = registry_entry.get("inputs", ["close"])

            try:
                # Build input args
                args = []
                for inp in inputs:
                    if inp in spot_df.columns:
                        args.append(spot_df[inp])
                    else:
                        args.append(spot_df["close"])  # fallback

                result = func(*args, **params)

                # Store results
                param_str = "_".join(f"{k}{v}" for k, v in sorted(params.items()))
                base_key = f"{name}_{param_str}"

                if isinstance(result, tuple):
                    output_names = registry_entry.get("outputs", [])
                    for i, series in enumerate(result):
                        out_name = output_names[i] if i < len(output_names) else str(i)
                        results[f"{base_key}_{out_name}"] = series
                else:
                    results[base_key] = result
            except Exception as e:
                log.warning(f"Failed to compute indicator {name}: {e}")

        return results

    def _get_indicator_snapshot(self, indicator_values: Dict[str, pd.Series],
                                 timestamp: pd.Timestamp) -> Dict[str, Any]:
        """Get indicator values at a specific timestamp."""
        snapshot = {}
        for key, series in indicator_values.items():
            if timestamp in series.index:
                snapshot[key] = float(series[timestamp])
                # Also store previous value for crossover detection
                idx = series.index.get_loc(timestamp)
                if idx > 0:
                    snapshot[f"{key}_prev"] = float(series.iloc[idx - 1])
        return snapshot

    # ── Day boundary handling ────────────────────────────────

    def _handle_day_start(self, day: date, strategy: Strategy,
                          data: pd.DataFrame,
                          indicator_values: Dict,
                          day_timestamps: List):
        """Handle start of a new trading day."""
        self.current_day = day
        self.day_pnl = 0.0
        self.day_trade_count = 0
        self.day_hit_loss_limit = False
        self._day_stop_reason = "daily_loss_limit"

        # Build a minimal context for on_day_start
        first_ts = pd.Timestamp(day_timestamps[0])
        chain = self._chain_at(first_ts)
        spot = self.loader.estimate_spot_price(chain)

        if spot is not None:
            ctx = MarketContext(
                timestamp=first_ts.to_pydatetime(),
                underlying=self.config.underlying,
                spot_price=spot,
                options_chain=chain,
                positions=list(self.positions),
                portfolio_value=self.capital + self.total_pnl,
                day_pnl=0.0,
                total_pnl=self.total_pnl,
                indicators={},
                trading_day=day,
                candle_index=0,
                total_candles=len(day_timestamps),
                days_to_expiry={},
            )
            setattr(ctx, "current_iv", self.current_iv)
            strategy.on_day_start(ctx)

    def _handle_day_end(self, day: date, strategy: Strategy,
                        data: pd.DataFrame,
                        indicator_values: Dict,
                        day_timestamps: List):
        """Handle end of a trading day."""
        # Record daily stats
        winning = sum(1 for t in self.completed_trades
                      if t.exit_time.date() == day and t.pnl > 0)
        losing = sum(1 for t in self.completed_trades
                     if t.exit_time.date() == day and t.pnl <= 0)

        portfolio_val = self.capital + self.total_pnl
        dd_pct = ((self.peak_portfolio - portfolio_val) / self.peak_portfolio * 100
                  if self.peak_portfolio > 0 else 0)

        self.daily_stats.append(DailyStats(
            date=day,
            pnl=self.day_pnl,
            cumulative_pnl=self.total_pnl,
            portfolio_value=portfolio_val,
            num_trades=self.day_trade_count,
            winning_trades=winning,
            losing_trades=losing,
            max_drawdown=dd_pct,
        ))

    # ── Mark to market ───────────────────────────────────────

    # ── Timestamp lookup ─────────────────────────────────────

    def _index_by_timestamp(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare `data` for O(log n) per-candle lookups.

        get_options_chain / get_option_price boolean-scan the whole frame on
        every call, which is O(rows) per candle. That is survivable at ~900k
        rows but becomes pathological once the Upstox backfill grows a single
        year file to tens of millions. Sorting once lets us binary-search the
        slice boundaries instead, using views rather than a second copy of the
        dataset.
        """
        if not data["timestamp"].is_monotonic_increasing:
            # mergesort keeps ties in their original order, matching the
            # stable sort load_data() already applied.
            data = data.sort_values("timestamp", kind="mergesort")
        self._ts_sorted = data
        self._ts_series = data["timestamp"]
        return data

    def _slice_at(self, timestamp: pd.Timestamp) -> pd.DataFrame:
        """All rows for one timestamp, as a view."""
        ts = pd.Timestamp(timestamp)
        lo = self._ts_series.searchsorted(ts, side="left")
        hi = self._ts_series.searchsorted(ts, side="right")
        return self._ts_sorted.iloc[lo:hi]

    def _chain_at(self, timestamp: pd.Timestamp) -> pd.DataFrame:
        """Options chain at a timestamp, ordered as get_options_chain returns it."""
        rows = self._slice_at(timestamp)
        if rows.empty:
            return rows
        return rows.sort_values(["expiry", "strike", "option_type"])

    def _price_at(self, timestamp: pd.Timestamp, strike: float,
                  option_type: str, expiry: str,
                  price_field: str = "close") -> Optional[float]:
        """Price of one contract at one timestamp."""
        rows = self._slice_at(timestamp)
        if rows.empty:
            return None
        match = rows[
            (rows["strike"] == strike)
            & (rows["option_type"] == option_type)
            & (rows["expiry"] == expiry)
        ]
        if match.empty:
            return None
        return float(match.iloc[0][price_field])

    def _mark_to_market(self, chain: pd.DataFrame, data: pd.DataFrame,
                        timestamp: pd.Timestamp,
                        spot: Optional[float] = None):
        """
        Update current prices (and Greeks) for all open positions.

        Only a handful of rows from the chain are ever read here: the first ATM
        row, which proxies `current_iv`, and the row backing each open position.
        Enriching the whole ~200-row chain on every candle meant roughly 450k
        iterative IV solves per backtest-week and dominated the runtime, so
        enrich just the rows that are actually consumed.

        `spot` is accepted from the caller, which has already computed it — the
        put-call-parity estimate used to be recomputed here for every candle.
        """
        enriched_rows = None
        if chain is not None and not chain.empty:
            if spot is None:
                spot = self.loader.estimate_spot_price(chain)

            if spot is not None and spot > 0:
                # Same ATM rule enrich_chain_with_greeks applies, evaluated up
                # front so we can select rows before paying for enrichment.
                atm_mask = (chain["strike"] - spot).abs() < spot * 0.005

                wanted = []
                atm_idx = chain.index[atm_mask]
                if len(atm_idx):
                    wanted.append(atm_idx[0])  # matches the old .iloc[0] pick
                for pos in self.positions:
                    match = chain.index[
                        (chain["strike"] == pos.strike)
                        & (chain["option_type"] == pos.option_type)
                        & (chain["expiry"] == pos.expiry)
                    ]
                    if len(match):
                        wanted.append(match[0])

                if wanted:
                    subset = chain.loc[sorted(set(wanted))]
                    enriched_rows = self.loader.enrich_chain_with_greeks(
                        subset, spot, 0.065)
                    if len(atm_idx) and atm_idx[0] in enriched_rows.index:
                        self.current_iv = enriched_rows.loc[atm_idx[0], "iv"]

        for pos in self.positions:
            price = self._price_at(
                timestamp, pos.strike, pos.option_type, pos.expiry
            )
            if price is not None:
                pos.mark_to_market(price)

                if enriched_rows is not None and not enriched_rows.empty:
                    match = enriched_rows[
                        (enriched_rows["strike"] == pos.strike)
                        & (enriched_rows["option_type"] == pos.option_type)
                        & (enriched_rows["expiry"] == pos.expiry)
                    ]
                    if not match.empty:
                        r = match.iloc[0]
                        pos.delta = r.get("delta", 0.0)
                        pos.gamma = r.get("gamma", 0.0)
                        pos.theta = r.get("theta", 0.0)
                        pos.vega = r.get("vega", 0.0)
                        pos.rho = r.get("rho", 0.0)


    # ── Result building ──────────────────────────────────────

    def _build_result(self, strategy: Strategy) -> BacktestResult:
        """Compile all statistics into a BacktestResult."""
        trades = self.completed_trades
        total = len(trades)

        if total == 0 and not self._intraday_clock_available:
            self.warnings.append(
                f"0 trades: '{self.config.underlying}' data at granularity "
                f"'{self.config.granularity}' has no intraday timestamps (every "
                f"candle is dated midnight), so time-of-day entry/exit rules can "
                f"never trigger. Use granularity='1min' intraday data for "
                f"time-based strategies, or a strategy without time conditions."
            )
        elif total == 0:
            self.warnings.append(
                "0 trades: the strategy's entry conditions never evaluated true "
                "over the selected date range."
            )
        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]

        win_rate = (len(winners) / total * 100) if total > 0 else 0
        avg_profit = (np.mean([t.pnl for t in winners])
                      if winners else 0)
        avg_loss = (np.mean([t.pnl for t in losers])
                    if losers else 0)

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        # Sharpe & Sortino from daily returns
        daily_returns = [d.pnl / self.config.initial_capital for d in self.daily_stats]
        sharpe = sortino = calmar = 0.0
        if daily_returns and len(daily_returns) > 1:
            avg_return = np.mean(daily_returns)
            std_return = np.std(daily_returns)
            if std_return > 0:
                sharpe = avg_return / std_return * np.sqrt(252)

            downside = [r for r in daily_returns if r < 0]
            downside_std = np.std(downside) if downside else 0
            if downside_std > 0:
                sortino = avg_return / downside_std * np.sqrt(252)

        max_dd_pct = (self.max_drawdown / self.peak_portfolio * 100
                      if self.peak_portfolio > 0 else 0)
        annual_return = self.total_pnl / self.config.initial_capital * 100
        if max_dd_pct > 0:
            calmar = annual_return / max_dd_pct

        # Consecutive wins/losses
        max_consec_wins, max_consec_losses = self._max_consecutive(trades)

        # Average trade duration
        durations = [(t.exit_time - t.entry_time).total_seconds() / 60
                     for t in trades]
        avg_duration = np.mean(durations) if durations else 0

        final_capital = self.capital + self.total_pnl

        return BacktestResult(
            strategy_name=strategy.name,
            underlying=self.config.underlying,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=self.config.initial_capital,
            final_capital=final_capital,
            total_pnl=self.total_pnl,
            total_pnl_pct=(self.total_pnl / self.config.initial_capital) * 100,
            total_trades=total,
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=self.max_drawdown,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            avg_trade_duration=avg_duration,
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            trades=trades,
            daily_stats=self.daily_stats,
            equity_curve=self.equity_curve,
            warnings=self.warnings,
        )

    def _build_empty_result(self, strategy: Strategy) -> BacktestResult:
        """Return an empty result when no data is available."""
        return BacktestResult(
            strategy_name=strategy.name,
            underlying=self.config.underlying,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=self.config.initial_capital,
            final_capital=self.config.initial_capital,
            total_pnl=0, total_pnl_pct=0, total_trades=0,
            winning_trades=0, losing_trades=0, win_rate=0,
            avg_profit=0, avg_loss=0, profit_factor=0,
            max_drawdown=0, max_drawdown_pct=0,
            sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
            avg_trade_duration=0,
            max_consecutive_wins=0, max_consecutive_losses=0,
            warnings=[
                f"No data found for {self.config.underlying} between "
                f"{self.config.start_date} and {self.config.end_date} at "
                f"granularity '{self.config.granularity}'."
            ],
        )

    @staticmethod
    def _max_consecutive(trades: List[Trade]) -> Tuple[int, int]:
        """Calculate max consecutive wins and losses."""
        max_wins = max_losses = 0
        curr_wins = curr_losses = 0
        for t in trades:
            if t.pnl > 0:
                curr_wins += 1
                curr_losses = 0
                max_wins = max(max_wins, curr_wins)
            else:
                curr_losses += 1
                curr_wins = 0
                max_losses = max(max_losses, curr_losses)
        return max_wins, max_losses
