## Execution-First Order-Flow Analytics Stack for Binance Spot

(VPS, Docker, n8n, Telegram, Binance Spot)

End-to-end market data -> analytics -> alerts -> execution stack deployed on a VPS.

**Pipeline:** Binance WS -> Aggregator -> DeltaScout -> Buyer / Executor -> Telegram / Binance API

> **Disclaimer:** Educational and engineering project. Not financial advice.

---

## Components

| Module | Path | What it does |
|--------|------|--------------|
| **Aggregator** | `aggregator/` | Connects to Binance WS and aggregates trades into 1-minute CSV rows |
| **DeltaScout** | `deltascout/` | Reads the CSV feed, detects delta peaks, emits PEAK signals, and writes research events |
| **Buyer** | `buyer/` | Reacts to PEAK signals and sends Telegram alerts via n8n |
| **Executor** | `executor/` | Reacts to PEAK signals and manages positions on Binance Spot |
| **Offline scripts** | `scripts/offline/` | Build derived research datasets from archived data |

---

## What Writes Where

### Aggregator writes

| What | Path (container) | Path (host) | Format | Behavior |
|------|-------------------|-------------|--------|----------|
| Live feed | `/data/feed/aggregated.csv` | `data/feed/aggregated.csv` | CSV, 10 columns | Rolling 1500 rows |
| Feed archive | `/data/archive/feed/YYYY-MM-DD.csv` | `data/archive/feed/YYYY-MM-DD.csv` | CSV, 10 columns | Append-only, one file per day, dedup by `Timestamp` |

Every minute the Aggregator writes one row to the live feed and appends the same row to the daily feed archive.

### Market-data contours used today

The project currently operates with two different daily market-data contours for research:

| Contour | Main path | Who writes it | Who reads it | Status in this repo |
|------|------|------|------|------|
| Runtime archive contour | `/data/archive/feed/YYYY-MM-DD.csv` | `aggregator/binance_run_aggregator.py` via `FEED_ARCHIVE_DIR` (default `/data/archive/feed`) | Local/manual research copies; self-contained fallback for `scripts/offline/build_phase1_derived.py` when `--feed-root` is not passed | Implemented writer in this repo |
| External enriched contour | `/opt/aitrader/feed/YYYY-MM-DD.csv` | Not written by code in this repo | DeltaScout research/offline flows documented in `deltascout/README.md`; `scripts/offline/build_phase1_derived.py` via `--feed-root`; `deltascout.delta_analyzer.cli` via `--feed-glob` default | External reader target, not a local writer |

These are different market-data contours. The documentation describes them as separate contours, not one conceptual feed.
The runtime trading path uses `/data/feed/aggregated.csv`; Buyer and Executor do not read either daily archive contour directly.
For research of market state, interpretations need the contour path to stay explicit rather than being silently carried over from one contour to the other.

### DeltaScout writes

| What | Path (container) | Path (host) | Format | Behavior |
|------|-------------------|-------------|--------|----------|
| PEAK signal bus | `/data/logs/deltascout.log` | `data/logs/deltascout.log` | JSONL | Live bus for Buyer and Executor, truncated at 500 rows |
| Research archive | `/data/archive/deltascout/YYYY-MM-DD.jsonl` | `data/archive/deltascout/YYYY-MM-DD.jsonl` | JSONL | Append-only, one file per day, never truncated |

### Executor writes

| What | Path (container) | Path (host) | Format |
|------|-------------------|-------------|--------|
| Action log | `/data/logs/executor.log` | `data/logs/executor.log` | JSONL |
| State | `/data/state/executor_state.json` | `data/state/executor_state.json` | JSON |
| Trade outcomes journal | `/data/state/trade_outcomes.jsonl` | `data/state/trade_outcomes.jsonl` | JSONL |

`trade_outcomes.jsonl` is the canonical append-only operational journal for closed trade outcomes. This is one of the latest research-layer additions from the 2.0 line that is already used in the current research workflow, even though day-to-day work remains focused on the `research` branch.

---

## PEAK Signal Lifecycle

```text
Aggregator                DeltaScout                    Buyer / Executor
    |                         |                              |
    | aggregated.csv row      |                              |
    |------------------------>|                              |
    |                         | delta detection              |
    |                         | comparison (3/3 rule)        |
    |                         | gate checks                  |
    |                         | PASS / FAIL                  |
    |                         |   |                          |
    |                         |   +-> reject -> research     |
    |                         |       archive                |
    |                         |                              |
    |                         | PEAK -> deltascout.log       |
    |                         |----------------------------->|
    |                         |                              | reads PEAK,
    |                         | PEAK_EMIT mirror             | sends alert
    |                         | -> research archive          | or opens position
```

**PEAK** is the core signal. It means DeltaScout detected a delta extreme that passed:

- rolling window ownership
- 3/3 comparison rule
- gate filters such as EMA50, VWAP position, CHOP30, COH10, and IMB range

Each PEAK is written to `deltascout.log` and mirrored as `PEAK_EMIT` to the research archive.

---

## Research Archive

The research archive captures every decision point in the DeltaScout pipeline. It is separate from the live signal bus and is never read by trading components.

### Events recorded at runtime

| Event | When | What it tells you |
|-------|------|-------------------|
| `DELTA_MAX` | New rolling window max detected | Raw delta peak before filtering |
| `DELTA_MIN` | New rolling window min detected | Raw delta peak before filtering |
| `CANDIDATE_COMPARISON_REJECT` | Peak failed base checks or 3/3 | Why a candidate was rejected |
| `CANDIDATE_GATE_REJECT` | Peak passed comparison but failed a gate | Which gate blocked it and with what values |
| `PEAK_EMIT` | Peak passed everything | Full PEAK payload plus gate values at emit time |

### Events derived offline

| Event | Built from | Script |
|-------|-----------|--------|
| `WINDOW_OWNERSHIP_MISS` | `DELTA_MAX` / `DELTA_MIN` + feed archive | `scripts/offline/build_phase1_derived.py` |
| `EXEC_CLOSE` | Primary: `trade_outcomes.jsonl`; fallback: executor log + state | `scripts/offline/build_close_outcomes.py` |

### Record format

```json
{"schema": 1, "event": "DELTA_MAX", "seq": 42, "ts": "2026-03-16 14:44:00", "kind": "long", "delta": 114.88}
```

- `schema` = format version
- `seq` = monotonic per-session sequence
- `event` = event type name

---

## Feed CSV Schema

```text
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
```

This 10-column schema is the contract actually written by the Aggregator to `/data/feed/aggregated.csv` and `/data/archive/feed/YYYY-MM-DD.csv`.
DeltaScout runtime validation in `deltascout/delta_scout.py` is aligned to this 10-column layout for its live input file.

This repository also documents a separate enriched research contour at `/opt/aitrader/feed/YYYY-MM-DD.csv`.
That contour is read by offline research tooling, but it is not written by the Aggregator code in this repo and it must not be described as the same storage object as `/data/archive/feed/YYYY-MM-DD.csv`.

Important historical recovery note:

- The enriched AiTrader/SHI contour has a known gap from `2026-04-23 17:05:00` through `2026-05-06 22:51:00` UTC caused by Binance Futures WebSocket route migration.
- Do not use the original flat/synthetic rows in that window as real market evidence.
- For the durable recovery contract, paths, and interpretation rules, see [feed_recovery_context_2026_04_23.md](feed_recovery_context_2026_04_23.md).

Known current-state divergence:

- `/data/archive/feed/YYYY-MM-DD.csv` is the archive written by this repo's Aggregator from the same rows it writes into live `aggregated.csv`.
- `/opt/aitrader/feed/YYYY-MM-DD.csv` is treated by research tooling as a separate external feed root.
- Documentation under `deltascout/` already assumes that `/opt/aitrader/feed` may contain enriched columns beyond the 10-column Aggregator archive.
- Therefore research outputs built from `/opt/aitrader/feed` are not strictly the same evidence source as outputs built from `data/archive/feed`.

---

## Notes

This repository is a portfolio and technical showcase demonstrating system design and engineering approach.

For the full research specification, see [DeltaScout_Research_Phase1_Spec.md](DeltaScout_Research_Phase1_Spec.md).
