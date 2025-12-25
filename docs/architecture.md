# Architecture

This system is designed as a modular pipeline where each component has a single responsibility.
The core value is the **market intelligence layer** (valid entry logic derived from order flow).

---

## Data Flow (High Level)

Binance Order Book (raw data)
↓
Aggregator

collects raw order book updates

aggregates + normalizes

outputs: aggregated.csv
↓
DeltaScout

reads: aggregated.csv

computes: delta / imbalance metrics

outputs: PEAK events (JSONL)
├── Buyer
│ - reads: PEAK events
│ - produces:  trade plan (Entry /SL/TP1/TP2)
│ - sends: Telegram alerts via n8n
│
       └────────────────│── Executor
- reads: PEAK events
- executes: paper trading (DRY mode)
- planned: live Binance execution
- 
---

## Key Interfaces

- `aggregated.csv` (Aggregator → DeltaScout)  
  Normalized market feed used for signal computation.

- `deltascout.log` (DeltaScout → Buyer/Executor)  
  Append-only JSONL stream of `PEAK` events.

Buyer and Executor are **parallel consumers** of the same event stream.

---

## Separation of Concerns

- **Aggregator**: data collection + normalization (no trading logic)
- **DeltaScout**: market intelligence (signal generation)
- **Buyer**: risk plan + human notifications (no execution)
- **Executor**: execution layer (paper now, live later)

This separation keeps the system maintainable and allows easy evolution of each module.
