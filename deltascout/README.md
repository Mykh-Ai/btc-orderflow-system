# DeltaScout

Order-flow signal detection module with research instrumentation.

DeltaScout monitors the aggregated trade feed (`aggregated.csv`) produced by the Aggregator, processes each minute row through a five-stage decision pipeline, emits PEAK signals for downstream consumers, and writes additive research events to a separate archive.

## Pipeline

```text
CSV row -> Delta Detection -> Comparison (3/3 rule) -> Gate Logic -> Optional PEAK admission -> PEAK Emit
```

1. **Feed ingestion**: tail-poll `aggregated.csv`, yield one row at a time
2. **Raw delta detection**: compute `delta = buy - sell`, track rolling window max and min
3. **Comparison logic**: current peak must beat previous on price, volume, and VWAP
4. **Gate logic**: EMA50 regime, VWAP regime, CHOP30, COH10, IMB band
5. **Optional PEAK admission**: evaluate the loss-avoidance rule in `off`, `shadow`, or `veto` mode
6. **PEAK emit**: write admitted JSONL to the live signal bus and mirror `PEAK_EMIT` to the research archive

The loss-avoidance rule is PEAK-only. It never applies to `ALMOST_PEAK_2_OF_3`. It combines:

- component A: same-side 24-hour peak percentile `<= 50`;
- component B: trusted `oi_change_60m < 0` and directional `delta_pct_240m < 0.06`;
- union decision: A or B.

Missing, stale, synthetic, duplicated, or incomplete feature inputs fail open. `shadow` records the decision but preserves the original PEAK bus behavior. `veto` may suppress a PEAK only after its audit record was written successfully; five consecutive would-block decisions open a circuit breaker and restore PEAK emission.

---

## Storage

### Feed inputs

| What | Path | Description |
|------|------|-------------|
| Live feed | `/data/feed/aggregated.csv` | Rolling feed used by DeltaScout during runtime |
| External research feed contour | `/opt/aitrader/feed/YYYY-MM-DD.csv` | Separate external research contour used by current offline/analyzer workflows |
| Local Aggregator archive contour | `/data/archive/feed/YYYY-MM-DD.csv` | Local Aggregator archive contour written by this repository |

The two daily archive paths above are not one feed with two aliases. They are two different market-data contours used by different parts of the current system documentation and workflow.

Observed current-state split:

- `/data/archive/feed/YYYY-MM-DD.csv` is written by this repository's Aggregator and follows the 10-column Aggregator contract.
- `/opt/aitrader/feed/YYYY-MM-DD.csv` is not written by code in this repository, but current offline research flows explicitly read it.
- `DeltaScout` runtime itself reads the live rolling file `FILE_PATH` (default `/data/feed/aggregated.csv`), not either daily archive path directly.
- `Buyer` and `Executor` also stay on the live path (`AGG_CSV` default under `/data/feed`) and on the PEAK bus; they do not consume either daily archive contour directly.

The research workflow therefore has a real path/source split. This documentation keeps that split explicit for market-state research.

Enriched CSV schema documented for the external `/opt/aitrader/feed` contour:

```text
Timestamp,Open,High,Low,Close,Volume,AggTrades,BuyQty,SellQty,VWAP,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty,IsSynthetic
```

### Live signal output

| What | Path | Description |
|------|------|-------------|
| Live signal bus | `/data/logs/deltascout.log` | JSONL bus for Buyer and Executor. Truncated at 500 rows, keeping the last 30 |

Example PEAK:

```json
{"ts":"2026-03-16 19:09:00","source":"DeltaScout","action":"PEAK","kind":"long","delta":114.88,"vol":195.12,"imb":0.589,"price":74148.10,"vwap":73398,"poc":73980}
```

### Research storage

| What | Path | Description |
|------|------|-------------|
| Decision archive | `/data/archive/deltascout/YYYY-MM-DD.jsonl` | Append-only research archive for DeltaScout runtime events |
| Trade outcomes journal | `/data/state/trade_outcomes.jsonl` | Canonical append-only raw journal of closed trade outcomes written by Executor |
| Derived datasets | `/data/archive/datasets/` | Offline-built datasets for research analysis |

---

## Research Events

The decision archive stores additive runtime events from DeltaScout:

| Event | Purpose |
|-------|---------|
| `DELTA_MAX` | New rolling window maximum before filtering |
| `DELTA_MIN` | New rolling window minimum before filtering |
| `CANDIDATE_COMPARISON_REJECT` | Candidate failed base checks or 3/3 comparison |
| `CANDIDATE_GATE_REJECT` | Candidate passed comparison but failed a gate |
| `PEAK_EMIT` | Mirrored successful PEAK event with gate context |
| `PEAK_LOSS_FILTER_DECISION` | Audited PEAK admission decision in shadow/veto mode |
| `PEAK_LOSS_FILTER_REJECT` | Vetoed PEAK, including its full counterfactual PEAK payload for replay |

Example record:

```json
{"schema":1,"event":"CANDIDATE_GATE_REJECT","seq":15,"ts":"2026-03-16 15:40:00","kind":"short","reject_reason":"chop30","gate_values":{"chop30":2.8,"coh10":0.35},"thresholds":{"chop30_max":2.6}}
```

Every record includes:

- `schema`: archive schema version
- `event`: event type
- `seq`: monotonic session sequence
- `ts`: event timestamp

---

## Trade Outcomes Journal

Executor writes raw close outcomes to:

```text
/data/state/trade_outcomes.jsonl
```

This is not a derived dataset. It is the canonical operational journal for closed trade outcomes.

Properties:

- append-only JSONL
- one line per closure episode
- contains top-level metadata such as `schema`, `event`, `ts`, `symbol`, `source`
- includes nested `last_closed` snapshot with close-path details

Typical `last_closed` fields may include:

- `ts`, `mode`, `reason`, `pos_status`
- `trade_key`, `order_id`, `side`, `qty`
- `entry`, `entry_ref`, `entry_actual`
- `opened_at`
- `order_id_sl`, `order_id_tp1`, `order_id_tp2`
- `qty1`, `qty2`, `qty3`
- `tp1_done`, `tp2_done`, `sl_done`
- `trail_active`, `trail_sl_price`
- `prices`

`build_close_outcomes.py` uses `trade_outcomes.jsonl` as the primary source and falls back to `executor.log + executor_state.json:last_closed` only when needed.

---

## Derived Datasets

Offline builders write derived datasets to:

```text
/data/archive/datasets/
```

Typical outputs:

- `close_outcomes_YYYY-MM-DD.parquet|csv`
- `reject_dataset_YYYY-MM-DD.parquet|csv`
- `baseline_init_YYYY-MM-DD.parquet|csv`
- `window_owner_miss_YYYY-MM-DD.parquet|csv`
- `late_peak_YYYY-MM-DD.parquet|csv`
- `events_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/accepted_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_reason_summary_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/daily_review_summary_YYYY-MM-DD.md`

Builders:

| Dataset area | Source | Builder |
|--------------|--------|---------|
| Rejects, baseline init, ownership misses, late peaks | DeltaScout archive + enriched feed | `scripts/offline/build_phase1_derived.py` |
| Close outcomes | Primary: `trade_outcomes.jsonl`; fallback: executor artifacts | `scripts/offline/build_close_outcomes.py` |
| Events context CSV | DeltaScout archive + enriched feed | `deltascout.delta_analyzer.cli` (main mode with `--date`) |
| Daily review package | Prebuilt `events_context`, `close_outcomes`, Phase 1 CSVs | `deltascout.delta_analyzer.cli --build-review` |

---

## Data Contracts

### Feed archive contract

Default self-contained path:

```text
INPUT_ROOT/feed/YYYY-MM-DD.csv
```

Properties of the self-contained/default offline feed contract (`INPUT_ROOT/feed/YYYY-MM-DD.csv` or `/data/archive/feed/YYYY-MM-DD.csv` when copied there):

- append-only
- one file per UTC day
- deduplicated by `Timestamp`
- same 10-column schema as `aggregated.csv` when sourced from the local Aggregator archive contour
- chronologically ordered
- builder normalization uses `Timestamp -> ts` (UTC), `BuyQty - SellQty -> delta`, and `ClosePrice` with row-level `AvgPrice` fallback -> `price`

Current research workflow also uses a separate external contour at `/opt/aitrader/feed/YYYY-MM-DD.csv`. In current docs and commands this contour may include columns that do not exist in the local 10-column archive.

Rules:

- `Timestamp` is unique within a file
- `Timestamp` is minute-aligned
- rows are strictly increasing in time
- files are treated as immutable after day close

### Research decision archive contract

Path:

```text
/data/archive/deltascout/YYYY-MM-DD.jsonl
```

Properties:

- append-only
- never truncated
- one JSON object per event
- events written in runtime order

Supported runtime events:

```text
DELTA_MAX
DELTA_MIN
CANDIDATE_COMPARISON_REJECT
CANDIDATE_GATE_REJECT
PEAK_LOSS_FILTER_DECISION
PEAK_LOSS_FILTER_REJECT
PEAK_EMIT
```

### Research isolation

- research archive is separate from `deltascout.log`
- Buyer and Executor do not consume the research archive
- archive writes must not interfere with PEAK emission
- archive is write-only for runtime and read-only for analysis

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FILE_PATH` | `/data/feed/aggregated.csv` | Input CSV path |
| `DELTASCOUT_LOG` | `/data/logs/deltascout.log` | Live signal bus output |
| `RESEARCH_ARCHIVE_DIR` | `/data/archive/deltascout` | Research archive directory |
| `POLL_SECS` | `20` | Feed poll interval |
| `ROLL_WINDOW_MIN` | `180` | Rolling ownership window in minutes |
| `STARTUP_LOOKBACK_MIN` | `1500` | Warmup rows |
| `WEBHOOK_URL` | unset | Optional debug webhook |
| `LOSS_FILTER_MODE` | `off` | Admission mode: `off`, `shadow`, or `veto` |
| `LOSS_FILTER_ENRICHED_FEED_DIR` | `/opt/aitrader/feed` | Daily enriched feed used for cutoff-safe OI/delta features |
| `LOSS_FILTER_STATE_PATH` | `/data/state/deltascout/loss_filter_state.json` | Atomic same-side peak history state |
| `LOSS_FILTER_RESEARCH_ARCHIVE_DIR` | `/data/archive/deltascout` | Canonical `DELTA_MAX/MIN` archive used to rebuild the runtime cache on startup |
| `LOSS_FILTER_RULE_ID` | `DS_PEAK_LOSS_AVOIDANCE_UNION_V1` | Pinned policy identifier; mismatch fails open |
| `LOSS_FILTER_SOURCE_TIMEZONE` | `Europe/Bratislava` | Timezone of legacy DeltaScout timestamps |
| `LOSS_FILTER_ENRICHED_TIMEZONE` | `UTC` | Timezone of enriched daily feed timestamps |
| `LOSS_FILTER_EVAL_BUDGET_MS` | `500` | Maximum evaluation budget before fail-open |

Gate parameters include `CHOP30_MAX`, `COH10_MIN`, `IMB_MIN`, `IMB_MAX`, and `VWAP_MAX_DIST_USD`.

---

## Phase 1 Workflow

### 1. Accumulate runtime data

The system automatically accumulates:

```text
/opt/aitrader/feed/YYYY-MM-DD.csv        # enriched feed (canonical)
/data/archive/deltascout/YYYY-MM-DD.jsonl # DeltaScout decision archive
/data/state/trade_outcomes.jsonl          # closed trade outcomes
```

No manual action is required during collection.

### 2. Rebuild datasets after a trade close

In routine operation this is handled by the post-close watcher / cron flow. For a manual rebuild of the UTC close date, run the four steps in order:

```bash
# Step 1 — Phase 1 derived datasets (rejects, baseline, ownership misses, late peaks)
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python \
  scripts/offline/build_phase1_derived.py \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data \
  --output-root /root/volume-alert/data/archive/datasets \
  --feed-root /opt/aitrader/feed

# Step 2 — Close outcomes join
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python \
  scripts/offline/build_close_outcomes.py \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data \
  --output-root /root/volume-alert/data/archive/datasets \
  --trade-outcomes-file /root/volume-alert/data/state/trade_outcomes.jsonl

# Step 3 — Build events_context CSV from archive + enriched feed
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python \
  -m deltascout.delta_analyzer.cli \
  --archive-glob "/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl" \
  --feed-glob "/opt/aitrader/feed/YYYY-MM-DD.csv" \
  --date YYYY-MM-DD \
  --output-root /root/volume-alert/data/archive/datasets

# Step 4 — Daily review package from prebuilt datasets
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python \
  -m deltascout.delta_analyzer.cli \
  --build-review \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data/archive/datasets \
  --output-root /root/volume-alert/data/archive/datasets
```

**Feed resolution.** `build_phase1_derived` resolves feed input in this order:

1. `--feed-file` explicit file override (highest priority)
2. `--feed-root/YYYY-MM-DD.csv` — external research feed root, often `/opt/aitrader/feed/` in current server workflow
3. self-contained `--input-root/feed/YYYY-MM-DD.csv` (fallback)

In current server research workflow, `--feed-root /opt/aitrader/feed` is used intentionally as a different market-data contour from `/data/archive/feed`. Current docs assume it may expose enriched columns such as `OpenInterest`, `FundingRate`, `LiqBuyQty`, and `LiqSellQty`. Step 3 reads that same external contour via `--feed-glob`. This is a real current-state divergence, not just an alternate spelling for the local Aggregator archive.

Expected outputs:

- `reject_dataset_YYYY-MM-DD.*`
- `baseline_init_YYYY-MM-DD.*`
- `window_owner_miss_YYYY-MM-DD.*`
- `late_peak_YYYY-MM-DD.*`
- `close_outcomes_YYYY-MM-DD.*`
- `events_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/accepted_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_reason_summary_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/daily_review_summary_YYYY-MM-DD.md`

### 3. Validate outputs

For example:

```bash
ls /data/archive/datasets
head -n 20 /data/archive/datasets/close_outcomes_YYYY-MM-DD.csv
```

If `join_status = missing`, it means the corresponding `PEAK_EMIT` was not found in the DeltaScout research archive for the requested join logic.

---

## Research Roadmap

### Phase 1: Foundation / base derived layer

Goal:

- accumulate feed archive
- accumulate DeltaScout decision archive
- build the base derived datasets used for reject and close-outcome research

### Phase 2: Backward-looking event context ✓ Complete

- `events_context` per-event context layer
- cumulative delta and return context around archive events
- deterministic research surface for later review and outcome joins

### Phase 2.5: Daily review package ✓ Complete, in production

- accepted and reject review tables built from `events_context`
- reject reason summary for the day
- deterministic daily review summary for repeated research use
- automated daily via post-close watcher cron at 06:10 server time

Later phases remain research-facing and should be defined from accumulated evidence rather than assumed in advance.

---

## Run

```bash
pip install pandas numpy
python -u deltascout/delta_scout.py
```

## Tests

```bash
pytest tests/ deltascout/test/ -v
```
