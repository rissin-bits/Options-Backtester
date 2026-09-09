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

try:
    import duckdb
    _HAS_DUCKDB = True
except ImportError:            # pandas/pyarrow fallback still works without it
    _HAS_DUCKDB = False

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
        Unique trading dates for an underlying.

        Deduplicates in Arrow rather than pandas. The `date` column is a string
        with only ~250 distinct values per year, so pyarrow.compute.unique reads
        the (dictionary-compressed) column and returns the small distinct set —
        instead of materializing 124M timestamps and calling .dt.date on each,
        which took ~28s for NIFTY. Falls back to the `timestamp` column, cast to
        a date before uniquing, only when no `date` column exists.
        """
        import pyarrow as pa
        import pyarrow.compute as pc

        cache_key = f"__dates__{underlying}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        found: set = set()
        for pq_file in self._parquet_files(underlying):
            try:
                names = pq.read_schema(pq_file).names
            except Exception as e:
                log.warning(f"Failed to read schema for {pq_file}: {e}")
                continue

            column = "date" if "date" in names else (
                "timestamp" if "timestamp" in names else None)
            if column is None:
                continue

            try:
                arr = pq.read_table(pq_file, columns=[column]).column(column)
                if pa.types.is_timestamp(arr.type):
                    arr = pc.cast(arr, pa.date32())  # collapse to day before uniquing
                for v in pc.unique(arr).to_pylist():
                    d = self._stat_to_date(v)
                    if d:
                        found.add(d)
            except Exception as e:
                log.warning(f"Failed to read {column} from {pq_file}: {e}")
                continue

        result = sorted(found)
        self._cache[cache_key] = result
        return result

    @staticmethod
    def _stat_to_date(value) -> Optional[date]:
        """Coerce a Parquet column-statistic min/max value to a date."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return pd.to_datetime(str(value)[:10], errors="coerce").date()
        except (ValueError, TypeError):
            return None

    def available_date_range(self, underlying: str) -> Tuple[Optional[date], Optional[date]]:
        """
        Min/max available dates for an underlying, read from Parquet row-group
        statistics rather than the data itself.

        Reading the date column across ~124M rows of merged intraday data took
        tens of seconds and made the first load of the data-driven tabs hang.
        Column min/max stats live in the file footer, so this is a metadata-only
        scan (~milliseconds) that returns the identical range.
        """
        cache_key = f"__range__{underlying}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        lo = hi = None
        for pq_file in self._parquet_files(underlying):
            try:
                md = pq.read_metadata(pq_file)
                names = md.schema.to_arrow_schema().names
                col = "date" if "date" in names else (
                    "timestamp" if "timestamp" in names else None)
                if col is None:
                    continue
                idx = names.index(col)
                for rg in range(md.num_row_groups):
                    stats = md.row_group(rg).column(idx).statistics
                    if not stats or not stats.has_min_max:
                        raise ValueError("no stats")  # fall back to a data read
                    dmin = self._stat_to_date(stats.min)
                    dmax = self._stat_to_date(stats.max)
                    if dmin and (lo is None or dmin < lo):
                        lo = dmin
                    if dmax and (hi is None or dmax > hi):
                        hi = dmax
            except Exception:
                # Any file without usable stats: fall back to the full scan,
                # which is correct (just slower) for that one underlying.
                dates = self._trading_dates(underlying)
                result = (dates[0], dates[-1]) if dates else (None, None)
                self._cache[cache_key] = result
                return result

        result = (lo, hi)
        self._cache[cache_key] = result
        return result

    @staticmethod
    def _date_pushdown(pq_file: Path, start_date: Optional[date],
                       end_date: Optional[date]):
        """
        Build a pyarrow predicate on the `date` column so only the relevant
        row groups are read from disk. A one-month backtest previously read the
        whole year file (14M–69M rows) and filtered in pandas; pushdown lets the
        Parquet reader skip row groups outside the range via their min/max stats.

        Only applied to a string `date` column (the large intraday files), where
        ISO 'YYYY-MM-DD' strings sort chronologically. Returns None otherwise —
        daily files are tiny, so reading them whole costs nothing. The pandas
        `_date` filter downstream still enforces exact bounds, so pushdown only
        ever needs to be a superset; results are identical either way.
        """
        if start_date is None and end_date is None:
            return None
        try:
            import pyarrow as pa
            field = pq.read_schema(pq_file).field("date")
        except (KeyError, Exception):
            return None
        if not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
            return None
        conds = []
        if start_date:
            conds.append(("date", ">=", start_date.isoformat()))
        if end_date:
            conds.append(("date", "<=", end_date.isoformat()))
        return conds or None

    def _read_track(self, files: List[Path],
                    start_date: Optional[date],
                    end_date: Optional[date]) -> pd.DataFrame:
        """
        Read one track's (already year-pruned) Parquet files as a single frame,
        date-filtered, using DuckDB when available and falling back to pandas.

        DuckDB reads the whole file set in one parallel columnar scan, which is
        ~5x faster than reading each file with pandas (a 4-day NIFTY slice: ~1.4s
        vs ~7s). Correctness never depends on it: if DuckDB is missing or errors
        for any reason, it falls back to per-file pandas+pyarrow reads, which the
        tests pin as the reference and which produce byte-identical results.

        A plain ISO string literal in the predicate keeps row-group pushdown
        working for both the string `date` column (intraday) and the datetime
        one (daily) — DuckDB casts the literal to the column type.
        """
        if _HAS_DUCKDB:
            try:
                paths = ", ".join(
                    "'" + str(f).replace("\\", "/").replace("'", "''") + "'"
                    for f in files
                )
                where = []
                if start_date:
                    where.append(f"date >= '{start_date.isoformat()}'")
                if end_date:
                    where.append(f"date <= '{end_date.isoformat()}'")
                clause = (" WHERE " + " AND ".join(where)) if where else ""
                con = duckdb.connect()
                try:
                    return con.execute(
                        f"SELECT * FROM read_parquet([{paths}], union_by_name=true){clause}"
                    ).df()
                finally:
                    con.close()
            except Exception as e:
                log.warning(f"DuckDB read failed ({e}); using pandas for {len(files)} file(s)")

        frames = []
        for f in files:
            try:
                df = pd.read_parquet(f, filters=self._date_pushdown(f, start_date, end_date))
                if not df.empty:
                    frames.append(df)
            except Exception as e:
                log.warning(f"Failed to read {f}: {e}")
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

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

            ranged = [f for f in sorted(underlying_dir.glob("*.parquet"))
                      if self._file_in_range(f, start_date, end_date)]
            if not ranged:
                continue
            df = self._read_track(ranged, start_date, end_date)
            if not df.empty:
                frames.append(df)

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
            ts = _parse_dates(data["timestamp"])
            # Only fall back to the `date` column for rows whose timestamp
            # failed to parse. Computing _parse_dates(date) unconditionally ran
            # a regex over ~800k string dates on every load (~5s) even when the
            # timestamp column was already fully valid — the common case.
            if "date" in data.columns and ts.isna().any():
                ts = ts.fillna(_parse_dates(data["date"]))
            data["timestamp"] = ts
                
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
        target = date.fromisoformat(trading_date)
        # Scope the load to the single day. Loading the whole underlying and
        # filtering in memory pulled ~124M rows for NIFTY once the intraday
        # backfill landed, exhausting RAM.
        data = self.load_data(underlying, target, target)
        if data.empty:
            return []
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
        target = date.fromisoformat(trading_date)
        data = self.load_data(underlying, target, target)  # one day, not all history
        if data.empty:
            return []
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
