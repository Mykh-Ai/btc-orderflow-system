## Execution-first Order-Flow Analytics Stack for Binance Spot
(VPS • Docker • n8n • Telegram • Binance Spot)

This repository is an end-to-end **market data → analytics → alerts → execution** stack deployed on a VPS.
Goal: demonstrate a **full spectrum system**, not a single script.

**Pipeline:** Binance Market Feed → VPS (Docker) → Aggregator/Analytics → n8n automation → Telegram alerts → Binance Spot API (Executor)

> **Disclaimer:** This is an educational/engineering project. **Not financial advice.** Use at your own risk.

### Scope
This is a demonstration / research project focused on:

- real-time market data ingestion and aggregation
- order-flow based signal detection
- execution flow with explicit risk and state control
- safe separation between data, signals, and execution
- designing systems that can survive partial fills, latency, and API failures
- **research instrumentation** for offline analysis and signal quality evaluation

## Important
- No trading strategy or profitability claims are included
- Production-ready execution logic and integrations are developed
  separately and adapted within individual client projects

## Components

| Module | Path | Role |
|--------|------|------|
| **Aggregator** | `aggregator/` | Real-time Binance WS → 1-minute CSV feed + daily feed archive |
| **DeltaScout** | `deltascout/` | Order-flow signal detection with Phase 1 research instrumentation |
| **Executor** | `executor/` | Execution flow (orders, state, risk handling) |
| **Buyer** | `buyer/` | Alert / action handling module |
| **Offline scripts** | `scripts/offline/` | Derived dataset builders for research analysis |

## Data Architecture

### Live data channels

| Channel | Container path | Host path | Format | Role |
|---------|---------------|-----------|--------|------|
| **Market feed** | `/app/feed/aggregated.csv` | `data/feed/aggregated.csv` | CSV, 10 columns | Rolling 1500-row live feed from Aggregator |
| **Signal bus** | `/data/logs/deltascout.log` | `data/logs/deltascout.log` | JSONL | PEAK events consumed by Buyer and Executor (truncated at 500 rows) |
| **Execution log** | `/data/logs/executor.log` | `data/logs/executor.log` | JSONL | Executor actions (open, close, state transitions) |

### Research archive (Phase 1)

| Channel | Container path | Host path | Format | Retention |
|---------|---------------|-----------|--------|-----------|
| **Feed archive** | `/data/archive/feed/YYYY-MM-DD.csv` | `data/archive/feed/YYYY-MM-DD.csv` | CSV, 10 columns | Append-only, daily files, dedup by Timestamp |
| **Decision archive** | `/data/archive/deltascout/YYYY-MM-DD.jsonl` | `data/archive/deltascout/YYYY-MM-DD.jsonl` | JSONL | Append-only, all decision events per day |

### Feed CSV schema (10 columns)

```
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
```

### Research event types (runtime)

| Event | Trigger | Key fields |
|-------|---------|------------|
| `DELTA_MAX` | New rolling window maximum | ts, delta, vol, imb, price, vwap, poc |
| `DELTA_MIN` | New rolling window minimum | ts, delta, vol, imb, price, vwap, poc |
| `CANDIDATE_COMPARISON_REJECT` | Failed base check or 3/3 rule | ts, kind, reject_reason, prev_* |
| `CANDIDATE_GATE_REJECT` | Failed gate check (EMA50/VWAP/CHOP30/COH10/IMB) | ts, kind, reject_reason, gate_values, thresholds |
| `PEAK_EMIT` | Successful PEAK (mirror to archive) | Full PEAK payload + gate values |

Every research event includes `schema` (version), `event` (type), `seq` (monotonic counter), `ts` (timestamp).

### Derived events (offline)

| Event | Source | Script |
|-------|--------|--------|
| `WINDOW_OWNERSHIP_MISS` | Reconstructed from DELTA_MAX/MIN + feed data | `scripts/offline/build_phase1_derived.py` |
| `EXEC_CLOSE` | Executor log + state snapshots | `scripts/offline/build_close_outcomes.py` |

### Isolation guarantees

- Research archive is a **separate channel** from the live signal bus (`deltascout.log`)
- Research writes never pass through live-bus truncation logic
- Research write failures are soft-fail and never block PEAK emission
- Archive files are never read by live trading components

## Architecture notes

- Aggregator maintains a rolling 1500-row live CSV and simultaneously appends each row to the daily feed archive
- DeltaScout processes the live CSV through a five-stage pipeline (feed → delta detection → comparison → gates → PEAK emit), logging research events at each decision point
- The research archive enables offline reconstruction of the full decision funnel, including events invisible to the live system (window ownership misses, late peak recognition)

For the full research specification, see [DeltaScout_Research_Phase1_Spec.md](DeltaScout_Research_Phase1_Spec.md).

## Notes
This repository is intended as a **portfolio and technical showcase**
to demonstrate system design and engineering approach.
