# DeltaScout

Order-flow signal detection module with research instrumentation.

DeltaScout monitors the aggregated trade feed (`aggregated.csv`) produced by the Aggregator, processes each minute row through a five-stage decision pipeline, emits PEAK signals for downstream consumers, and writes additive research events to a separate archive.

## Pipeline

```text
CSV row -> Delta Detection -> Comparison (3/3 rule) -> Gate Logic -> PEAK Emit
```

1. **Feed ingestion**: tail-poll `aggregated.csv`, yield one row at a time
2. **Raw delta detection**: compute `delta = buy - sell`, track rolling window max and min
3. **Comparison logic**: current peak must beat previous on price, volume, and VWAP
4. **Gate logic**: EMA50 regime, VWAP regime, CHOP30, COH10, IMB band
5. **PEAK emit**: write JSONL to the live signal bus and mirror `PEAK_EMIT` to the research archive

---

## Storage

### Feed inputs

| What | Path | Description |
|------|------|-------------|
| Live feed | `/data/feed/aggregated.csv` | Rolling feed used by DeltaScout during runtime |
| Feed archive | `/data/archive/feed/YYYY-MM-DD.csv` | Append-only historical minute archive used for research |

CSV schema:

```text
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
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

Builders:

| Dataset area | Source | Script |
|--------------|--------|--------|
| Rejects, baseline init, ownership misses, late peaks | DeltaScout archive + feed archive | `scripts/offline/build_phase1_derived.py` |
| Close outcomes | Primary: `trade_outcomes.jsonl`; fallback: executor artifacts | `scripts/offline/build_close_outcomes.py` |

---

## Data Contracts

### Feed archive contract

Path:

```text
/data/archive/feed/YYYY-MM-DD.csv
```

Properties:

- append-only
- one file per UTC day
- deduplicated by `Timestamp`
- same schema as `aggregated.csv`
- chronologically ordered

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

Gate parameters include `CHOP30_MAX`, `COH10_MIN`, `IMB_MIN`, `IMB_MAX`, and `VWAP_MAX_DIST_USD`.

---

## Phase 1 Workflow

### 1. Accumulate runtime data

The system automatically accumulates:

```text
/data/archive/feed/YYYY-MM-DD.csv
/data/archive/deltascout/YYYY-MM-DD.jsonl
/data/state/trade_outcomes.jsonl
```

No manual action is required during collection.

### 2. Rebuild datasets after a trade close

Run the offline builders for the UTC close date:

```bash
python scripts/offline/build_phase1_derived.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
python scripts/offline/build_close_outcomes.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
```

Expected outputs:

- `reject_dataset_YYYY-MM-DD.*`
- `baseline_init_YYYY-MM-DD.*`
- `window_owner_miss_YYYY-MM-DD.*`
- `late_peak_YYYY-MM-DD.*`
- `close_outcomes_YYYY-MM-DD.*`

### 3. Validate outputs

For example:

```bash
ls /data/archive/datasets
head -n 20 /data/archive/datasets/close_outcomes_YYYY-MM-DD.csv
```

If `join_status = missing`, it means the corresponding `PEAK_EMIT` was not found in the DeltaScout research archive for the requested join logic.

---

## Research Roadmap

### Phase 1: Data accumulation

Goal:

- accumulate feed archive
- accumulate DeltaScout decision archive
- build baseline derived datasets

### Phase 2: Signal research

Typical directions:

- signal density maps
- profitability by delta bucket
- profitability by regime
- reject signal analysis
- threshold sensitivity

Future dataset registry:

```text
/data/archive/datasets/manifest.json
```

This should track dataset metadata such as name, file, build time, source date range, row count, and builder script.

### Phase 3: Strategy modeling

Potential directions:

- adaptive thresholds
- regime-specific signals
- multi-factor signal scoring

### Phase 4: Production strategy

After statistical validation, new signal logic may be promoted into the live trading system.

---

## Run

```bash
pip install pandas numpy
python -u delta_scout.py
```

## Tests

```bash
pytest deltascout/test/ -v
```
