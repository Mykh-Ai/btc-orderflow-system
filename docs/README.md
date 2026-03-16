## Execution-first Order-Flow Analytics Stack for Binance Spot
(VPS • Docker • n8n • Telegram • Binance Spot)

End-to-end **market data → analytics → alerts → execution** stack deployed on a VPS.

**Pipeline:** Binance WS → Aggregator → DeltaScout → Buyer / Executor → Telegram / Binance API

> **Disclaimer:** Educational/engineering project. **Not financial advice.**

---

## Components

| Module | Path | What it does |
|--------|------|--------------|
| **Aggregator** | `aggregator/` | Connects to Binance WS, aggregates trades into 1-minute CSV rows |
| **DeltaScout** | `deltascout/` | Reads CSV feed, detects delta peaks, emits PEAK signals |
| **Buyer** | `buyer/` | Reacts to PEAK signals, sends Telegram alerts via n8n |
| **Executor** | `executor/` | Reacts to PEAK signals, manages positions on Binance Spot API |
| **Offline scripts** | `scripts/offline/` | Builds derived research datasets from archived data |

---

## What writes where

### Aggregator writes

| What | Path (container) | Path (host) | Format | Behaviour |
|------|-------------------|-------------|--------|-----------|
| Live feed | `/app/feed/aggregated.csv` | `data/feed/aggregated.csv` | CSV, 10 columns | Rolling 1500 rows (oldest dropped) |
| **Feed archive** | `/data/archive/feed/YYYY-MM-DD.csv` | `data/archive/feed/YYYY-MM-DD.csv` | CSV, 10 columns | Append-only, one file per day, dedup by Timestamp |

Every minute the Aggregator writes one row to the live feed **and** appends the same row to the daily archive.
The live feed is a sliding window for DeltaScout. The archive is permanent storage for research.

### DeltaScout writes

| What | Path (container) | Path (host) | Format | Behaviour |
|------|-------------------|-------------|--------|-----------|
| **PEAK signals** | `/data/logs/deltascout.log` | `data/logs/deltascout.log` | JSONL | Live bus for Buyer/Executor. Truncated at 500 rows |
| **Research archive** | `/data/archive/deltascout/YYYY-MM-DD.jsonl` | `data/archive/deltascout/YYYY-MM-DD.jsonl` | JSONL | Append-only, one file per day. Never truncated |

### Executor writes

| What | Path (container) | Path (host) | Format |
|------|-------------------|-------------|--------|
| Action log | `/data/logs/executor.log` | `data/logs/executor.log` | JSONL |
| State | `/data/state/executor_state.json` | `data/state/executor_state.json` | JSON |

---

## PEAK signal lifecycle

```
Aggregator                DeltaScout                    Buyer / Executor
    │                         │                              │
    │  aggregated.csv row     │                              │
    ├────────────────────────►│                              │
    │                         │  delta detection             │
    │                         │  comparison (3/3 rule)       │
    │                         │  gate checks                 │
    │                         │         │                    │
    │                         │    PASS │ FAIL               │
    │                         │         │                    │
    │                         │    ┌────┴────┐               │
    │                         │    │ PEAK    │ reject event  │
    │                         │    │ signal  │ → research    │
    │                         │    └────┬────┘   archive     │
    │                         │         │                    │
    │                         │  deltascout.log (JSONL)      │
    │                         ├────────────────────────────►│
    │                         │                         reads PEAK,
    │                         │  research archive       opens position
    │                         │  (PEAK_EMIT mirror)     or sends alert
    │                         │                              │
```

**PEAK** is the core signal. It means DeltaScout detected a delta extreme that passed all checks:
- Rolling window ownership (strongest delta in the window)
- 3/3 comparison rule (beats previous peak on price, volume, AND vwap)
- Gate filters (EMA50, VWAP position, CHOP30, COH10, IMB range)

Each PEAK is written to `deltascout.log` (live bus) and mirrored as `PEAK_EMIT` to the research archive.

---

## Research archive

The research archive captures every decision point in the DeltaScout pipeline.
It is **separate** from the live signal bus and is never read by trading components.

### Events recorded at runtime

| Event | When | What it tells you |
|-------|------|-------------------|
| `DELTA_MAX` | New rolling window max detected | Raw delta peak before any filtering |
| `DELTA_MIN` | New rolling window min detected | Raw delta peak before any filtering |
| `CANDIDATE_COMPARISON_REJECT` | Peak failed base check or 3/3 rule | Why a candidate was rejected (reason: `no_prev_peak`, `direction_mismatch`, `vwap_side`, `vwap_distance`, `3of3_fail`) |
| `CANDIDATE_GATE_REJECT` | Peak passed comparison but failed a gate | Which gate blocked it (reason: `ema50_regime`, `vwap_regime`, `chop30`, `coh10`, `imb_band`) + all gate values |
| `PEAK_EMIT` | Peak passed everything | Full PEAK payload + gate values at emission time |

### Events derived offline

| Event | Built from | Script |
|-------|-----------|--------|
| `WINDOW_OWNERSHIP_MISS` | DELTA_MAX/MIN + feed archive | `scripts/offline/build_phase1_derived.py` |
| `EXEC_CLOSE` | Executor log + state | `scripts/offline/build_close_outcomes.py` |

### Record format

```json
{"schema": 1, "event": "DELTA_MAX", "seq": 42, "ts": "2026-03-16 14:44:00", "kind": "long", "delta": 114.88, ...}
```

`schema` — format version, `seq` — monotonic counter per session, `event` — type name.

---

## Feed CSV schema

```
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
```

Used by both live feed and feed archive (identical format).

---

## Notes

This repository is a **portfolio and technical showcase** demonstrating system design and engineering approach.

For the full research specification, see [DeltaScout_Research_Phase1_Spec.md](DeltaScout_Research_Phase1_Spec.md).
