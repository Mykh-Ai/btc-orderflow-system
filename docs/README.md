## Execution-first Order-Flow Analytics Stack for Binance Spot
(VPS • Docker • n8n • Telegram • Binance Spot)

This repository is an end-to-end **market data → analytics → alerts → execution** stack deployed on a VPS.
Goal: demonstrate a **full spectrum system**, not a single script.

**Pipeline:** Binance Market Feed → VPS (Docker) → Aggregator/Analytics → n8n automation → Telegram alerts → Binance Spot API (Executor)

> ⚠️ **Disclaimer:** This is an educational/engineering project. **Not financial advice.** Use at your own risk.

### Scope
This is a demonstration / research project focused on:

- real-time market data ingestion and aggregation
- order-flow based signal detection
- execution flow with explicit risk and state control
- safe separation between data, signals, and execution
- designing systems that can survive partial fills, latency, and API failures

## Important
- No trading strategy or profitability claims are included
- Production-ready execution logic and integrations are developed
  separately and adapted within individual client projects

## Components
- `aggregator` — real-time market data ingestion
- `deltascout` — order flow / imbalance signal detection
- `executor` — execution flow demo (orders, state, risk handling)
- `buyer` — example alert / action handling module

## Research Data Architecture

The system maintains four data channels relevant to research and analysis:

| Channel | Path | Format | Role |
|---------|------|--------|------|
| **Canonical input** | `/root/volume-alert/data/feed/aggregated.csv` (live) | CSV, 10 columns | Minute-level market feed from Aggregator |
| **Decision archive** | *(planned)* `/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl` | JSONL | Research delta archive capturing every decision point |
| **Live signal bus** | `/data/logs/deltascout.log` | JSONL | PEAK events consumed by Buyer and Executor |
| **Execution outcome** | `/data/logs/executor.log` | JSONL | Executor action log (open, close, state transitions) |

For the full research infrastructure specification, see [DeltaScout_Research_Phase1_Spec.md](DeltaScout_Research_Phase1_Spec.md).

## Notes
This repository is intended as a **portfolio and technical showcase**
to demonstrate system design and engineering approach.



