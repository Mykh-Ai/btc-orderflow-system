# DeltaScout (signals from `aggregated.csv`)

DeltaScout monitors the aggregated trade feed produced by the Aggregator (`aggregated.csv`) and emits JSONL events (including `PEAK`) for downstream consumers (e.g., Buyer/Executor).

## What it does

- Tails `aggregated.csv` and processes new rows as they appear.
- Maintains a rolling window of recent 1-minute rows.
- Computes lightweight volume/imbalance/delta-style metrics from executed-trade aggregates.
- Applies a trigger pipeline and writes events as JSONL lines into `deltascout.log`.
- Optionally sends debug payloads to a webhook (if configured).

## Inputs / Outputs

### Input

- Aggregated CSV file (configured via `FILE_PATH`):
  - `Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice`

### Output

- JSONL log file (configured via `DELTASCOUT_LOG`):
  - one JSON object per line
  - includes event types such as `PEAK` and warmup/init events (`INIT_MAX`, `INIT_MIN`) depending on settings

## Configuration

The script uses environment variables for configuration.

Common variables:

- `FILE_PATH` — path to `aggregated.csv`
- `DELTASCOUT_LOG` — output JSONL log path
- `POLL_SECS` — how often to poll for new data
- `ROLL_WINDOW_MIN`, `STARTUP_LOOKBACK_MIN` — rolling/window sizing
- `WEBHOOK_URL` — optional webhook endpoint for debug payloads
- Tier/gate parameters: `TIER_*`, `IMB_*`, `AVG9_MAX`, `CHOP30_MAX`, `COH10_MIN`, etc.

Peak/trigger thresholds are required via environment variables.  
See `.env.example`. The service will not start without them.

## Run

Install deps:

```bash
pip install pandas numpy

