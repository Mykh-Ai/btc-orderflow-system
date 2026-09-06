# DeltaScout Scout Replay Backtester Specification v0.1

## Document Status

- Status: implementation-ready technical specification
- Version: `0.1`
- Date: `2026-08-20`
- Owner area: DeltaScout research layer
- Runtime impact: none
- Deployment authorization: none
- Primary branch: `research`

This document defines an offline, deterministic backtester for DeltaScout candidate
events. It is a research instrument, not a live trading component and not evidence of
market edge by itself.

---

## 1. Decision

Build a new research-side component named **Scout Replay Backtester** inside this
repository.

The implementation may reuse selected, audited ideas from the legacy AI Trader
`backtester/` package, especially:

- chronological replay;
- explicit same-bar policies;
- event ledger materialization;
- metrics and drawdown artifacts;
- experiment manifests;
- cost and robustness hooks.

The new backtester must not import the AI Trader repository as a runtime dependency.
The legacy AI Trader engine is not sufficient as-is because it models a single stop
and single target and does not reproduce the current Executor V1.5 lifecycle.

The execution policy must be based on the live behavior in `executor/executor.py`, not
on its simplified paper-position path.

---

## 2. Problem Statement

Current outcome analysis is selection-biased toward events that passed the full
DeltaScout funnel and became `PEAK_EMIT` signals. It cannot answer what would have
happened to:

- candidates that nearly passed the `3of3` comparison;
- `direction_mismatch` or `vwap_side` rejects;
- gate rejects;
- later signals blocked because Executor already had an open position;
- signals matched by new offline/shadow hypotheses;
- alternative candidate groups that were recorded but never traded.

Manual forward reconstruction is slow, inconsistent, and unsuitable for testing
hundreds of archived candidates. A deterministic replay layer is required to compare
candidate groups under one execution contract.

---

## 3. Research Questions

The backtester must make the following questions answerable:

1. How do archived `PEAK_EMIT` signals perform under a replay of the current Executor
   lifecycle?
2. How do `almost PEAK` candidates perform under the same execution policy?
3. Which reject classes contain useful independent opportunities?
4. Which candidate classes mostly produce plain stops, scratches, or protected wins?
5. How often does the one-position rule block a later signal with a better outcome?
6. What is the opportunity cost of production position locking and cooldown?
7. Do proposed shadow filters reduce plain stops without removing `TP1 + TP2` winners?
8. Does a result survive commissions, slippage assumptions, and same-bar ambiguity?

---

## 4. Success Definition

The MVP is successful when it can take an explicit archived candidate cohort and a
date range and produce:

- deterministic per-candidate execution results;
- Executor-compatible lifecycle classes;
- independent-opportunity and production-portfolio views;
- gross and net fixed-notional PnL;
- normalized R as a separate diagnostic metric;
- candidate-group summaries;
- position-lock opportunity-cost evidence;
- a parity report against available real Executor outcomes;
- a complete manifest of data, configuration, assumptions, and code version.

No live threshold, signal, order, or position-sizing change is part of success.

---

## 5. Scope

### 5.1 MVP in scope

- Offline replay of archived DeltaScout terminal candidate events.
- Candidate groups defined from existing event fields.
- One-minute chronological market replay.
- Long and short symmetry.
- Executor entry, initial-stop, TP1, TP2, breakeven, and trailing lifecycle.
- Fixed-notional position sizing and exchange-compatible quantity/tick rounding.
- Commission and optional slippage models.
- Conservative handling of unknown intrabar event order.
- `independent_opportunity` replay mode.
- `executor_portfolio` replay mode with one-position locking and cooldown.
- Comparison against canonical operational outcomes where artifacts exist.
- Research artifacts under `deltascout/research_material/backtests/`.

### 5.2 Explicitly out of scope for MVP

- Rerunning DeltaScout detection to generate historical events that were never archived.
- Changing DeltaScout runtime thresholds.
- Running old AI Trader Analyzer v1 campaigns.
- Enabling the AI Trader backtester as an active validation gate.
- Calling Binance or any other exchange API.
- Live, paper, or remote order placement.
- LLM verdict generation or model retraining.
- Parameter optimization over a large threshold grid.
- Claiming a profitable strategy or market edge.
- Server deployment.

### 5.3 Important boundary: candidate replay versus detector replay

The MVP is a **candidate outcome replay**. It starts from candidate events already
present in the research archive.

It can test `PEAK_EMIT`, `3of3_fail 2/3`, other rejects, and shadow labels that can be
derived from archived pre-entry fields. It cannot discover an unrecorded delta event
created by a hypothetical lower runtime threshold.

A future **full Scout detector replay** may regenerate DeltaScout events from raw feed
under alternate detection rules. That is a separate phase and must not be silently
claimed by the MVP.

---

## 6. Repository Placement

Recommended implementation layout:

```text
deltascout/
  research_bundle/
    scout_backtester/
      __init__.py
      cli.py
      candidate_compiler.py
      contracts.py
      execution_policy.py
      replay_engine.py
      fill_models.py
      cost_models.py
      same_bar_policies.py
      ledger.py
      metrics.py
      parity.py
      reports.py
      manifests.py

tests/
  offline/
    scout_backtester/
      test_candidate_compiler.py
      test_execution_policy.py
      test_replay_engine.py
      test_same_bar_policies.py
      test_cost_models.py
      test_portfolio_lock.py
      test_parity.py

deltascout/research_material/
  backtests/
    <experiment_id>/
      ...generated artifacts...
```

The package must remain offline and isolated from the live signal bus and Executor
state files.

---

## 7. Source Systems and Reuse Policy

### 7.1 AI Trader legacy backtester

Reference source:

```text
D:\Project_V\Aitrader\backtester\
```

Allowed reuse after audit:

- interfaces and deterministic event-ledger patterns;
- same-bar policy hook design;
- cost-model hook design;
- metrics and robustness concepts;
- experiment registry and manifest concepts.

Must not be reused unchanged:

- old Analyzer artifact contracts;
- single-target replay state machine;
- assumptions about one-position behavior;
- old candidate/ruleset generators;
- any campaign tied to failed Analyzer v1 outputs.

Any copied code must be moved into the current repository, reduced to the new contract,
covered by local tests, and attributed in implementation notes where appropriate.

### 7.2 Executor

Reference source:

```text
executor/executor.py
```

The backtester must reproduce the economic and lifecycle semantics of the live V1.5
path:

- `build_entry_price`;
- `notional_to_qty`;
- `swing_stop_far`;
- `compute_tps`;
- quantity split from `validate_exit_plan` / `place_exits_v15`;
- TP1 then stop-to-breakeven behavior;
- TP2 then fractal trailing behavior;
- single-position admission behavior;
- cooldown behavior.

The backtester must not import `executor.py` directly because that module includes
environment access, state writes, logging, exchange adapters, and live side effects.

For MVP, implement a versioned pure policy named:

```text
EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2
```

Longer term, shared pure functions may be extracted into a side-effect-free module
used by both Executor and the backtester, but that refactor is production-adjacent and
requires separate authorization and parity evidence.

---

## 8. Input Contracts

### 8.1 Candidate source

Primary local source:

```text
deltascout/research_material/reviews/YYYY-MM-DD/events_context_YYYY-MM-DD.csv
```

Candidate compilation may also use the underlying research archive when a required
field is missing from review tables, but one canonical normalized candidate table must
be produced before replay.

Minimum normalized candidate schema:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `candidate_id` | string | yes | Stable deterministic identifier |
| `source_event_ts_local` | datetime | yes | Original DeltaScout local timestamp |
| `signal_ts_utc` | datetime | yes | Normalized cutoff timestamp |
| `side` | enum | yes | `LONG` or `SHORT` |
| `event_type` | string | yes | Terminal archive event type |
| `candidate_group` | string | yes | Versioned research cohort |
| `reject_reason` | string/null | yes | Original terminal rejection |
| `signal_price` | float | yes | Candidate price from event |
| `delta` | float | yes | Event delta |
| `volume` | float | yes | Event volume |
| `imbalance` | float/null | no | Event imbalance |
| `vwap` | float/null | no | Event VWAP |
| `poc` | float/null | no | Event POC |
| `comparison_3of3_pass_count` | int/null | no | Comparison pass count |
| `comparison_3of3_failed_subconditions` | string/null | no | Failed comparison fields |
| `shadow_flags` | object | yes | Versioned offline labels |
| `source_path` | string | yes | Provenance |
| `source_row_hash` | string | yes | Stable content hash |

### 8.2 Candidate timestamp contract

Legacy DeltaScout review timestamps are Europe/Bratislava local-naive timestamps.
Effective feed timestamps are UTC-naive timestamps.

The candidate compiler must:

1. interpret `source_event_ts_local` in `Europe/Bratislava`;
2. convert it to an aware UTC timestamp;
3. persist both values;
4. use only feed rows available at or after the normalized cutoff for forward replay;
5. fail loudly on ambiguous or unparseable timestamps.

The corrected timestamp boundary already used by current commonality analysis is the
required reference behavior.

### 8.3 Market feed

Primary replay source:

```text
deltascout/research_material/effective_feed/YYYY-MM-DD.csv
```

Required columns:

```text
Timestamp,Open,High,Low,Close,Volume,BuyQty,SellQty,IsSynthetic
```

Optional research/context columns:

```text
AggTrades,VWAP,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty
```

Execution replay must use OHLC and must not infer intrabar ordering that the one-minute
feed cannot prove.

### 8.4 Recovery and quality contract

Known enriched-feed quality gap:

```text
2026-04-23 17:05:00 UTC through 2026-05-06 22:51:00 UTC
```

Rules:

- Never use original flat/synthetic rows in this interval as market evidence.
- Use `effective_feed` backed by recovered output.
- Join the recovery quality sidecar.
- Price/volume/delta replay may proceed where recovered rows are available.
- Funding/liquidation claims must be marked degraded or unavailable.
- Every trade row must include `feed_quality_class` and `recovery_overlap`.
- A run must report counts of real, recovered, synthetic, missing, and degraded rows.

### 8.5 Operational outcome sources for parity

Use, in priority order:

1. `deltascout/research_material/server_state/trade_execution_snapshots.jsonl`;
2. `deltascout/research_material/server_state/trade_pnl_ledger.csv`;
3. `deltascout/research_material/server_state/trade_outcomes.jsonl`;
4. user-confirmed outcome ledger rows where canonical execution evidence is absent.

Operator test trades must remain excluded from scoring and parity rates.

---

## 9. Candidate Group Contract v0.1

Candidate groups must be deterministic, versioned, and mutually auditable. One event
may carry multiple diagnostic labels, but it must have one primary candidate group per
experiment.

Required initial groups:

| Group | Definition |
|---|---|
| `PEAK_EMIT_BASELINE` | `event_type == PEAK_EMIT` |
| `ALMOST_PEAK_2_OF_3` | comparison reject with `3of3_fail` and pass count `2` |
| `ALMOST_PEAK_1_OF_3` | comparison reject with `3of3_fail` and pass count `1` |
| `DIRECTION_MISMATCH_REJECT` | comparison reject with `direction_mismatch` |
| `VWAP_SIDE_REJECT` | comparison reject with `vwap_side` |
| `GATE_REJECT` | terminal `CANDIDATE_GATE_REJECT` |
| `OTHER_COMPARISON_REJECT` | remaining terminal comparison rejects |

Required shadow labels:

```text
weak_peak_le_50
oi_down_60_and_directional_delta_pct_240_lt_0_06
loss_avoidance_conservative_union
```

Shadow labels are annotations, not candidate admission rules, unless an experiment
explicitly defines a cohort from them.

### 9.1 Candidate deduplication

The compiler must deduplicate terminal decision rows by a stable key containing at
least:

```text
normalized UTC minute + side + terminal event type + signal price at configured precision
```

Raw `DELTA_MAX` / `DELTA_MIN` rows must not be replayed as additional trades when a
terminal decision for the same candidate exists.

All dropped duplicates must be written to a candidate-quality artifact with the reason.

---

## 10. Replay Modes

### 10.1 `independent_opportunity`

Every normalized candidate is replayed independently from the same historical feed.

Properties:

- no position lock;
- no capital competition;
- no suppression by another candidate;
- no portfolio drawdown claim;
- suitable for measuring the standalone outcome distribution of candidate groups.

This mode answers: **What would this signal have done if it had been tradable?**

### 10.2 `executor_portfolio`

Candidates are processed chronologically under Executor-like admission state.

Required rules:

- one active or pending position at a time;
- no pyramiding;
- later candidates while locked are recorded, not discarded;
- after a close, apply the configured cooldown;
- preserve deterministic tie-breaking for multiple candidates at the same timestamp;
- blocked candidates retain their independent-opportunity result through a join.

This mode answers: **What would the current bot have executed?**

Required blocked reasons:

```text
POSITION_ALREADY_OPEN
POSITION_PENDING_ENTRY
COOLDOWN_ACTIVE
DUPLICATE_CANDIDATE
INVALID_CANDIDATE
NO_FEED_COVERAGE
```

### 10.3 Opportunity-cost join

For every candidate blocked in `executor_portfolio`, join its
`independent_opportunity` result and report:

- blocked candidate lifecycle;
- blocked candidate gross/net PnL;
- active trade lifecycle and net PnL;
- entry improvement in USD and percent where comparable;
- normalized R difference;
- fixed-notional PnL difference;
- whether the blocked candidate reached TP1 or TP2;
- whether replacing or allowing the candidate would have improved economic outcome.

This join must preserve the difference between better risk geometry and larger actual
dollar profit.

---

## 11. Execution Policy Contract

### 11.1 Versioned defaults

`EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2` defaults:

| Parameter | Default | Source semantics |
|---|---:|---|
| `symbol` | `BTCUSDC` | Executor default |
| `fixed_notional_usdc` | `3000` for research baseline | Explicit experiment config; actual Executor value may differ by period |
| `tick_size` | `0.01` | Executor default |
| `qty_step` | `0.00001` | Executor default |
| `entry_offset_usd` | `0.5` | Executor default |
| `entry_expiry_bars` | `2` | Deterministic one-minute approximation of the live 90-second entry timeout |
| `sl_pct` | `0.002` | Executor default |
| `swing_lookback_minutes` | `180` | Executor `SWING_MINS` |
| `tp_r_multipliers` | `[1, 2]` | Executor default |
| `cooldown_seconds` | `180` | Executor default |
| `trail_swing_lookback` | `240` rows | Executor default |
| `trail_swing_lr` | `2` | Executor default |
| `trail_swing_buffer_usd` | `50` | Executor default |
| `trail_step_usd` | `20` | Executor default |
| `trail_confirm_buffer_usd` | `0` | Executor default |
| `sl_limit_gap_ticks` | `2` | Executor default |

Every run must materialize the resolved values in `run_manifest.json`; no important
execution parameter may remain an implicit environment default.

### 11.2 Price-reference contract

DeltaScout research feed and Executor execution may use different price contours
(`BTCUSDT`-like signal/reference data versus `BTCUSDC` execution). The live Executor
uses a conversion factor where available.

MVP must expose:

```text
price_reference_model_id
signal_price_symbol
replay_feed_symbol
execution_symbol
conversion_model_id
```

Deterministic dual-feed baseline:

```text
CONTEMPORANEOUS_BTCUSDC_SPOT_TO_BTCUSDT_REFERENCE_CLOSE_RATIO_V0_1
```

The candidate signal and swing stop are planned in USDT on the signal/reference
contour. At the signal cutoff, one frozen ratio is calculated from the exact-minute
BTCUSDC Spot close divided by the exact-minute BTCUSDT reference close. Entry, stop,
TP1, and TP2 are converted once and directionally tick-rounded before fill replay.
The ratio, both source closes, and cutoff timestamp must be persisted. BTCUSDC Spot
OHLC is then the only contour allowed to trigger fills, stops, targets, and trailing
events. Signal-feed volume, OI, delta, or Futures-only wicks must never enter lifecycle
execution. The close ratio is an explicit one-minute proxy for live bookTicker, not a
claim of exact exchange planning parity.

### 11.3 Planned entry

For a candidate signal price `P`:

- long raw entry: `P + entry_offset_usd`;
- short raw entry: `P - entry_offset_usd`;
- apply the same directional tick rounding as Executor.

The run must persist both `planned_entry_price` and simulated `entry_fill_price`.

### 11.4 Entry fill model

One-minute data cannot reproduce the exact exchange order book or a 90-second live
timeout. Fill behavior must therefore be explicit and versioned.

Baseline model:

```text
MARKETABLE_LIMIT_NEXT_BAR_V0_1
```

Rules:

- The event minute is cutoff context; earliest activation is the next feed bar.
- Long buy limit:
  - if next/open price is at or below the limit, fill at `min(open, limit)`;
  - otherwise fill at the limit only when a subsequent bar low reaches it.
- Short sell limit:
  - if next/open price is at or above the limit, fill at `max(open, limit)`;
  - otherwise fill at the limit only when a subsequent bar high reaches it.
- Entry order expiry is a configurable bar count and must be written to the manifest.
- Default MVP `entry_expiry_bars=2` is the declared one-minute approximation of the
  live 90-second timeout. Parity calibration may test other named variants, but it may
  not silently replace the baseline.
- Plan-B market fallback is a separate fill-model variant, not part of the initial
  baseline unless explicitly configured.

Guarded Plan-B variant:

```text
LIMIT_THEN_MARKET_90S_GUARDED_V0_1
```

Rules:

- The first complete post-signal minute is the LIMIT-touch window.
- If no LIMIT fill occurs, the open of the second complete post-signal minute is the
  deterministic 90-second executable-price proxy.
- A missing or synthetic required bar is `NO_FEED_COVERAGE`.
- The MARKET fallback is rejected when `abs(proxy - planned_entry) > 0.25R` with
  `R = abs(planned_entry - initial_stop)`; an explicit positive absolute threshold
  may raise the maximum in the same way as Executor `PLANB_MAX_DEV_USD`.
- After the deviation check, the fallback is rejected when the proxy is past TP1 in
  the trade direction.
- Otherwise the entry fills at the proxy open and is labeled `PLANB_MARKET`.
- The ledger must persist fill method, decision, abort reason, proxy price,
  deviation, maximum deviation, and risk.
- This is a deterministic OHLC approximation. It does not reconstruct bid/ask,
  partial fills, cancel races, cancel-confirmation polling, or market slippage.

The fill model must never use a future close to improve the fill.

### 11.5 Fixed-notional quantity

```text
raw_qty = fixed_notional_usdc / entry_fill_price
qty = floor(raw_qty / qty_step) * qty_step
```

The trade must be rejected with an explicit reason if quantity or notional fails the
configured exchange minimum.

### 11.6 Initial stop

Reproduce `swing_stop_far` using data available at the signal cutoff only.

For long:

```text
pct_stop = entry * (1 - sl_pct)
swing_stop = minimum replay reference close over prior swing_lookback_minutes
initial_stop = min(pct_stop, swing_stop)
```

For short:

```text
pct_stop = entry * (1 + sl_pct)
swing_stop = maximum replay reference close over prior swing_lookback_minutes
initial_stop = max(pct_stop, swing_stop)
```

Apply Executor-compatible directional tick rounding and enforce that the stop remains
on the correct side of entry.

The baseline uses historical `Close`, matching Executor's `ClosePrice` swing input,
not candle high/low.

### 11.7 Targets

```text
risk_usd = abs(entry - initial_stop)
TP1 = entry +/- 1 * risk_usd
TP2 = entry +/- 2 * risk_usd
```

Apply Executor-compatible directional rounding.

### 11.8 Quantity split

Split quantity in integer `qty_step` units:

- first third to TP1;
- second third to TP2;
- remainder to the trailing leg;
- if either of the first two legs rounds to zero, degrade to two 50/50 legs and set
  trailing quantity to zero, matching Executor fallback semantics.

### 11.9 Position lifecycle

Required state machine:

```text
SIGNAL
  -> ENTRY_PENDING
  -> OPEN
      -> PLAIN_SL
      -> TP1_DONE
          -> stop remaining quantity at breakeven
          -> TP1_SL_SCRATCH
          -> TP2_DONE
              -> TRAILING_ACTIVE
              -> TRAILING_STOP_CLOSE
```

Required lifecycle labels:

```text
NO_FILL
PLAIN_SL
TP1_SL
TP1_TP2_TRAILING_STOP
TP1_TP2_OPEN_TRAIL
UNRESOLVED_END_OF_DATA
INVALID_EXECUTION_PLAN
```

Close reason `SL` must not be used as the economic outcome label by itself.

### 11.10 TP1 and breakeven

When TP1 is reached:

- realize leg 1 at TP1;
- set `tp1_done=true`;
- replace the remaining stop with `entry_fill_price`, directionally tick-aligned;
- apply the replacement no earlier than allowed by the configured same-bar policy;
- retain TP2 for leg 2.

### 11.11 TP2 and trailing activation

When TP2 is reached:

- realize leg 2 at TP2;
- set `tp2_done=true`;
- activate trailing for leg 3 if its quantity is greater than zero;
- do not use information after the current closed bar to calculate the first trail;
- the newly computed trailing stop becomes executable on the next bar.

### 11.12 Fractal trailing

Reproduce the pure market-data meaning of Executor trailing:

- use the most recent confirmed fractal swing from the BTCUSDT reference feed;
- long uses `LowPrice` and a fractal low minus `trail_swing_buffer_usd`;
- short uses `HiPrice` and a fractal high plus `trail_swing_buffer_usd`;
- use BTCUSDT `ClosePrice` only for the post-activation confirmation break;
- fractal left/right width is `trail_swing_lr`;
- a swing is confirmed only after the required right-hand bars exist;
- calculate a contemporaneous historical proxy
  `k_trail = BTCUSDC execution close / BTCUSDT reference close` for every trail
  activation or update, and reject the quote outside `[0.95, 1.05]`;
- convert the buffered USDT stop with `k_trail`, round outward, and validate it
  against the current BTCUSDC execution close before changing the active stop;
- after activation, update only when the converted BTCUSDC stop improves by at
  least `trail_step_usd`, and never loosen an active trailing stop;
- activate an updated stop on the following bar to prevent look-ahead.

Missing exact-minute reference/execution alignment or an invalid conversion retains
the existing protective stop. Every applied update must audit the source swing,
source USDT stop, converted stop, ratio, both reference closes, and quote timestamp.

Exchange cancel/replace failures are not modeled in the baseline economic replay. A
future execution-stress variant may model delayed trail updates.

### 11.13 End of data

Open trades at the end of feed coverage must remain `UNRESOLVED_END_OF_DATA` unless an
experiment explicitly selects a forced-close model.

The baseline must not invent a final close at the last price.

---

## 12. Same-Bar Ambiguity

One-minute OHLC proves which levels were touched but not their order.

Required policy interface:

```text
same_bar_policy_id
resolve(state_before, bar, active_levels) -> ordered outcome
```

Required MVP policies:

### 12.1 `CONSERVATIVE_STOP_FIRST_V0_1`

- If the active stop and next profit target are both touched in one bar, stop wins.
- If TP1 is touched and the initial stop is not touched but the bar also crosses
  breakeven, classify conservatively as `TP1_SL` after TP1.
- If TP1 and TP2 are both touched without the active stop being touched, both targets
  may fill in price-order sequence; trailing begins next bar.
- If a trailing stop and a higher target concept collide, only the active trailing
  stop matters because no further fixed target remains after TP2.

### 12.2 `TARGET_FIRST_SENSITIVITY_V0_1`

An optimistic sensitivity run that resolves target before stop. It must never be the
only reported result.

### 12.3 Ambiguity reporting

Every trade must include:

```text
same_bar_ambiguous
same_bar_collision_count
same_bar_policy_id
outcome_changes_under_sensitivity
```

Results that materially depend on same-bar ordering must be isolated in summaries.

---

## 13. Cost Model

### 13.1 Baseline commission

Initial model:

```text
COMMISSION_TURNOVER_RATE_V0_1
```

Required fields:

```text
commission_rate
commission_calibration_source
commission_calibration_count
commission_usdc
```

Current research reference is approximately `0.0744%` of total entry-plus-exit
turnover, calibrated from actual overlapping execution fills. The exact resolved rate
must be regenerated from the available local ledger at run time or pinned explicitly
in the experiment configuration.

### 13.2 Slippage

Required variants:

- `ZERO_SLIPPAGE_DIAGNOSTIC`;
- `FIXED_BPS_ADVERSE` with configurable entry and exit bps;
- optional separate stop slippage stress.

Zero slippage may be used for parity diagnostics but must not be presented as the only
economic result.

### 13.3 Borrow interest

Historical borrow interest is currently unavailable for many execution snapshots.

Rules:

- persist `borrow_interest_usdc=null` when unavailable;
- persist `net_pnl_scope=after_commission_before_borrow_interest`;
- do not silently treat unknown borrow interest as observed zero;
- add a later stress model if sufficient evidence becomes available.

### 13.4 Economic calculations

For each realized leg:

```text
long_gross = qty * (exit - entry)
short_gross = qty * (entry - exit)
```

Trade totals:

```text
gross_pnl_usdc = sum(realized_leg_gross)
commission_usdc = commission_model(total_turnover)
slippage_usdc = cost_model(...)
net_pnl_usdc = gross_pnl_usdc - commission_usdc - slippage_usdc
```

Normalized R must be reported separately from fixed-notional USDC. Ranking by R must
not be substituted for ranking by dollar PnL.

---

## 14. Outcome Utility Contract

Required research utility buckets:

| Utility bucket | Lifecycle | Interpretation |
|---|---|---|
| `LOSS_TARGET` | `PLAIN_SL` | Main loss-avoidance target |
| `SCRATCH_NEUTRAL` | `TP1_SL` | Practical-zero attempt, even if fees create a small net loss |
| `PROTECTED_WINNER` | `TP1_TP2_TRAILING_STOP` | Main cohort that admission filters should preserve |
| `UNRESOLVED` | no final result | Excluded from resolved outcome rates |
| `NO_TRADE` | no fill/blocked/invalid | Reported separately |

The utility contract must be configurable only through a versioned policy. Reports
must not collapse all `SL` close reasons into one loss class.

---

## 15. Output Artifacts

Each experiment writes to:

```text
deltascout/research_material/backtests/<experiment_id>/
```

Required artifacts:

### 15.1 `run_manifest.json`

- experiment id and description;
- code git commit or explicit `dirty` state;
- input paths, sizes, hashes, and date range;
- candidate contract version;
- execution policy version and all resolved parameters;
- fill, cost, same-bar, conversion, and quality policy ids;
- generation timestamp;
- excluded trades/candidates;
- deterministic run fingerprint.

### 15.2 `normalized_candidates.csv`

One row per compiled candidate, including all provenance and group fields.

### 15.3 `candidate_quality.csv`

Dropped duplicates, invalid rows, missing timestamps, missing feed coverage, and data
quality exclusions.

### 15.4 `replay_events.jsonl`

Append-style chronological state-transition ledger. Required event examples:

```text
CANDIDATE_SEEN
CANDIDATE_BLOCKED
ENTRY_PENDING
ENTRY_FILLED
ENTRY_EXPIRED
INITIAL_SL_SET
TP1_FILLED
SL_MOVED_TO_BE
TP2_FILLED
TRAIL_ACTIVATED
TRAIL_UPDATED
STOP_FILLED
POSITION_CLOSED
RUN_ENDED_UNRESOLVED
```

### 15.5 `independent_trades.csv`

One row per independently replayed candidate.

### 15.6 `portfolio_trades.csv`

One row per candidate under the one-position production policy, including blocked rows.

### 15.7 `position_lock_opportunity_cost.csv`

Blocked candidate result joined to the active trade result.

### 15.8 `candidate_group_metrics.csv`

Metrics by candidate group, side, session, feed quality, and shadow-label status.

### 15.9 `equity_curve.csv` and `drawdown.csv`

Only for `executor_portfolio`, where position competition and trade ordering are real
within the replay contract.

### 15.10 `parity_report.csv`

Per-real-trade comparison between replay and canonical execution evidence.

### 15.11 `summary.md`

Human-readable result with:

- scope and contracts;
- cohort counts;
- lifecycle distribution;
- gross/net results;
- same-bar sensitivity;
- recovery/data-quality coverage;
- position-lock opportunity cost;
- parity quality;
- explicit limitations;
- no live-promotion claim.

---

## 16. Minimum Trade-Ledger Schema

Required fields include:

```text
trade_id
candidate_id
experiment_id
replay_mode
candidate_group
side
signal_ts_utc
entry_status
entry_fill_ts
planned_entry_price
entry_fill_price
fixed_notional_usdc
qty_total
qty1
qty2
qty3
initial_stop_price
initial_risk_usd
tp1_price
tp2_price
tp1_fill_ts
tp2_fill_ts
breakeven_stop_price
trail_activation_ts
trail_update_count
final_stop_price
exit_ts
lifecycle_class
utility_bucket
gross_pnl_usdc
commission_usdc
slippage_usdc
borrow_interest_usdc
net_pnl_usdc
net_pnl_scope
position_r
same_bar_ambiguous
same_bar_policy_id
feed_quality_class
recovery_overlap
blocked_reason
active_trade_id_when_blocked
source_path
run_fingerprint
```

Leg-level fills must be preserved either as normalized JSON columns or, preferably, a
separate `trade_legs.csv` keyed by `trade_id`.

---

## 17. Metrics

Required per cohort:

- total candidates;
- valid execution plans;
- entry fill rate;
- no-fill rate;
- resolved and unresolved counts;
- `PLAIN_SL` count/rate;
- `TP1_SL` count/rate;
- `TP1_TP2_TRAILING_STOP` count/rate;
- utility-bucket distribution;
- gross and net PnL sum;
- mean and median net PnL;
- expectancy per filled trade;
- win rate under both strict-net and utility definitions;
- profit factor where defined;
- average and median R;
- average holding time;
- same-bar ambiguous share;
- result sensitivity to same-bar and cost model;
- long/short split;
- session split;
- recovered/degraded feed split.

Required portfolio-only metrics:

- chronological equity curve;
- max drawdown;
- concurrent signal pressure;
- position-lock blocked count;
- blocked TP1 and TP2 opportunity count;
- net opportunity cost versus independent replay;
- cases where a later blocked trade outperformed the active trade;
- cases where normalized R ranking disagreed with fixed-notional PnL ranking.

Small denominators must always be displayed. No percentage may be shown without its
count and denominator.

---

## 18. Determinism and Look-Ahead Safety

Mandatory rules:

- Sort feed and candidates chronologically with stable secondary keys.
- Use only pre-signal rows for entry-plan features and initial stop.
- Earliest entry is the next bar under the baseline model.
- Confirm fractals only after right-side bars exist.
- Apply new trailing stops no earlier than the next bar.
- Never use final trade outcome to create candidate or execution features.
- Never choose thresholds based on the same outcome during the replay run.
- Persist all policies and parameters.
- Same input hashes plus the same code and configuration must produce identical output
  hashes.
- Randomized robustness, if later added, must use and persist an explicit seed.

The engine must fail loudly on non-monotonic timestamps, duplicate feed minutes that
cannot be resolved deterministically, missing required columns, or untrusted synthetic
rows used without an explicit quality policy.

---

## 19. Validation and Parity

### 19.1 Synthetic state-machine tests

Required deterministic fixtures:

1. long plain stop;
2. short plain stop;
3. long TP1 then breakeven stop;
4. short TP1 then breakeven stop;
5. long TP1, TP2, multiple trail updates, trailing stop;
6. short TP1, TP2, multiple trail updates, trailing stop;
7. TP and stop in the same bar;
8. TP1 and TP2 in the same bar;
9. entry never fills;
10. end-of-data unresolved trade;
11. quantity split rounding fallback;
12. two candidates competing under one-position mode;
13. candidate during cooldown;
14. trailing fractal confirmation without future leakage.

All synthetic lifecycle expectations must pass exactly.

### 19.2 Real Executor parity

For all eligible non-test execution snapshots:

- reconstruct the candidate and replay plan;
- compare planned entry, initial stop, TP1, TP2, quantity split, lifecycle, and PnL;
- separate planning parity from exchange-fill parity;
- explain known differences caused by symbol conversion, exact order timing, spread,
  slippage, cancel/replace latency, or minute-bar ambiguity.

Parity dimensions:

```text
candidate_join_status
entry_plan_match
stop_plan_difference_usd
tp1_difference_usd
tp2_difference_usd
qty_difference
lifecycle_match
gross_pnl_difference_usdc
net_pnl_difference_usdc
mismatch_reason
```

### 19.3 Validation thresholds

MVP implementation status requires:

- 100% passing synthetic state-machine tests;
- a generated parity report for all eligible available snapshots;
- zero unexplained long/short sign inversions;
- zero unexplained `PLAIN_SL` versus `TP1_TP2` lifecycle inversions;
- every mismatch explicitly classified.

`EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2` may be marked parity-validated only when:

- at least 90% of comparable real snapshots match lifecycle class; and
- no protected winner is replayed as a plain stop without an understood, documented
  data-resolution or execution-model reason.

Failure to meet this threshold does not justify tuning results; it requires a parity
audit.

---

## 20. Experiment Discipline

Each experiment must declare one primary question before running.

Examples:

```text
Does ALMOST_PEAK_2_OF_3 produce fewer plain stops than PEAK_EMIT_BASELINE?

Does the loss_avoidance_conservative_union reduce PLAIN_SL while preserving
TP1_TP2_TRAILING_STOP?

How much net opportunity cost is caused by one-position locking?
```

Rules:

- Keep a baseline cohort in every comparative experiment.
- Limit threshold variants per experiment.
- Report all tested variants, including negative results.
- Do not select only the best historical threshold in the headline.
- Separate discovery range from validation range.
- Do not use recovered/degraded evidence without visible labeling.
- Promotion decisions remain outside the backtester.

Recommended first temporal split after parity:

- discovery: earliest reliable date through a declared cutoff;
- validation: later untouched dates;
- prospective shadow: all new candidates after implementation date.

The exact split must be placed in the experiment manifest, not hard-coded globally.

---

## 21. CLI Contract

Proposed command:

```powershell
python -m deltascout.research_bundle.scout_backtester.cli `
  --candidate-root deltascout/research_material/reviews `
  --feed-root deltascout/research_material/effective_feed `
  --execution-feed-root deltascout/research_material/execution_feed/btcusdc_spot_1m/daily `
  --quality-sidecar-root deltascout/research_material/recovery_reports `
  --date-from 2026-03-20 `
  --date-to 2026-08-20 `
  --candidate-groups PEAK_EMIT_BASELINE,ALMOST_PEAK_2_OF_3 `
  --execution-policy EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2 `
  --fill-model MARKETABLE_LIMIT_NEXT_BAR_V0_1 `
  --same-bar-policy CONSERVATIVE_STOP_FIRST_V0_1 `
  --cost-model COMMISSION_TURNOVER_RATE_V0_1 `
  --replay-modes independent_opportunity,executor_portfolio `
  --experiment-id scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v1
```

CLI requirements:

- reject an existing non-empty experiment directory unless `--resume` is explicitly
  supported and proven safe;
- never overwrite source artifacts;
- return non-zero on contract or quality failure;
- print only concise scope and output paths;
- write detailed evidence to the experiment directory.

---

## 22. Implementation Stages

### Stage A — contracts and candidate compiler

- Define typed candidate/feed/config/trade contracts.
- Compile and deduplicate terminal candidate rows.
- Normalize Bratislava-local timestamps to UTC.
- Build candidate-quality reporting.
- Add candidate cohort tests.

Deliverable: normalized candidate artifact without trade simulation.

### Stage B — pure Executor policy

- Implement rounding, planned entry, quantity, initial stop, targets, and quantity split.
- Pin all default parameters in a versioned configuration.
- Add unit tests against explicit Executor examples.

Deliverable: deterministic execution plans.

### Stage C — independent lifecycle replay

- Implement fill model and position state machine.
- Add TP1/BE, TP2, fractal trailing, end-of-data, and same-bar policies.
- Add event and trade ledgers.

Deliverable: `independent_trades.csv` plus replay events.

### Stage D — cost and utility layer

- Add commission/slippage hooks.
- Compute fixed-notional gross/net PnL and R separately.
- Apply lifecycle-aware utility buckets.
- Add cohort metrics.

Deliverable: economically interpretable independent results.

### Stage E — portfolio and opportunity cost

- Add one-position state, pending entry, cooldown, and deterministic blocking.
- Join blocked candidates to independent outcomes.
- Add equity, drawdown, and opportunity-cost artifacts.

Deliverable: production-policy comparison.

### Stage F — parity and first research run

- Join real execution snapshots and outcomes.
- Generate parity report and resolve mismatches.
- Run baseline `PEAK_EMIT` versus `ALMOST_PEAK_2_OF_3` experiment.
- Write a research review without changing live logic.

Deliverable: parity evidence and first candidate comparison.

---

## 23. Acceptance Criteria

The implementation is accepted only when all items below are true:

### Contracts

- [ ] Candidate, feed, execution, fill, cost, same-bar, and output schemas are versioned.
- [ ] Local-to-UTC timestamp conversion is tested.
- [ ] Candidate deduplication is deterministic and audited.
- [ ] Feed recovery quality is visible per trade and per run.

### Execution

- [ ] Long and short initial plans reproduce Executor formulas.
- [ ] Quantity rounding and three-leg split reproduce Executor semantics.
- [ ] TP1 moves the remaining stop to breakeven.
- [ ] TP2 activates a no-look-ahead fractal trail for the third leg.
- [ ] Trailing stops only improve and activate on the next eligible bar.
- [ ] Same-bar collisions are policy-controlled and reported.

### Replay modes

- [ ] Independent mode returns an outcome for every valid candidate with feed coverage.
- [ ] Portfolio mode enforces one position and cooldown.
- [ ] Blocked signals remain in the ledger with explicit reasons.
- [ ] Blocked signals are joined to their independent opportunity outcomes.

### Economics

- [ ] Fixed-notional gross and net USDC are reported.
- [ ] R remains separate from dollar PnL.
- [ ] Commissions are included under a declared model.
- [ ] Unknown borrow interest is not presented as observed zero.
- [ ] `TP1_SL` remains a scratch-neutral utility class.

### Evidence

- [ ] Synthetic tests pass exactly.
- [ ] Real-execution parity report is generated.
- [ ] Every parity mismatch is classified.
- [ ] Same inputs/configuration produce the same run fingerprint and outputs.
- [ ] Summary shows counts and denominators for every rate.

### Safety

- [ ] The backtester never imports or calls exchange-order functions.
- [ ] The backtester never writes to live signal, state, feed, or execution paths.
- [ ] No server deployment or live policy change is included.
- [ ] Generated conclusions are labeled research/shadow evidence.

---

## 24. Initial Research Run

After parity validation, run exactly this first comparison:

```text
Baseline: PEAK_EMIT_BASELINE
Candidate: ALMOST_PEAK_2_OF_3
Modes: independent_opportunity + executor_portfolio
Execution: EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2
Same-bar: conservative baseline + target-first sensitivity
Economics: fixed 3000 USDC notional + commission + slippage stress
Date range: maximum reliable locally available range
```

Primary output questions:

1. How many `ALMOST_PEAK_2_OF_3` entries fill?
2. What share end as plain SL, TP1 scratch, and TP1+TP2 protected?
3. What is net expectancy after commission?
4. How sensitive are results to same-bar ordering and slippage?
5. How many were blocked by an existing position?
6. Did any blocked candidate outperform the active trade in fixed-notional USDC?
7. Does the loss-avoidance shadow rule separate bad candidates while preserving
   protected winners in both cohorts?

No broader reject class should be added to the headline experiment until this baseline
comparison and parity review are complete.

---

## 25. Known Risks

### One-minute intrabar ambiguity

Mitigation: conservative baseline, sensitivity policy, ambiguity flags.

### Signal/reference symbol versus execution symbol

Mitigation: separate feed roles, exact-cutoff persisted conversion evidence, official
BTCUSDC Spot execution OHLC, and parity report; no hidden 1:1 assumption.

### Live entry timeout cannot be reproduced exactly

Mitigation: versioned bar-based fill models and plan-B variants.

### Trailing order-management latency

Mitigation: baseline economic trail uses next-bar activation; future stress can add
delayed updates.

### Historical feed gap

Mitigation: effective recovered feed plus provenance sidecars and degraded-field rules.

### Threshold overfitting

Mitigation: small variant budgets, discovery/validation separation, prospective shadow.

### Selection bias remains for unarchived events

Mitigation: document that MVP replays archived candidates only; detector replay is a
later phase.

### Cross-repository drift

Mitigation: no runtime dependency on AI Trader; copy only audited generic patterns into
the current repository.

### Executor drift

Mitigation: versioned replay policy, configuration snapshots, parity fixtures, and a
future explicit upgrade process when live Executor semantics change.

---

## 26. Future Phases

Not authorized by this specification, but anticipated:

1. Full DeltaScout detector replay from raw minute feed under alternate detection
   thresholds.
2. Higher-frequency BTCUSDT/BTCUSDC bookTicker conversion evidence for tighter live
   planning parity than the current exact-minute close proxy.
3. Exchange microstructure and partial-fill model.
4. Delayed cancel/replace and stop-limit non-fill stress.
5. Borrow-interest model.
6. Batch LLM judge overlay for candidate cohorts.
7. Walk-forward threshold calibration.
8. Formal promotion gate from research to shadow runtime logging.
9. Shared pure execution-policy module used by both live Executor and replay after
   separate production-adjacent approval.

---

## 27. Definition of Done

Scout Replay Backtester v0.1 is done when:

- the package and tests exist in the current repository;
- the candidate compiler handles `PEAK_EMIT` and `ALMOST_PEAK_2_OF_3`;
- independent and portfolio modes both run deterministically;
- live V1.5 lifecycle semantics are represented through TP1, TP2, and trailing close;
- fixed-notional net PnL includes declared execution costs;
- real-trade parity is measured and documented;
- the first baseline-versus-almost-PEAK experiment is generated;
- all output artifacts include provenance and policy versions;
- no live code, server state, or trading behavior has been changed.

Completion of this specification authorizes local research implementation only. It
does not authorize deployment, live filtering, Executor refactoring, or strategy
promotion.
