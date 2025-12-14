# Data Contracts

This document describes the main data interfaces between modules.

The system is built around two primary artifacts:
- `aggregated.csv` — normalized market feed produced by **Aggregator**
- `deltascout.log` (JSONL) — event stream produced by **DeltaScout** (PEAK events)

These contracts allow Buyer and Executor to remain decoupled from the raw Binance API.

---

## 1) Aggregator Output: `aggregated.csv`

**Purpose:** normalized minute-level feed used by DeltaScout.

**Path (typical):**
- `/data/feed/aggregated.csv`

### Required columns
| Column | Type | Description |
|---|---|---|
| `Timestamp` | string/datetime | Candle minute timestamp (UTC recommended) |
| `BuyQty` | float | Total aggressive buy quantity for the minute |
| `SellQty` | float | Total aggressive sell quantity for the minute |
| `ClosePrice` | float | Close price for the minute (or `AvgPrice` if used) |

### Optional columns (allowed)
- `AvgPrice` (float)
- `Trades` (int)
- `TotalQty` (float)
- any additional telemetry fields

### Notes
- DeltaScout treats the feed as append-only time series.
- If both `ClosePrice` and `AvgPrice` exist, `ClosePrice` is preferred.
- Timestamps are expected to be minute-aligned (or will be floored to minute resolution).

---

## 2) DeltaScout Output: `deltascout.log` (JSONL)

**Purpose:** append-only event stream consumed by Buyer and Executor.

**Path (typical):**
- `/data/logs/deltascout.log`

### Event format
Each line is one JSON object.

### PEAK event (minimum fields)
```json
{
  "ts": "2025-12-13T11:34:00Z",
  "action": "PEAK",
  "kind": "short",
  "price": 90399.0,
  "delta": -123.45,
  "imb": 0.62,
  "vol": 18.7
}
| Field    | Type   | Description                                 |
| -------- | ------ | ------------------------------------------- |
| `ts`     | string | Event timestamp (ISO 8601, UTC recommended) |
| `action` | string | `"PEAK"`                                    |
| `kind`   | string | `"long"` or `"short"`                       |
| `price`  | float  | Reference price at signal time              |
| `delta`  | float  | Delta value used by the trigger             |
| `imb`    | float  | Imbalance metric at signal time             |
| `vol`    | float  | Volume metric used by the trigger           |

Notes

Buyer and Executor must not write back to deltascout.log.

Consumers should implement deduplication (hash or event id).

The system assumes single active position mode in Executor (for now).

3) Consumer behavior (Buyer / Executor)

Both consumers:

read the same PEAK stream

apply their own logic

write only to their own state/logs

Buyer:

produces human-readable trade plan

sends alerts to Telegram (via n8n)

Executor:

runs paper execution in DRY mode

live execution is planned (Binance integration)
