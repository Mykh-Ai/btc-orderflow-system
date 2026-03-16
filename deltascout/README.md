# DeltaScout

Order-flow signal detection module with research instrumentation.

Monitors the aggregated trade feed (`aggregated.csv`) produced by the Aggregator,
processes each minute row through a five-stage decision pipeline,
and emits JSONL events for downstream consumers (Buyer, Executor)
and a separate research archive for offline analysis.

## Pipeline stages

```
CSV row → Delta Detection → Comparison (3/3 rule) → Gate Logic → PEAK Emit
              │                    │                      │           │
          DELTA_MAX/MIN    COMPARISON_REJECT      GATE_REJECT    PEAK_EMIT
          (archive)            (archive)            (archive)    (archive + live bus)
```

1. **Feed Ingestion** — tail-poll `aggregated.csv`, yield dict per row
2. **Raw Delta Detection** — compute `delta = buy - sell`, track rolling window max/min
3. **Comparison Logic (3/3 rule)** — current peak must beat previous on price, volume, AND vwap
4. **Gate Logic** — regime filters: EMA50 position, VWAP position, CHOP30, COH10, IMB range
5. **PEAK Emit** — write JSONL to live signal bus + mirror to research archive

## Outputs

### Live signal bus

`deltascout.log` (configured via `DELTASCOUT_LOG`) — JSONL consumed by Buyer and Executor.
Truncated at 500 lines (keeps last 30). Contains `PEAK`, `INIT_MAX`, `INIT_MIN` events.

### Research archive

`/data/archive/deltascout/YYYY-MM-DD.jsonl` (configured via `RESEARCH_ARCHIVE_DIR`) —
append-only daily JSONL capturing every decision point in the pipeline.

Events recorded at runtime:

| Event | Trigger | Fields |
|-------|---------|--------|
| `DELTA_MAX` | New rolling window maximum | ts, delta, vol, imb, price, vwap, poc |
| `DELTA_MIN` | New rolling window minimum | ts, delta, vol, imb, price, vwap, poc |
| `CANDIDATE_COMPARISON_REJECT` | Failed base check or 3/3 | ts, kind, reject_reason, curr/prev values |
| `CANDIDATE_GATE_REJECT` | Failed gate check | ts, kind, reject_reason, gate_values, thresholds |
| `PEAK_EMIT` | Successful PEAK (mirror) | Full PEAK payload + gate values (chop30, coh10, ema50) |

Record format:
```json
{"schema": 1, "event": "DELTA_MAX", "seq": 42, "ts": "2026-03-16 14:44:00", ...}
```

- `schema` — format version (integer, starts at 1)
- `seq` — monotonic sequence number per session
- `event` — event type name

### Isolation

- Research archive is a **separate file** from `deltascout.log`
- Research writes do not use live-bus truncation logic
- Write errors are soft-fail — never block or alter PEAK emission
- Archive files are never read by live trading components

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FILE_PATH` | `/data/feed/aggregated.csv` | Input CSV path |
| `DELTASCOUT_LOG` | `/data/logs/deltascout.log` | Live signal bus output |
| `RESEARCH_ARCHIVE_DIR` | `/data/archive/deltascout` | Research archive directory |
| `POLL_SECS` | `20` | Feed poll interval (seconds) |
| `ROLL_WINDOW_MIN` | `180` | Rolling window size (minutes) |
| `STARTUP_LOOKBACK_MIN` | `1500` | Warmup lookback rows |
| `WEBHOOK_URL` | — | Optional debug webhook endpoint |

Gate/threshold parameters: `CHOP30_MAX`, `COH10_MIN`, `IMB_LONG_MIN`, `IMB_LONG_MAX`,
`IMB_SHORT_MIN`, `IMB_SHORT_MAX`, `VWAP_MAX_DIST_USD`, etc. See `.env.example`.

## Run

```bash
pip install pandas numpy
python -u delta_scout.py
```

Or via Docker (see `docker-compose.yml` in project root).

## Tests

```bash
pytest deltascout/test/ -v
```
