# DeltaScout Research Phase 1 Specification

## Overview

Phase 1 establishes the **research data infrastructure** for DeltaScout.
It does not modify any trading logic, PEAK emission, gate thresholds, or execution behavior.

The goal is to capture every decision point in the DeltaScout pipeline as structured,
archivable research events — enabling offline analysis, backtesting, and model evaluation
without interfering with live operation.

---

## Research Objective

Identify **high-quality missed opportunities** where DeltaScout rejected a candidate
but price continued in the signalled direction with acceptable adverse excursion.

Specifically, Phase 1 research data must enable answering:

1. **Which rejects were wrong?** — candidates rejected by comparison or gate logic
   that would have been profitable entries.
2. **Which gate is the bottleneck?** — are most near-miss rejects caused by a single
   gate (e.g. CHOP30) or by multiple conditions failing together?
3. **Are there impulse types the 3/3 rule misses?** — strong delta events that never
   become window owners or fail 3/3 despite being directionally correct.
4. **How tight are the gate margins?** — for passed PEAKs, how close were gate values
   to their thresholds? For rejects, how far off?

Without this structured data, the system is a black box — PEAKs appear or don't,
with no visibility into the decision funnel.

---

## Runtime Topology (Confirmed)

```
Binance WS
    │
    ▼
Aggregator
    │  writes: /data/feed/aggregated.csv
    ▼
DeltaScout
    │  reads:  aggregated.csv (tail polling, POLL_SECS=20)
    │  stdout: Δ1m max/min/zero/init_* lines (Docker logs)
    │  writes: /data/logs/deltascout.log (JSONL: PEAK, INIT_MAX, INIT_MIN)
    ├──────────────────┐
    ▼                  ▼
  Buyer            Executor
    │  reads: deltascout.log     │  reads: deltascout.log
    │  writes: CLOSED → deltascout.log (feedback)
    │                            │  writes: /data/logs/executor.log (JSONL)
    │  sends: Telegram via n8n   │  state:  /data/state/executor_state.json
```

### Confirmed file paths

| Artifact           | Default path                        | ENV override       |
|--------------------|-------------------------------------|---------------------|
| Feed CSV           | `/data/feed/aggregated.csv`         | `FEED_DIR`, `FILE_PATH`, `AGG_CSV` |
| DeltaScout log     | `/data/logs/deltascout.log`         | `DELTASCOUT_LOG`    |
| Executor log       | `/data/logs/executor.log`           | `EXEC_LOG`          |
| Executor state     | `/data/state/executor_state.json`   | `STATE_FN`          |
| Buyer state        | `/root/volume-alert/buyer_state.json` | `STATE_FN`        |

> Implementation note: defaults are not fully harmonized across modules (for example,
> Buyer path defaults differ from DeltaScout/Executor defaults). Phase 1 archive
> implementation must use explicit archive path configuration and must not assume
> all services already share identical defaults.

### Confirmed log channels

| Channel               | Mechanism        | Location                        |
|------------------------|------------------|---------------------------------|
| Raw delta events       | `print()` stdout | Docker stdout (`docker logs`)   |
| PEAK signal bus        | JSONL file write | `deltascout.log`                |
| Buyer feedback         | JSONL append     | `deltascout.log` (CLOSED event) |
| Executor actions       | JSONL file write | `executor.log`                  |

---

## Feed Schema (aggregated.csv)

10 columns, strict order, validated on startup:

```
Timestamp, Trades, TotalQty, AvgSize, BuyQty, SellQty, AvgPrice, ClosePrice, HiPrice, LowPrice
```

An external minute-feed archive (`/opt/aitrader/feed/YYYY-MM-DD.csv`) uses the same schema
and can serve as a reference dataset for offline joins. It is **not** part of the
DeltaScout runtime root — see [Runtime Topology Note](#runtime-topology-note).

---

## PEAK Bus Contract (deltascout.log)

### PEAK event (emitted by DeltaScout)

```json
{
  "ts": "2026-03-05 06:36:00",
  "source": "DeltaScout",
  "action": "PEAK",
  "kind": "long|short",
  "delta": -123.45,
  "vol": 144.0,
  "imb": 0.62,
  "price": 72549.0,
  "vwap": 71745,
  "poc": 70190
}
```

### Buyer CLOSED feedback event

```json
{
  "source": "Buyer",
  "action": "CLOSED",
  "ts": "2026-03-05T06:40:00+00:00"
}
```

### Log management

- DeltaScout truncates `deltascout.log` at 500 lines, keeping last 30.
- Executor reads only last `TAIL_LINES` (default 80) from EOF.
- Executor log capped at `LOG_MAX_LINES` (default 200).

---

## Decision Flow Map

The DeltaScout pipeline processes each CSV row through five stages:

### Stage 1 — Feed Ingestion

| Item       | Detail |
|------------|--------|
| Function   | `tail_csv()` (live) / `read_last_rows()` (warmup) |
| File       | `deltascout/delta_scout.py` |
| Lines      | 561-601 (tail_csv), 604-624 (read_last_rows) |
| Output     | `dict` per CSV row, yielded to main loop |

### Stage 2 — Raw Delta Detection

| Item       | Detail |
|------------|--------|
| Function   | `Scout.handle_row()` |
| File       | `deltascout/delta_scout.py` |
| Lines      | 394-425 |
| Logic      | `delta = buy - sell`, rolling window max/min detection |
| Output     | Identifies current row as MAX or MIN owner |

### Stage 3 — Comparison Logic (3/3 Rule)

| Item       | Detail |
|------------|--------|
| Function   | `prev_pass_3of3()` |
| File       | `deltascout/delta_scout.py` |
| Lines      | 168-172 |
| Logic      | Current peak must beat previous on price, volume, AND vwap |
| Rejects    | Same-kind peaks that fail any of the three comparisons |

Additional base checks (lines 456-467 for long, 518-529 for short):
- Direction match with previous peak
- Price must be on correct side of VWAP
- VWAP distance cap (`VWAP_MAX_DIST_USD`)

### Stage 4 — Gate Logic

| Item       | Detail |
|------------|--------|
| Function   | `Scout.handle_row()` (gate section) |
| File       | `deltascout/delta_scout.py` |
| Lines      | 472-478 (long gates), 534-540 (short gates) |
| Gates      | EMA50 position, VWAP position, CHOP30 <= 2.6, COH10 >= 0.30, IMB range |

### Stage 5 — PEAK Emit

| Item       | Detail |
|------------|--------|
| Function   | `Scout._emit_json()` |
| File       | `deltascout/delta_scout.py` |
| Lines      | 202-211 (writer), 482-493 (long PEAK), 544-555 (short PEAK) |
| Output     | JSONL line appended to `deltascout.log` |

### Debug/Stdout Emission

| Item       | Detail |
|------------|--------|
| Function   | `Scout._emit()` |
| File       | `deltascout/delta_scout.py` |
| Lines      | 242-278 |
| Output     | `Δ1m {kind} {sign} @ {ts} | Vol ... | Ib ... | Price ... | VWAP ... POC ...` |
| Mechanism  | `print()` to stdout (captured by Docker) |

---

## Insertion Points for Research Events

The following insertion points are identified for future Phase 1 implementation.
**No code changes are made in Phase 0.**

### DELTA_MAX / DELTA_MIN

- **Location:** `deltascout/delta_scout.py`, lines 441 / 503
- **Context:** Immediately after `self._emit("max", ...)` / `self._emit("min", ...)`
- **Purpose:** Capture every raw delta peak before comparison/gate filtering
- **Safe:** These lines run unconditionally for every new peak owner

### CANDIDATE_COMPARISON_REJECT

- **Location:** `deltascout/delta_scout.py`, lines 456-467 (long) / 518-529 (short)
- **Context:** Each `return` statement after a failed base check or 3/3 comparison
- **Purpose:** Record why a candidate was rejected at the comparison stage
- **Safe:** Each `return` is a terminal exit from the peak branch; a log call before `return` has no side effects

Specific return points:
- Line 457: no previous peak (first peak)
- Line 459: direction mismatch
- Line 461: price wrong side of VWAP
- Line 465: VWAP distance exceeds cap
- Line 467: 3/3 comparison failed

### CANDIDATE_GATE_REJECT

- **Location:** `deltascout/delta_scout.py`, lines 473-478 (long) / 535-540 (short)
- **Context:** Each `return` statement after a failed gate check
- **Purpose:** Record why a candidate passed comparison but was rejected at the gate stage
- **Safe:** Same terminal-return pattern
- **Must include:** all gate values at rejection time (`chop30`, `coh10`, `ema50`, `imb`, `price`, `vwap`) and their thresholds, to enable margin analysis

Specific return points:
- Line 474: EMA50/VWAP position gate
- Line 476: CHOP30 or COH10 gate
- Line 478: IMB range gate

### WINDOW_OWNERSHIP_MISS (derived offline)

`WINDOW_OWNERSHIP_MISS` events are **not emitted at runtime** in Phase 1.
They are derived during offline analysis by comparing `DELTA_MAX`/`DELTA_MIN`
events against rolling window ownership logic reconstructed from the feed archive.

- **Reference code:** `deltascout/delta_scout.py`, lines 437 / 499 (the `if last_ts_max == ts` / `if last_ts_min == ts` conditions)
- **Context:** A row has a strong delta but does NOT become the rolling window max/min owner
- **Purpose:** Capture the "invisible" class of events — strong impulses that never enter the candidate pipeline because the current window already has a stronger extreme
- **Note:** This may be the most interesting event class for research — these signals are currently completely invisible. No runtime insertion point is needed; the mandatory `DELTA_MAX`/`DELTA_MIN` stream plus feed data provide sufficient information for offline reconstruction

---

## Executor Close Event Detection

Executor tracks position lifecycle in its state file and log:

| Event        | Location                        | Detection method |
|-------------|----------------------------------|------------------|
| `CLOSED`     | `executor.py`, lines ~2129-2139 | `pos["status"] = "CLOSED"` written to state and log |
| Close reason | `pos["close_reason"]`           | SL, TP1, TP2, trailing, manual |
| Close price  | `pos["close_price"]`            | Actual exit price |
| Last closed  | `st["last_closed"]`             | Persisted in state for cooldown |

Executor log path: `EXEC_LOG` env var, default `/data/logs/executor.log`.

### Executor close snapshot requirements

Each snapshot in `executor_close/YYYY-MM-DD/<ts>_<trade_key>.log` must be **atomic**
(written as a single complete file, never appended to) and must contain:

| Section          | Content |
|------------------|---------|
| `position_state` | Full position object at close time (entry, exit, side, qty, pnl, close_reason) |
| `triggering_peak`| The PEAK event that opened this position (original JSON from deltascout.log) |
| `executor_tail`  | Last N lines of executor.log at close time (`EXECUTOR_TAIL_LINES` ENV, default 400) |

This enables post-analysis that joins: what signal opened the trade, what happened
during the trade, and how it closed — in a single self-contained artifact.

---

## Phase 1 Research Events (Runtime status + offline scope)

### Smallest safe Patch 1 scope (frozen)

Patch 1 must log only the following additive research events:

- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`

These events are additive research instrumentation only and must not change
PEAK emission, thresholds, gates, cooldown/state logic, or Buyer/Executor contracts.

These events are emitted to a dedicated research archive (not `deltascout.log`) in the
current runtime implementation:

| Event                         | Trigger point                    | Fields (planned) |
|-------------------------------|----------------------------------|-------------------|
| `DELTA_MAX`                   | New rolling window maximum       | ts, delta, vol, imb, price, vwap, poc |
| `DELTA_MIN`                   | New rolling window minimum       | ts, delta, vol, imb, price, vwap, poc |
| `CANDIDATE_COMPARISON_REJECT` | Failed base check or 3/3         | ts, kind, reject_reason, curr, prev *(runtime)* + `reject_class` *(offline-derived)* |
| `CANDIDATE_GATE_REJECT`       | Failed gate check                | ts, kind, reject_reason, gate_values, thresholds *(runtime)* + `reject_class` *(offline-derived)* |
| `WINDOW_OWNERSHIP_MISS`       | Strong delta but not window owner | ts, delta, vol, imb, price, window_max, window_min |
| `PEAK_EMIT`                   | Successful PEAK (mirror)         | Full PEAK payload + gate_values (chop30, coh10, ema50) |
| `EXEC_CLOSE`                  | Position closed *(offline-derived dataset row type)* | ts, reason, entry, exit, pnl, triggering_peak, position_state |

### Patch 1 out of scope

The following are explicitly excluded from the smallest Patch 1:

- Executor runtime emission of `EXEC_CLOSE` (close outcomes are derived offline)
- Runtime `WINDOW_OWNERSHIP_MISS` emission (offline-derived only)
- Buyer/Executor contract changes
- Any PEAK payload or PEAK path change
- Large archive-manager abstraction

### Reject classification

In Phase 1, `reject_reason` is emitted at runtime, while `reject_class` is derived
offline from the emitted reject events and gate/comparison context.

Offline reject datasets should include:

| Field           | Type   | Description |
|-----------------|--------|-------------|
| `reject_reason` | string | Specific check that failed (e.g. `"3of3_vol"`, `"chop30"`, `"vwap_side"`) |
| `reject_class`  | string | One of: `single_condition`, `multi_condition`, `soft_fail` |

Classification rules:
- **`single_condition`** — exactly one check failed, all others passed
- **`multi_condition`** — two or more checks failed simultaneously
- **`soft_fail`** — one condition failed narrowly while other relevant metrics strengthened. These cases are recorded separately because the combined signal structure may still represent a viable trading opportunity. Numeric thresholds for `soft_fail` classification may be refined during offline research and are not fixed in Phase 1

This classification enables filtering for near-miss candidates that are most
likely to represent missed opportunities.

---

## Missed Signal Taxonomy

DeltaScout signals can be missed at multiple structural stages of the pipeline.
The research layer must observe not only accepted signals but also events that
were rejected, never evaluated, or recognized too late.

The following taxonomy maps every category of missed opportunity to the
pipeline stage where it occurs:

```
CSV row arrives
    │
    ├─ delta computed, rolling window updated
    │       │
    │       ├─ NOT window owner ──────────► TYPE 1: WINDOW_OWNER_MISS
    │       │
    │       └─ IS window owner (max or min)
    │               │
    │               ├─ no prev_peak (first) ──► TYPE 2: BASELINE_INITIALIZATION_EVENT
    │               │
    │               ├─ comparison checks
    │               │       │
    │               │       └─ FAIL ──────────► TYPE 3: CANDIDATE_COMPARISON_REJECT
    │               │
    │               ├─ gate checks
    │               │       │
    │               │       └─ FAIL ──────────► TYPE 4: CANDIDATE_GATE_REJECT
    │               │
    │               └─ ALL PASS ──► PEAK emitted
    │                                   │
    │                                   └─ late? ─► TYPE 5: LATE_PEAK_RECOGNITION
```

### Type 1 — WINDOW_OWNER_MISS

**Definition:**
A strong delta event occurred but did not become the rolling window owner
(max or min), therefore it never entered the candidate evaluation pipeline.

**How it happens:**
DeltaScout uses rolling extreme ownership to identify candidate peaks.
If a delta spike occurs but another larger delta already owns the window,
the new event is silently skipped — it is never evaluated by comparison
or gate logic.

**Research value:**
These events may represent valid continuation impulses that are structurally
hidden by the window ownership rule. A second strong impulse in the same
direction is invisible if the first impulse was stronger within the window.
This is potentially the most interesting class of missed signals because
the current pipeline has zero visibility into them.

**Pipeline stage:** Pre-candidate (Stage 2 — Raw Delta Detection)

### Type 2 — BASELINE_INITIALIZATION_EVENT

**Definition:**
An extreme delta event that initializes the `prev_peak` reference but cannot
generate a signal because it is the first peak of its kind (no comparison
baseline exists).

**How it happens:**
After startup, restart, or direction change, the first window owner of a given
kind (`long` or `short`) sets `self.prev_peak = curr` and returns immediately.
No comparison or gate logic runs. The event exists only as a baseline for
future candidates.

**Research value:**
In strong trends, the first impulse after a direction change may actually be
the most valuable signal — it marks the beginning of a new move. The current
system structurally cannot act on it because the 3/3 comparison rule requires
a predecessor.

**Pipeline stage:** Candidate entry (Stage 3 — Comparison Logic, first-peak branch)

### Type 3 — CANDIDATE_COMPARISON_REJECT

**Definition:**
A candidate extreme passed window ownership but failed one or more comparison
rules against `prev_peak`.

**Specific failure reasons:**
- `direction_mismatch` — `curr.kind != prev_peak.kind`
- `vwap_side` — price on wrong side of VWAP for the signal direction
- `vwap_distance` — price too far from VWAP (`VWAP_MAX_DIST_USD` exceeded)
- `3of3_price` — price did not improve vs. previous peak
- `3of3_vol` — volume did not improve vs. previous peak
- `3of3_vwap` — VWAP did not improve vs. previous peak

**Research focus:**
Detect **soft failures** where only one metric regressed but others
strengthened. A candidate that fails on volume alone but shows stronger
delta and better price may still represent a valid opportunity. The
`reject_class` field (`single_condition` / `multi_condition` / `soft_fail`)
enables filtering for these near-miss cases.

**Pipeline stage:** Stage 3 — Comparison Logic

### Type 4 — CANDIDATE_GATE_REJECT

**Definition:**
A candidate passed all comparison logic (including 3/3) but failed one
or more regime gates.

**Specific gates:**
- `ema50_regime` — price not on correct side of EMA50
- `vwap_regime` — price not on correct side of VWAP
- `chop30` — CHOP30 index exceeds threshold (choppy market)
- `coh10` — COH10 coherence below threshold (weak directional flow)
- `imb_band` — imbalance outside acceptable range

**Research focus:**
Identify **single-gate rejects** — candidates where only one gate blocked
the signal. These are the highest-quality missed opportunities because
the candidate passed every other structural check. Gate margin analysis
(how far was the value from the threshold?) reveals whether gates are
calibrated too tightly or if they correctly filter noise.

**Pipeline stage:** Stage 4 — Gate Logic

### Type 5 — LATE_PEAK_RECOGNITION

**Definition:**
The system eventually emits a valid PEAK signal, but only after a significant
portion of the directional move has already occurred.

**How it happens:**
Detection latency can arise from multiple sources:
- The rolling window takes time to establish a new extreme owner
- The 3/3 comparison requires the current peak to exceed the previous one,
  which may only happen after several minutes of price continuation
- Polling interval (`POLL_SECS=20`) adds inherent delay

**Research value:**
A PEAK emitted 5 minutes into a move has lower entry quality than the same
signal detected at the start. Measuring signal timeliness — the gap between
the start of the price move and the PEAK emission timestamp — reveals
whether earlier structural indicators could have triggered detection sooner.

**Note:** This category does not represent a "missed" signal in the strict
sense (the PEAK was emitted). It represents degraded signal quality due to
latency.

**Pipeline stage:** Post-emit analysis (derived metric, not a pipeline rejection)

### Implementation priority

Phase 1 implementation **already logs** a subset of these events in real time:

| Event | Logged at runtime | Rationale |
|-------|:-:|---|
| `DELTA_MAX` / `DELTA_MIN` | yes | Raw peaks — foundation for all analysis |
| `CANDIDATE_COMPARISON_REJECT` | yes | Direct insertion at `return` statements |
| `CANDIDATE_GATE_REJECT` | yes | Direct insertion at `return` statements |
| `PEAK_EMIT` | yes | Runtime mirror event in research archive (side-channel only) |
| `EXEC_CLOSE` | **derived** | Offline-derived close outcome dataset from existing executor artifacts |
| `WINDOW_OWNER_MISS` | **derived** | Computed offline by comparing `DELTA_MAX/MIN` timestamps against feed data |
| `BASELINE_INITIALIZATION_EVENT` | **derived** | Identifiable from `DELTA_MAX/MIN` sequences where no comparison event follows |
| `LATE_PEAK_RECOGNITION` | **derived** | Computed offline by measuring price move before `PEAK_EMIT` timestamp |

Derived events are not logged at runtime to avoid adding complexity to
the hot path. They are reconstructed during offline analysis from the
mandatory event stream.

---

### Research archive layout

Canonical runtime root for Phase 1 archive writes is `/data`.

All research data for Phase 1 lives under:

```
/data/archive/
    deltascout/
        YYYY-MM-DD.jsonl          # decision-level research events
    executor_close/
        YYYY-MM-DD/
            <ts>_<trade_key>.log  # executor state snapshots at close
    datasets/                     # derived / joined datasets
```

This archive is append-only and never read by the live trading system.

### Live bus isolation requirements (mandatory)

- Research archive must use a separate archive file and must not reuse `deltascout.log`.
- Research archive writes must not go through the live-bus truncation logic used for `deltascout.log`.
- Research archive must remain fully isolated from Buyer/Executor PEAK bus consumers.

### Record format

Every research event must include a `schema` version field to support
forward-compatible format evolution:

```json
{
  "schema": 1,
  "event": "DELTA_MAX",
  "seq": 42,
  "ts": "2026-03-05 06:36:00",
  ...
}
```

| Field    | Type | Description |
|----------|------|-------------|
| `schema` | int  | Format version (starts at 1, bumped on breaking changes) |
| `event`  | string | Event type name |
| `seq`    | int  | Monotonic sequence number per session |

### External reference datasets

Market-feed archives under `/opt/aitrader/feed/YYYY-MM-DD.csv` belong to a
separate project/container and are **not** part of the DeltaScout runtime root.
They may be used for offline joins and backfill but must not be assumed
writable or locally available at runtime.

---

## Runtime Topology Note

Current repository/runtime defaults are mixed between `/data/...` and `/root/volume-alert/...`.
For Phase 1 implementation, archive pathing is canonicalized to `/data/archive/...` for
implementation safety.

- Live data and bus defaults in code: `/data/feed`, `/data/logs`, `/data/state`
- Research archive (Phase 1 canonical): `/data/archive/`

Any datasets under `/opt/aitrader` or other containers/projects are
external references only and are not part of the local runtime root.

---

## Constraints

- **No live code changes** in Phase 0
- Research events must be **additive** (new code paths only, no modification of existing logic)
- Research archive must be **isolated** from the live signal bus (`deltascout.log`)
- Research logging must not introduce latency into the hot path
- Archive writes must be **soft-fail**: write errors must never block or alter PEAK emission
- Archive writes must not alter `handle_row()` control flow or state behavior
- All research events must include a monotonic sequence number for ordering

## Dormant Runtime Item Note

`TIER_TP1` exists in code as a helper path, but it is not part of the verified active
runtime emission flow and is not in scope for the smallest Phase 1 patch unless explicitly wired later.
