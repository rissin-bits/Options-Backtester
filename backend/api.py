"""
api.py — FastAPI application for the options backtester.

Endpoints:
  POST /api/backtest          — Run a backtest from strategy config
  GET  /api/strategies        — List available/saved strategies
  POST /api/strategies        — Save a strategy config
  GET  /api/data/underlyings  — Available underlyings and date ranges
  GET  /api/data/options-chain — Historical options chain
  GET  /api/indicators        — Available indicators for GUI
  GET  /api/status            — Server health check
  WS   /ws/backtest           — WebSocket for live backtest progress
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import traceback
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.data_loader import DataLoader
from backend.engine import BacktestConfig, BacktestEngine
from backend.indicators import INDICATOR_REGISTRY
from backend.models import (
    BacktestRequest, BacktestResultModel, IndicatorInfo,
    OptionsChainRequest, OptionsChainRow, StatusResponse,
    StrategyConfigModel, UnderlyingInfo, ExpiryInfo, TradingDateInfo,
)
from backend.strategy import (
    RuleBasedStrategy, Rule, Condition, Order, Side, OptionType,
    StrikeSelection, OrderType, AndCondition, OrCondition,
)
from backend.example_strategies import EXAMPLE_STRATEGIES
from backend.strategy_templates import TEMPLATES, list_templates, build_strategy
from backend import builder_store
from backend.monte_carlo import run_monte_carlo
from backend.stress_test import run_stress_tests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Options Backtester API",
    description="Wall Street Club × BITS Pilani Options Backtesting Engine",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data loader (shared instance)
DATA_DIR = Path("./options_data/parsed").resolve()
loader = DataLoader(str(DATA_DIR))

# In-memory storage for saved strategies and running backtests
saved_strategies: Dict[str, dict] = {}
running_backtests: Dict[str, dict] = {}


# ──────────────────────────────────────────────────────────────
# Health & Info
# ──────────────────────────────────────────────────────────────

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    underlyings = loader.available_underlyings()
    return StatusResponse(
        status="healthy",
        version="1.0.0",
        data_available=len(underlyings) > 0,
        underlyings=underlyings,
    )


@app.get("/api/indicators")
async def get_indicators():
    """List all available technical indicators."""
    result = []
    for name, info in INDICATOR_REGISTRY.items():
        result.append(IndicatorInfo(
            name=name,
            description=info.get("description", ""),
            params=info.get("params", {}),
            inputs=info.get("inputs", []),
            outputs=info.get("outputs"),
        ))
    return result


@app.get("/api/data/summary")
async def get_data_summary():
    """Get high-level summary of available data for dashboard."""
    underlyings = loader.available_underlyings()
    total_days = 0
    date_ranges = {}
    for u in underlyings:
        dates = loader.get_available_trading_dates(u)
        total_days += len(dates)
        min_d, max_d = loader.available_date_range(u)
        if min_d and max_d:
            date_ranges[u] = f"{min_d} to {max_d}"
            
    return {
        "underlyings_count": len(underlyings),
        "total_trading_days": total_days,
        "date_ranges": date_ranges,
        "underlyings_list": underlyings
    }


# ──────────────────────────────────────────────────────────────
# Data exploration
# ──────────────────────────────────────────────────────────────

@app.get("/api/data/underlyings")
async def get_underlyings():
    """List available underlyings with metadata."""
    underlyings = loader.available_underlyings()
    result = []
    for u in underlyings:
        min_d, max_d = loader.available_date_range(u)
        result.append(UnderlyingInfo(
            name=u,
            min_date=str(min_d) if min_d else None,
            max_date=str(max_d) if max_d else None,
        ))
    return result


@app.post("/api/data/options-chain")
async def get_options_chain(request: OptionsChainRequest):
    """Get historical options chain for a specific date/time, enriched with Greeks and IV."""
    target_date = date.fromisoformat(request.date)

    # Load only the requested day. Loading the whole underlying pulled ~124M
    # rows for NIFTY after the intraday backfill and exhausted memory.
    data = loader.load_data(request.underlying, target_date, target_date)
    if data.empty:
        raise HTTPException(404, f"No data for {request.underlying}")

    if request.time:
        target_ts = datetime.fromisoformat(f"{request.date}T{request.time}")
        chain = loader.get_options_chain(data, target_ts, request.expiry)
    else:
        # Find first timestamp on that date
        timestamps = loader.get_timestamps(data, target_date)
        if not timestamps:
            raise HTTPException(404, f"No data for {request.date}")
        chain = loader.get_options_chain(data, timestamps[0], request.expiry)

    # Estimate spot price and enrich with Greeks/IV
    spot = loader.estimate_spot_price(chain)
    if spot is not None:
        chain = loader.enrich_chain_with_greeks(chain, spot)

    def _safe_float(val, default=0.0):
        if val is None: return default
        try:
            f = float(val)
            return default if math.isnan(f) else f
        except:
            return default

    def _safe_int(val, default=0):
        if val is None: return default
        try:
            f = float(val)
            return default if math.isnan(f) else int(f)
        except:
            return default

    def _safe_opt_float(val, precision=None):
        if val is None: return None
        try:
            f = float(val)
            if math.isnan(f): return None
            return round(f, precision) if precision is not None else f
        except:
            return None

    rows = []
    for _, row in chain.iterrows():
        rows.append(OptionsChainRow(
            strike=_safe_float(row["strike"]),
            option_type=str(row["option_type"]),
            expiry=str(row["expiry"]),
            open=_safe_float(row.get("open")),
            high=_safe_float(row.get("high")),
            low=_safe_float(row.get("low")),
            close=_safe_float(row.get("close")),
            volume=_safe_int(row.get("volume")),
            oi=_safe_opt_float(row.get("oi")),
            iv=_safe_opt_float(row.get("iv", None) * 100 if row.get("iv") is not None and not math.isnan(float(row.get("iv"))) else None, 2),
            delta=_safe_opt_float(row.get("delta"), 4),
            gamma=_safe_opt_float(row.get("gamma"), 6),
            theta=_safe_opt_float(row.get("theta"), 4),
            vega=_safe_opt_float(row.get("vega"), 4),
            rho=_safe_opt_float(row.get("rho"), 4),
            moneyness=str(row.get("moneyness", "")) if "moneyness" in row else None,
        ))
    return {"chain": rows, "spot_price": spot}


@app.get("/api/data/expiries")
async def get_expiries(underlying: str, date: str):
    """Get valid expiries for a given trading date — prevents arbitrary expiry selection."""
    expiries = loader.get_valid_expiries(underlying, date)
    if not expiries:
        return []
    ref = __import__('datetime').date.fromisoformat(date)
    result = []
    for exp in expiries:
        try:
            exp_date = __import__('datetime').date.fromisoformat(str(exp)[:10])
            dte = max(0, (exp_date - ref).days)
        except Exception:
            dte = None
        result.append(ExpiryInfo(expiry=str(exp), dte=dte))
    return result


@app.get("/api/data/trading-dates")
async def get_trading_dates(underlying: str):
    """Get all available trading dates for an underlying."""
    dates = loader.get_available_trading_dates(underlying)
    return [TradingDateInfo(date=d) for d in dates]


@app.get("/api/data/timestamps")
async def get_timestamps_for_date(underlying: str, date: str):
    """Get available timestamps for a given trading date."""
    timestamps = loader.get_available_timestamps_for_date(underlying, date)
    return timestamps


@app.get("/api/data/lot-size")
async def get_lot_size(underlying: str, date: str):
    """Get the correct historical lot size for a given date."""
    from backend.data_loader import DataLoader
    d = __import__('datetime').date.fromisoformat(date)
    lot_size = DataLoader.get_historical_lot_size(underlying, d)
    return {"underlying": underlying, "date": date, "lot_size": lot_size}


# ──────────────────────────────────────────────────────────────
# Strategy management
# ──────────────────────────────────────────────────────────────

@app.get("/api/strategies")
async def list_strategies():
    """List saved strategies."""
    return list(saved_strategies.values())


@app.get("/api/strategies/templates")
async def get_strategy_templates():
    """
    List every ready-made strategy together with its adjustable parameter
    schema and a preview of the legs it will trade at the default settings.
    The Backtest tab renders these as editable forms.
    """
    return list_templates()


class SavedStrategyRequest(BaseModel):
    """Save a built strategy. `payload` is the opaque Builder state."""
    name: str = "Untitled"
    payload: Dict[str, Any] = {}
    id: Optional[str] = None


@app.get("/api/builder/strategies")
async def builder_list_strategies():
    """List saved builder strategies (My Strategies)."""
    return builder_store.list_strategies()


@app.get("/api/builder/strategies/{sid}")
async def builder_get_strategy(sid: str):
    rec = builder_store.get_strategy(sid)
    if not rec:
        raise HTTPException(404, "Strategy not found")
    return rec


@app.post("/api/builder/strategies")
async def builder_save_strategy(req: SavedStrategyRequest):
    return builder_store.save_strategy(req.name, req.payload, req.id)


@app.delete("/api/builder/strategies/{sid}")
async def builder_delete_strategy(sid: str):
    return {"deleted": builder_store.delete_strategy(sid)}


@app.post("/api/strategies/templates/{template_id}/preview")
async def preview_strategy_template(template_id: str, params: Optional[Dict[str, Any]] = None):
    """
    Re-derive a template's legs, exit rules and resolved params for a given set
    of adjustments, so the Backtest tab can show a live preview as the user edits.
    """
    if template_id not in TEMPLATES:
        raise HTTPException(404, f"Unknown strategy template: {template_id}")
    template = TEMPLATES[template_id]
    resolved = template.resolve(params or {})
    return {
        "id": template_id,
        "resolved_params": resolved,
        **{k: v for k, v in template.to_dict(params or {}).items()
           if k in ("preview_legs",)},
    }


@app.get("/api/strategies/examples")
async def get_example_strategies():
    """List built-in example strategies."""
    result = []
    for key, strategy in EXAMPLE_STRATEGIES.items():
        if isinstance(strategy, RuleBasedStrategy):
            result.append({
                "id": key,
                "name": strategy.name,
                "description": strategy.description,
                "type": "rule_based"
            })
        else:
            result.append({
                "id": key,
                "name": strategy.name,
                "description": strategy.description,
                "type": "custom"
            })
    return result


@app.post("/api/strategies")
async def save_strategy(config: StrategyConfigModel):
    """Save a strategy configuration."""
    strategy_id = str(uuid.uuid4())[:8]
    entry = {
        "id": strategy_id,
        "config": config.model_dump(),
        "created_at": datetime.now().isoformat(),
    }
    saved_strategies[strategy_id] = entry
    return entry


@app.get("/api/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    if strategy_id not in saved_strategies:
        raise HTTPException(404, "Strategy not found")
    return saved_strategies[strategy_id]


@app.delete("/api/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str):
    if strategy_id in saved_strategies:
        del saved_strategies[strategy_id]
    return {"deleted": True}


# ──────────────────────────────────────────────────────────────
# Backtesting
# ──────────────────────────────────────────────────────────────

def _build_strategy_from_config(config: StrategyConfigModel) -> RuleBasedStrategy:
    """Convert API model to engine Strategy object."""
    entry_rules = []
    for rule_model in config.entry_rules:
        condition = Condition.from_dict(rule_model.condition.model_dump())
        orders = []
        for o in rule_model.orders:
            orders.append(Order(
                side=Side(o.side.value),
                option_type=OptionType(o.option_type.value),
                strike_selection=StrikeSelection(o.strike_selection.value),
                fixed_strike=o.fixed_strike,
                quantity=o.quantity,
                expiry_selection=o.expiry_selection,
                tag=o.tag,
            ))
        entry_rules.append(Rule(
            name=rule_model.name,
            condition=condition,
            orders=orders,
            is_entry=True,
            max_triggers_per_day=rule_model.max_triggers_per_day,
        ))

    exit_rules = []
    for rule_model in config.exit_rules:
        condition = Condition.from_dict(rule_model.condition.model_dump())
        exit_rules.append(Rule(
            name=rule_model.name,
            condition=condition,
            orders=[],
            is_entry=False,
            max_triggers_per_day=rule_model.max_triggers_per_day,
        ))

    return RuleBasedStrategy(
        name=config.name,
        description=config.description,
        entry_rules=entry_rules,
        exit_rules=exit_rules,
        square_off_time=config.square_off_time,
        max_positions=config.max_positions,
    )


def _order_from_leg(leg) -> Order:
    """Turn a builder LegModel into an engine Order (with per-leg risk)."""
    opt = OptionType(leg.option_type.value)
    n = int(leg.strike_offset or 0)
    if leg.moneyness == "ATM" or n == 0:
        sel, off = StrikeSelection.ATM, None
    else:
        # OTM call = higher strike, OTM put = lower; ITM is the mirror.
        higher = (opt == OptionType.CE) == (leg.moneyness == "OTM")
        sel = StrikeSelection.ATM_PLUS_N if higher else StrikeSelection.ATM_MINUS_N
        off = n
    return Order(
        side=Side(leg.side.value),
        option_type=opt,
        strike_selection=sel,
        strike_offset=off,
        quantity=leg.lots,
        expiry_selection=leg.expiry_selection,
        tag=leg.tag,
        stop_loss_pct=leg.stop_loss_pct,
        take_profit_pct=leg.take_profit_pct,
        trailing_sl_pct=leg.trailing_sl_pct,
        move_to_cost_at_pct=leg.move_to_cost_at_pct,
    )


def _build_custom_strategy(cfg):
    from backend.custom_strategy import CustomLegStrategy

    # Entry-When: every condition must hold (AND). Exit-When: any triggers (OR).
    entry_cond = (AndCondition([Condition.from_dict(c.model_dump())
                                for c in cfg.entry_conditions])
                  if cfg.entry_conditions else None)
    exit_cond = (OrCondition([Condition.from_dict(c.model_dump())
                              for c in cfg.exit_conditions])
                 if cfg.exit_conditions else None)

    return CustomLegStrategy(
        name=cfg.name,
        legs=[_order_from_leg(leg) for leg in cfg.legs],
        entry_time=cfg.entry_time,
        square_off_time=cfg.square_off_time,
        max_entries_per_day=cfg.max_entries_per_day,
        re_entry=cfg.re_entry,
        entry_condition=entry_cond,
        exit_condition=exit_cond,
        overall_stop_loss=cfg.overall_stop_loss,
        overall_take_profit=cfg.overall_take_profit,
    )


def _resolve_strategy(request: BacktestRequest):
    """
    Resolve a backtest request to a Strategy.

    BacktestRequest has always declared `strategy_id` alongside the inline
    `strategy` config, but only the inline path was implemented — passing an id
    (as the run-an-example-strategy UI does) hit
    _build_strategy_from_config(None) and raised AttributeError.

    Example strategies are module-level singletons that accumulate per-run state,
    so hand back a deep copy rather than the shared instance.
    """
    if request.custom_strategy is not None and request.custom_strategy.legs:
        return _build_custom_strategy(request.custom_strategy)

    if request.strategy_id:
        # Ready-made strategies are built from templates so the user's
        # adjustments (request.params) actually take effect.
        if request.strategy_id in TEMPLATES:
            return build_strategy(request.strategy_id, request.params)
        if request.strategy_id in EXAMPLE_STRATEGIES:
            return copy.deepcopy(EXAMPLE_STRATEGIES[request.strategy_id])
        if request.strategy_id in saved_strategies:
            saved = saved_strategies[request.strategy_id]["config"]
            return _build_strategy_from_config(StrategyConfigModel(**saved))
        raise HTTPException(404, f"Unknown strategy_id: {request.strategy_id}")

    if request.strategy is not None:
        return _build_strategy_from_config(request.strategy)

    raise HTTPException(422, "Provide either 'strategy' or 'strategy_id'")


@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest):
    """
    Run a backtest synchronously and return results.
    For large backtests, use the WebSocket endpoint instead.
    """
    try:
        strategy = _resolve_strategy(request)

        config = BacktestConfig(
            underlying=request.underlying,
            start_date=date.fromisoformat(request.start_date),
            end_date=date.fromisoformat(request.end_date),
            initial_capital=request.initial_capital,
            lot_size=request.lot_size,
            granularity=request.granularity,
            slippage_pct=request.slippage_pct,
            commission_per_lot=request.commission_per_lot,
            max_loss_per_day=request.max_loss_per_day,
            max_loss_per_day_pct=request.max_loss_per_day_pct,
            max_profit_per_day=request.max_profit_per_day,
            max_profit_per_day_pct=request.max_profit_per_day_pct,
        )

        engine = BacktestEngine(config, loader)
        result = engine.run(strategy)
        return result.to_dict()

    except HTTPException:
        # Deliberate 404/422 from _resolve_strategy — don't relabel it a 500.
        raise
    except Exception as e:
        log.error(f"Backtest failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Backtest failed: {str(e)}")


# ──────────────────────────────────────────────────────────────
# WebSocket — live backtest progress
# ──────────────────────────────────────────────────────────────

@app.websocket("/ws/backtest")
async def ws_backtest(websocket: WebSocket):
    """
    WebSocket endpoint for running backtests with live progress updates.

    Client sends a BacktestRequest JSON, server streams progress and
    final results back.
    """
    await websocket.accept()
    try:
        # Receive backtest request
        raw = await websocket.receive_text()
        request_data = json.loads(raw)
        request = BacktestRequest(**request_data)

        strategy = _resolve_strategy(request)
        config = BacktestConfig(
            underlying=request.underlying,
            start_date=date.fromisoformat(request.start_date),
            end_date=date.fromisoformat(request.end_date),
            initial_capital=request.initial_capital,
            lot_size=request.lot_size,
            granularity=request.granularity,
            slippage_pct=request.slippage_pct,
            commission_per_lot=request.commission_per_lot,
            max_loss_per_day=request.max_loss_per_day,
            max_loss_per_day_pct=request.max_loss_per_day_pct,
            max_profit_per_day=request.max_profit_per_day,
            max_profit_per_day_pct=request.max_profit_per_day_pct,
        )

        engine = BacktestEngine(config, loader)

        # Progress callback sends updates over WebSocket
        async def progress_callback(pct, msg):
            try:
                await websocket.send_json({
                    "type": "progress",
                    "progress": round(pct, 1),
                    "message": msg,
                })
            except Exception:
                pass

        # Run in thread pool to not block the event loop
        loop = asyncio.get_event_loop()

        def sync_progress(pct, msg):
            asyncio.run_coroutine_threadsafe(
                progress_callback(pct, msg), loop
            )

        result = await loop.run_in_executor(
            None, lambda: engine.run(strategy, sync_progress)
        )

        # Send final result
        await websocket.send_json({
            "type": "result",
            "data": result.to_dict(),
        })

    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
    except Exception as e:
        log.error(f"WebSocket backtest error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# Analysis & Stress Testing
# ──────────────────────────────────────────────────────────────

class StrategyLeg(BaseModel):
    """One option leg, as consumed by monte_carlo.py / stress_test.py."""
    side: str          # "BUY" | "SELL"
    type: str          # "CE" | "PE"
    strike: float
    premium: float
    qty: int = 1


class AnalysisRequest(BaseModel):
    spot_price: float
    current_iv: float
    days_to_expiry: int
    legs: List[StrategyLeg]
    lot_size: int = 1

@app.post("/api/analysis/monte-carlo")
def get_monte_carlo_analysis(req: AnalysisRequest):
    """Run Monte Carlo simulations for a strategy."""
    try:
        results = run_monte_carlo(
            current_spot=req.spot_price,
            current_iv=req.current_iv,
            days_to_expiry=req.days_to_expiry,
            legs=[leg.model_dump() for leg in req.legs],
            lot_size=req.lot_size
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analysis/stress-test")
def get_stress_test_analysis(req: AnalysisRequest):
    """Run Stress Test scenarios for a strategy."""
    try:
        results = run_stress_tests(
            current_spot=req.spot_price,
            current_iv=req.current_iv,
            days_to_expiry=req.days_to_expiry,
            legs=[leg.model_dump() for leg in req.legs],
            lot_size=req.lot_size
        )
        return {"scenarios": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────
# Serve frontend (production)
# ──────────────────────────────────────────────────────────────

class SPAStaticFiles(StaticFiles):
    """
    Static files with a single-page-app fallback.

    The frontend uses client-side routing (/backtest, /results, ...). Plain
    StaticFiles 404s on those paths, so deep-linking or refreshing anywhere
    other than "/" broke the app. Serve index.html instead and let the router
    resolve the path.

    Two things deliberately keep their 404 rather than falling back:
      - anything with a file extension (a missing bundle must not become an
        HTML 200 that fails to parse as JS), and
      - /api/* (an unknown or misspelled endpoint must return a real 404, not
        HTML that a fetch() would choke on when calling .json()).
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # StaticFiles hands us an OS-native path, so on Windows this arrives
            # as "api\\foo" — normalize before matching the API prefix.
            normalized = path.replace("\\", "/")
            is_api = normalized == "api" or normalized.startswith("api/")
            if exc.status_code == 404 and not Path(path).suffix and not is_api:
                return await super().get_response("index.html", scope)
            raise


frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)
