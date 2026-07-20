"""
data_loader.py — Unified data access layer for the options backtester.

Loads and merges Parquet data from all pipeline tracks:
  - Track A: NSE daily bhavcopy (historical_daily/)
  - Track B: Upstox 1-min intraday (upstox_intraday/)
  - Track C: Kotak/Fyers live (kotak_live/, fyers_intraday/)

Provides helper methods for options chain reconstruction, strike selection,
spot price approximation, and Greeks/IV enrichment.
"""
import logging
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from backend.greeks import black_scholes, implied_volatility

log = logging.getLogger(__name__)


class DataLoader:
    """
    Unified data loader that abstracts away the multi-source Parquet layout.

    Usage:
        loader = DataLoader(base_dir="./options_data/parsed")
        data = loader.load_data("NIFTY", date(2024, 1, 1), date(2024, 3, 31))
        chain = loader.get_options_chain(data, pd.Timestamp("2024-01-25 09:30:00"))
        spot = loader.estimate_spot_price(chain)
    """

    # Subdirectories for each track
    TRACK_DIRS = {
        "historical_daily": "historical_daily",
        "upstox_intraday": "upstox_intraday",
        "kotak_live": "kotak_live",
        "fyers_intraday": "fyers_intraday",
    }

    def __init__(self, base_dir: str = "./options_data/parsed"):
        self.base_dir = Path(base_dir).resolve()
        self._cache: Dict[str, pd.DataFrame] = {}
        log.info(f"DataLoader initialized with base_dir={self.base_dir}")

    @staticmethod
    def _file_in_range(pq_file: Path, start_date: Optional[date],
                       end_date: Optional[date]) -> bool:
        """
        Partition pruning by filename year (files are named e.g. NIFTY_2024.parquet).

        Without this, a one-month backtest still read every year on disk —
        ~25 years of NIFTY bhavcopy — before filtering the rows away. Any file
        whose name doesn't end in a 4-digit year is read, so an unrecognized
        naming scheme degrades to the old behaviour rather than silently
        dropping data.
        """
        if start_date is None and end_date is None:
            return True
        match = re.search(r"(\d{4})$", pq_file.stem)
        if not match:
            return True
        year = int(match.group(1))
        if start_date and year < start_date.year:
            return False
        if end_date and year > end_date.year:
            return False
        return True

    def available_underlyings(self) -> List[str]:
        """List all underlyings that have data on disk."""
        underlyings = set()
        for track_dir in self.TRACK_DIRS.values():
            track_path = self.base_dir / track_dir
            if track_path.exists():
                for child in track_path.iterdir():
                    if child.is_dir() and any(child.glob("*.parquet")):
                        underlyings.add(child.name)
        return sorted(underlyings)

    def _parquet_files(self, underlying: str) -> List[Path]:
        """Every Parquet file for an underlying, across all tracks."""
        files = []
        for track_subdir in self.TRACK_DIRS.values():
            underlying_dir = self.base_dir / track_subdir / underlying
            if underlying_dir.exists():
                files.extend(sorted(underlying_dir.glob("*.parquet")))
        return files

    def _trading_dates(self, underlying: str) -> List[date]:
        """
        Unique trading dates for an underlying, read cheaply.

        Reads ONLY the date column from each Parquet file instead of every
        column of every row. The callers here just need dates, but they used to
        go through load_data() and pull ~8.4M fully-populated NIFTY rows into
        memory, which is what made the first page load hang for ~15s.
        """
        cache_key = f"__dates__{underlying}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        found: set = set()
        for pq_file in self._parquet_files(underlying):
            try:
                available = set(pq.read_schema(pq_file).names)
            except Exception as e:
                log.warning(f"Failed to read schema for {pq_file}: {e}")
                continue

            # `timestamp` is canonical; minimal fixtures only carry `date`.
            column = "timestamp" if "timestamp" in available else (
                "date" if "date" in available else None)
            if column is None:
                continue

            try:
                series = pd.read_parquet(pq_file, columns=[column])[column]
            except Exception as e:
                log.warning(f"Failed to read {column} from {pq_file}: {e}")
                continue

            if pd.api.types.is_datetime64_any_dtype(series):
                parsed = series
            else:
                cleaned = series.astype(str).str.replace(
                    r'(Z|[+-]\d{2}:\d{2})$', '', regex=True)
                parsed = pd.to_datetime(cleaned, format='ISO8601', errors='coerce')
            found.update(parsed.dropna().dt.date.unique())

        result = sorted(found)
        self._cache[cache_key] = result
        return result

    def available_date_range(self, underlying: str) -> Tuple[Optional[date], Optional[date]]:
        """Get the min/max dates available for an underlying across all tracks."""
        dates = self._trading_dates(underlying)
        if not dates:
            return None, None
        return dates[0], dates[-1]

    def load_data(
        self,
        underlying: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        granularity: Optional[str] = None,
        tracks: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Load all options data for an underlying, optionally filtered by
        date range, granularity, and data tracks.

        Parameters:
            underlying: e.g. "NIFTY", "BANKNIFTY"
            start_date: inclusive start date
            end_date: inclusive end date
            granularity: "1min", "5min", "1d" etc. None = all
            tracks: list of track names to load from. None = all

        Returns:
            DataFrame with canonical columns, sorted by timestamp.
        """
        cache_key = f"{underlying}_{start_date}_{end_date}_{granularity}_{tracks}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        frames = []
        search_tracks = tracks or list(self.TRACK_DIRS.keys())

        for track_name in search_tracks:
            track_subdir = self.TRACK_DIRS.get(track_name)
            if not track_subdir:
                continue
            underlying_dir = self.base_dir / track_subdir / underlying
            if not underlying_dir.exists():
                continue

            for pq_file in sorted(underlying_dir.glob("*.parquet")):
                if not self._file_in_range(pq_file, start_date, end_date):
                    continue
                try:
                    df = pd.read_parquet(pq_file)
                    if not df.empty:
                        frames.append(df)
                except Exception as e:
                    log.warning(f"Failed to read {pq_file}: {e}")

        if not frames:
            log.warning(f"No data found for {underlying}")
            return pd.DataFrame()

        data = pd.concat(frames, ignore_index=True)

        # Ensure timestamp is datetime
        def _parse_dates(series):
            if pd.api.types.is_datetime64_any_dtype(series):
                return series
            # Strip timezones to make all naive, keeping local time
            cleaned = series.astype(str).str.replace(r'(Z|[+-]\d{2}:\d{2})$', '', regex=True)
            return pd.to_datetime(cleaned, format='ISO8601', errors='coerce')

        if "timestamp" not in data.columns:
            data["timestamp"] = _parse_dates(data["date"])
        else:
            data["timestamp"] = _parse_dates(data["timestamp"])
            if "date" in data.columns:
                data["timestamp"] = data["timestamp"].fillna(_parse_dates(data["date"]))
                
        if "date" in data.columns:
            data["_date"] = pd.to_datetime(data["date"]).dt.date
        else:
            data["_date"] = data["timestamp"].dt.date

        # Apply filters
        if start_date:
            data = data[data["_date"] >= start_date]
        if end_date:
            data = data[data["_date"] <= end_date]
        if granularity:
            if "granularity" in data.columns:
                data = data[data["granularity"] == granularity]
            else:
                log.warning(
                    f"{underlying}: no 'granularity' column on disk; "
                    f"ignoring granularity={granularity} filter"
                )

        data = data.drop(columns=["_date"], errors="ignore")
        data = data.sort_values("timestamp").reset_index(drop=True)

        # Deduplicate
        dedup_cols = ["timestamp", "underlying", "expiry", "strike", "option_type"]
        existing_cols = [c for c in dedup_cols if c in data.columns]
        if existing_cols:
            data = data.drop_duplicates(subset=existing_cols, keep="last")

        self._cache[cache_key] = data
        log.info(f"Loaded {len(data)} rows for {underlying} "
                 f"({start_date} to {end_date}, granularity={granularity})")
        return data

    def get_options_chain(
        self, data: pd.DataFrame, timestamp: pd.Timestamp,
        expiry: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Reconstruct the options chain at a specific timestamp.

        Returns a DataFrame with one row per (strike, option_type, expiry),
        showing the OHLCV snapshot at that moment.
        """
        mask = data["timestamp"] == timestamp
        chain = data[mask].copy()

        if expiry is not None:
            chain = chain[chain["expiry"] == expiry]

        return chain.sort_values(["expiry", "strike", "option_type"])

    def get_nearest_expiry(self, data: pd.DataFrame,
                           ref_date: date) -> Optional[str]:
        """Get the nearest expiry on or after ref_date."""
        expiries = pd.to_datetime(data["expiry"].unique())
        future = expiries[expiries >= pd.Timestamp(ref_date)]
        if len(future) == 0:
            return None
        return str(future.min().date())

    def get_expiries(self, data: pd.DataFrame,
                     ref_date: Optional[date] = None) -> List[str]:
        """List all available expiries, optionally only those after ref_date."""
        expiries = sorted(data["expiry"].unique())
        if ref_date:
            expiries = [e for e in expiries if e >= str(ref_date)]
        return expiries



    def get_strikes(self, data: pd.DataFrame, expiry: str) -> List[float]:
        """List all strikes for a given expiry."""
        mask = data["expiry"] == expiry
        return sorted(data[mask]["strike"].unique())

    def get_timestamps(self, data: pd.DataFrame,
                       trading_date: Optional[date] = None) -> List[pd.Timestamp]:
        """List all unique timestamps, optionally for a specific date."""
        if trading_date:
            mask = data["timestamp"].dt.date == trading_date
            ts = data[mask]["timestamp"].unique()
        else:
            ts = data["timestamp"].unique()
        return sorted(ts)

    def estimate_spot_price(self, chain: pd.DataFrame) -> Optional[float]:
        """
        Estimate the spot price from the options chain using the
        put-call parity approximation: Spot ≈ strike where CE_close ≈ PE_close.

        Falls back to the strike with minimum |CE_close - PE_close|.
        """
        if chain.empty:
            return None

        # Put-call parity needs a price column; some sources (and minimal
        # fixtures) ship only volume/oi, in which case fall back below.
        if "close" not in chain.columns:
            log.warning("estimate_spot_price: no 'close' column in chain")
            if "volume" in chain.columns and not chain["volume"].isna().all():
                return float(chain.loc[chain["volume"].idxmax(), "strike"])
            return None

        # Get the nearest expiry
        nearest_expiry = sorted(chain["expiry"].unique())[0]
        exp_chain = chain[chain["expiry"] == nearest_expiry]

        ce = exp_chain[exp_chain["option_type"].isin(["CE"])].set_index("strike")["close"]
        pe = exp_chain[exp_chain["option_type"].isin(["PE"])].set_index("strike")["close"]

        common_strikes = ce.index.intersection(pe.index)
        if len(common_strikes) == 0:
            # Fallback: use the strike with highest volume
            if "volume" in chain.columns:
                max_vol_idx = chain["volume"].idxmax()
                return chain.loc[max_vol_idx, "strike"]
            return None

        diff = (ce[common_strikes] - pe[common_strikes]).abs()
        atm_strike = diff.idxmin()
        # Better approximation: Spot ≈ ATM_strike + CE_price - PE_price
        spot = atm_strike + ce[atm_strike] - pe[atm_strike]
        return float(spot)

    def select_strike(
        self,
        chain: pd.DataFrame,
        spot_price: float,
        option_type: str = "CE",
        moneyness: str = "ATM",
        offset: int = 0,
        expiry: Optional[str] = None,
    ) -> Optional[float]:
        """
        Select a strike based on moneyness relative to spot.

        Parameters:
            chain: options chain DataFrame
            spot_price: current spot price
            option_type: "CE" or "PE"
            moneyness: "ATM", "ITM", "OTM"
            offset: number of strikes away from ATM (0=ATM, 1=1 strike OTM, etc.)
            expiry: specific expiry to use

        Returns:
            Selected strike price, or None if not available.
        """
        if expiry:
            chain = chain[chain["expiry"] == expiry]

        type_chain = chain[chain["option_type"] == option_type]
        strikes = sorted(type_chain["strike"].unique())

        if not strikes:
            return None

        # Find ATM strike
        atm_idx = int(np.argmin([abs(s - spot_price) for s in strikes]))

        if moneyness == "ATM":
            target_idx = atm_idx + offset
        elif moneyness == "OTM":
            if option_type == "CE":
                target_idx = atm_idx + offset + 1  # Higher strikes
            else:
                target_idx = atm_idx - offset - 1  # Lower strikes
        elif moneyness == "ITM":
            if option_type == "CE":
                target_idx = atm_idx - offset - 1  # Lower strikes
            else:
                target_idx = atm_idx + offset + 1  # Higher strikes
        else:
            target_idx = atm_idx

        target_idx = max(0, min(target_idx, len(strikes) - 1))
        return strikes[target_idx]

    def get_option_price(
        self, data: pd.DataFrame, timestamp: pd.Timestamp,
        strike: float, option_type: str, expiry: str,
        price_field: str = "close",
    ) -> Optional[float]:
        """Get the price of a specific option at a specific timestamp."""
        mask = (
            (data["timestamp"] == timestamp)
            & (data["strike"] == strike)
            & (data["option_type"] == option_type)
            & (data["expiry"] == expiry)
        )
        rows = data[mask]
        if rows.empty:
            return None
        return float(rows.iloc[0][price_field])

    @staticmethod
    def get_historical_lot_size(underlying: str, date_obj: date) -> int:
        """
        Dynamically return the lot size based on historical NSE contract changes.
        """
        underlying = underlying.upper()
        
        if underlying == "NIFTY":
            if date_obj >= date(2024, 4, 26):
                return 25
            elif date_obj >= date(2021, 7, 1):
                return 50
            else:
                return 75
                
        elif underlying == "BANKNIFTY":
            if date_obj >= date(2023, 7, 1):
                return 15
            elif date_obj >= date(2016, 7, 1):
                return 25
            else:
                return 40
                
        elif underlying == "FINNIFTY":
            if date_obj >= date(2023, 10, 31):
                return 25
            else:
                return 40
                
        elif underlying == "MIDCPNIFTY":
            if date_obj >= date(2024, 4, 26):
                return 50
            else:
                return 75
                
        elif underlying == "SENSEX":
            return 10
            
        # Default fallback
        return 50

    def get_available_trading_dates(self, underlying: str) -> List[str]:
        """Return all unique trading dates available for an underlying."""
        return [str(d) for d in self._trading_dates(underlying)]

    def get_valid_expiries(
        self, underlying: str, trading_date: str
    ) -> List[str]:
        """
        Return only expiries that actually existed in the data on the given
        trading date.  This prevents the user from selecting arbitrary expiry
        dates.
        """
        data = self.load_data(underlying)
        if data.empty:
            return []
        target = date.fromisoformat(trading_date)
        mask = data["timestamp"].dt.date == target
        day_data = data[mask]
        if day_data.empty:
            return []
        return sorted(day_data["expiry"].unique().tolist())

    def get_available_timestamps_for_date(
        self, underlying: str, trading_date: str
    ) -> List[str]:
        """
        Return all unique timestamps (as ISO strings) for a given trading date.
        Useful for the time-slider in the UI.
        """
        data = self.load_data(underlying)
        if data.empty:
            return []
        target = date.fromisoformat(trading_date)
        mask = data["timestamp"].dt.date == target
        day_data = data[mask]
        if day_data.empty:
            return []
        ts = sorted(day_data["timestamp"].unique())
        # isoformat() (not str()) so the value is genuinely ISO-8601 —
        # "2024-01-02T09:20:00" rather than "2024-01-02 09:20:00". The UI splits
        # on "T" to derive the time-of-day, and api.py rebuilds "<date>T<time>".
        return [pd.Timestamp(t).isoformat() for t in ts]

    def enrich_chain_with_greeks(
        self,
        chain: pd.DataFrame,
        spot_price: float,
        risk_free_rate: float = 0.065,
    ) -> pd.DataFrame:
        """
        Compute IV, Delta, Gamma, Theta, Vega, Rho for every row in the
        options chain and add them as columns.
        """
        if chain.empty or spot_price is None:
            for col in ["iv", "delta", "gamma", "theta", "vega", "rho", "moneyness"]:
                chain[col] = np.nan if col != "moneyness" else ""
            return chain

        enriched = chain.copy()
        ivs, deltas, gammas, thetas, vegas, rhos, moneyness = [], [], [], [], [], [], []

        for _, row in enriched.iterrows():
            price = row.get("close", 0)
            strike = row["strike"]
            opt_type = row["option_type"]
            expiry_str = str(row["expiry"])

            # Time to expiry in years
            try:
                expiry_date = pd.to_datetime(expiry_str).date()
                ts = pd.to_datetime(row.get("timestamp", row.get("date")))
                if hasattr(ts, 'date'):
                    current_date = ts.date() if callable(getattr(ts, 'date', None)) else ts
                else:
                    current_date = pd.to_datetime(row.get("date", expiry_str)).date()
                dte_days = max(0, (expiry_date - current_date).days)
                T = max(dte_days / 365.0, 1e-6)
            except Exception:
                T = 1 / 365.0  # 1 day fallback

            flag = 'c' if opt_type in ('CE', 'CA') else 'p'

            # Moneyness
            if opt_type in ('CE', 'CA'):
                if abs(strike - spot_price) < spot_price * 0.005:
                    mon = 'ATM'
                elif strike < spot_price:
                    mon = 'ITM'
                else:
                    mon = 'OTM'
            else:
                if abs(strike - spot_price) < spot_price * 0.005:
                    mon = 'ATM'
                elif strike > spot_price:
                    mon = 'ITM'
                else:
                    mon = 'OTM'
            moneyness.append(mon)

            # Compute IV
            try:
                if price > 0.01 and spot_price > 0 and strike > 0:
                    iv_val = implied_volatility(flag, price, spot_price, strike, T, risk_free_rate)
                    if iv_val <= 0 or iv_val > 5.0:
                        iv_val = np.nan
                else:
                    iv_val = np.nan
            except Exception:
                iv_val = np.nan
            ivs.append(iv_val)

            # Compute Greeks using IV (or a default)
            sigma = iv_val if not np.isnan(iv_val) else 0.20
            try:
                greeks = black_scholes(flag, spot_price, strike, T, risk_free_rate, sigma)
                deltas.append(greeks["delta"])
                gammas.append(greeks["gamma"])
                thetas.append(greeks["theta"])
                vegas.append(greeks["vega"])
                rhos.append(greeks["rho"])
            except Exception:
                deltas.append(np.nan)
                gammas.append(np.nan)
                thetas.append(np.nan)
                vegas.append(np.nan)
                rhos.append(np.nan)

        enriched["iv"] = ivs
        enriched["delta"] = deltas
        enriched["gamma"] = gammas
        enriched["theta"] = thetas
        enriched["vega"] = vegas
        enriched["rho"] = rhos
        enriched["moneyness"] = moneyness
        return enriched

    def clear_cache(self):
        """Clear the data cache."""
        self._cache.clear()
