---
license: other
pretty_name: NSE Options Historical Data (Intraday + Daily)
tags:
  - finance
  - options
  - nse
  - india
  - backtesting
size_categories:
  - 1B<n<10B
---

# NSE Options Historical Data

Historical Indian index-options data (NIFTY, BANKNIFTY, SENSEX) for backtesting,
in a single canonical Parquet schema. Assembled from NSE F&O bhavcopy (daily EOD,
2001→present) and Upstox 1-minute intraday candles (2024→present).

## Coverage

| Track | Underlyings | Granularity | Range |
|---|---|---|---|
| `upstox_intraday/` | NIFTY, BANKNIFTY, SENSEX | 1 minute | Oct 2024 → 2026 (BANKNIFTY from Mar 2024) |
| `historical_daily/` | NIFTY (2001→), BANKNIFTY (2005→) | 1 day (EOD) | 2001 → present |

~2.3 GB total, 62 Parquet files.

## Layout

Partitioned by track / underlying / year:

```
upstox_intraday/NIFTY/NIFTY_2025.parquet
historical_daily/BANKNIFTY/BANKNIFTY_2010.parquet
```

Files are named `{UNDERLYING}_{YEAR}.parquet`, so a date-ranged query only needs
to open the relevant years.

## Schema (16 columns)

| Column | Type | Notes |
|---|---|---|
| `date` | string `YYYY-MM-DD` | Trading date |
| `timestamp` | timestamp (IST) | Candle start; daily rows = date at market close |
| `underlying` | string | NIFTY / BANKNIFTY / SENSEX |
| `expiry` | string | Contract expiry date |
| `strike` | float | Strike price |
| `option_type` | string | CE / PE |
| `exercise_style` | string | european / american |
| `open` `high` `low` `close` | float | OHLC |
| `volume` | float | Contracts traded |
| `oi` | float | Open interest (NaN for Upstox intraday) |
| `settle_price` | float | NaN for intraday |
| `source` | string | e.g. `upstox_expired`, `nse_bhavcopy` |
| `granularity` | string | `1min` / `1d` |

## Loading

```python
import pandas as pd
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="<your-username>/nse-options-intraday",
    filename="upstox_intraday/NIFTY/NIFTY_2025.parquet",
    repo_type="dataset",
)
df = pd.read_parquet(path)
```

Or grab the whole dataset:

```python
from huggingface_hub import snapshot_download
local = snapshot_download(repo_id="<your-username>/nse-options-intraday", repo_type="dataset")
```

## Notes & attribution

- Daily data derives from the NSE F&O bhavcopy (publicly published by NSE).
- Intraday data was collected via the Upstox historical API; redistribute in line
  with the source providers' terms.
- `oi` and `settle_price` are NaN on Upstox intraday rows (not returned by that API).
