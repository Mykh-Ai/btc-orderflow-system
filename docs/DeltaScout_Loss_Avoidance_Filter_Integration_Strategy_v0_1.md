# DeltaScout Loss-Avoidance Filter Integration Strategy v0.1

Status: WP1-WP4 implemented and verified locally. By explicit operator
authorization, the VPS DeltaScout was deployed directly in `veto` mode on
2026-08-20. Prospective validation remains in progress.

Date: 2026-08-20

Operational rollout record:

- VPS backup: `/root/volume-alert/backups/deltascout_loss_filter_20260820T1720Z`;
- active mode: `LOSS_FILTER_MODE=veto`;
- enriched feed mount: `/opt/aitrader_data/feed -> /opt/aitrader/feed` read-only;
- persistent state: `/root/volume-alert/data/state/deltascout`;
- only the `deltascout` container was recreated; Executor, Buyer and n8n were not
  restarted;
- the rollout intentionally bypassed the recommended seven-day shadow stage at
  the operator's explicit direction. The historical parity evidence is unchanged,
  but prospective shadow gates must therefore be treated as not yet satisfied;
- startup rebuilds component A from the canonical DeltaScout archive; the first
  verified VPS bootstrap recovered `17` exact-window extrema, so A and B are both
  eligible immediately when their respective inputs are trustworthy.

## 1. Decision

Integrate the frozen loss-avoidance union as a versioned, PEAK-only admission
policy inside DeltaScout, after all existing comparison and gate checks and before
the live `PEAK` JSON is written to `deltascout.log`.

The integration must be deployed in two operational stages:

1. `shadow`: calculate and archive the decision while emitting every current PEAK
   exactly as before;
2. `veto`: suppress the live PEAK only when the union is definitely `true` and a
   durable audit record has been written successfully.

Unknown, stale, incomplete, untrusted, or failed feature calculations always keep
the signal. The policy is fail-open.

The policy must not be applied to ALMOST 2/3 candidates. Historical dual-feed
evidence showed unacceptable domain transfer: 32 of 45 replay-protected ALMOST
outcomes were flagged.

## 2. Frozen rule contract

Rule identifier:

```text
DS_PEAK_LOSS_AVOIDANCE_UNION_V1
```

Eligible cohort:

```text
action == PEAK
candidate_group == PEAK_EMIT_BASELINE
```

Components:

```text
A = same_side_peak_percentile_24h <= 50.0

B = oi_trusted_60m
    AND oi_change_60m < 0
    AND directional_delta_pct_240m < 0.06

BLOCK = A OR B
```

`directional_delta_pct_240m` is direction-adjusted:

```text
raw_delta_pct = (sum(BuyQty) - sum(SellQty)) / sum(BuyQty + SellQty)
LONG  directional_delta_pct = raw_delta_pct
SHORT directional_delta_pct = -raw_delta_pct
```

`oi_change_240m` is not part of the policy. Thresholds must not be changed under
the same rule identifier.

Three-valued decision logic:

| A | B | Union | Runtime action in veto mode |
|---|---|---|---|
| true | any | true | block |
| any | true | true | block |
| false | false | false | keep |
| false | unknown | unknown | keep |
| unknown | false | unknown | keep |
| unknown | unknown | unknown | keep |

## 3. Evidence boundary

Corrected dual-feed experiment:

```text
deltascout/research_material/backtests/
scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v2/
```

Shared-kernel parity replay:

```text
deltascout/research_material/backtests/
scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v3_shared_policy/
```

The v3 replay imports the same V1 policy kernel as the runtime adapter and exactly
reproduces the v2 loss-avoidance metrics for both PEAK and ALMOST cohorts. ALMOST
remains an evidence-only negative control and is not eligible for live filtering.

PEAK replay:

- baseline: 46 candidates, 35 fills, -21.06 USDC net;
- union blocked fills: 7 plain SL, 5 TP1->SL, 0 protected;
- kept: 23 fills, +175.42 USDC net, +7.63 USDC/fill.

Comparable operational PEAK outcomes:

- union flagged 6/13 plain SL;
- union flagged 3/8 TP1->SL;
- union flagged 0/7 TP1+TP2 protected outcomes.

This is a small, discovery-domain sample. The evidence supports guarded PEAK-only
integration, not a universal filter or a claim of independently validated edge.

## 4. Current production constraint

The running DeltaScout container reads the legacy 10-column feed mounted under
`/data`. That feed has price, volume, BuyQty, and SellQty but no Open Interest.

The separate `shi-aggregator` writes the enriched feed to:

```text
/opt/aitrader_data/feed/YYYY-MM-DD.csv
```

The executor already mounts that directory read-only as `/opt/aitrader/feed`, but
DeltaScout currently does not. DeltaScout therefore cannot calculate component B
without one new read-only bind mount.

Required DeltaScout mounts:

```text
/opt/aitrader_data/feed  -> /opt/aitrader/feed      read-only
/root/volume-alert/data/state/deltascout
                         -> /data/state/deltascout   read-write
```

DeltaScout must receive no Binance, OpenAI, or trading credentials for this
feature. The evaluator performs local file reads only.

The legacy DeltaScout timestamps are Europe/Bratislava local time, while enriched
feed timestamps are UTC. Conversion must use an explicit timezone database, not a
fixed UTC offset, so DST transitions remain correct.

## 5. Target architecture

```text
legacy aggregated.csv
        |
        v
existing DeltaScout detector
  3/3 comparisons -> gates -> would-be PEAK
                              |
                              v
                    loss filter evaluator
                    /                   \
         24h same-side peaks       enriched SHI feed
         persistent local state    OI 60m + flow 240m
                    \                   /
                     versioned tri-state decision
                              |
             +----------------+----------------+
             |                                 |
        research archive                 live PEAK bus
        always attempted                 KEEP/UNKNOWN only
             |                                 |
      offline backtester                  Buyer + Executor
```

The detector remains responsible for identifying a valid PEAK. The new layer only
decides whether that already-valid PEAK is admitted to the live bus.

## 6. Code ownership and drift prevention

Create a pure policy kernel with no filesystem, network, pandas, or exchange side
effects:

```text
deltascout/loss_avoidance_policy.py
```

It owns:

- the rule identifier and thresholds;
- three-valued component/union evaluation;
- a typed decision result;
- reason codes.

Both live runtime evaluation and the offline backtester must import this same
kernel. The existing offline rule must not remain as a second independent copy.

Create a runtime adapter:

```text
deltascout/loss_avoidance_runtime.py
```

It owns:

- timestamp conversion;
- persistent 24h peak history;
- enriched-feed loading across UTC day boundaries;
- exact cutoff and contiguity validation;
- feature calculation;
- health counters and audit payload construction.

Modify `deltascout/delta_scout.py` only at narrow integration points:

1. record each `DELTA_MAX`/`DELTA_MIN` in the persistent history;
2. after existing gates pass, build the unchanged would-be PEAK payload;
3. call one `_admit_peak(...)` helper for both LONG and SHORT branches;
4. emit or suppress the live payload based on mode and durable audit success.

The duplicated LONG/SHORT admission blocks should be replaced by the shared helper
so the two sides cannot drift.

## 7. Feature parity rules

### 7.1 Component A

Maintain UTC tuples:

```text
(event_ts_utc, side, abs(delta))
```

The window includes the current delta peak and all same-side `DELTA_MAX` or
`DELTA_MIN` events in the preceding 24 hours. Percentile semantics must match the
backtester exactly:

```text
100 * count(value <= abs(current_delta)) / count(values)
```

Persist the deque atomically after every new peak. On startup:

- load and validate the state cache;
- rebuild or merge the last 24 hours from the append-only DeltaScout archive,
  which remains the canonical source;
- prune events older than 24h and persist the rebuilt bounded cache;
- mark A `unknown` if full history provenance cannot be established.

The state file is only a runtime cache. Missing or corrupt state must be rebuilt
from the canonical archive, so a normal restart does not create a 24-hour blind
period. The system must not pretend that incomplete archive coverage is a full
window.

### 7.2 Component B

For the exact signal cutoff minute in UTC, load:

- 60 contiguous one-minute bars for Open Interest, including the cutoff minute;
- 240 contiguous one-minute bars for BuyQty/SellQty, including the cutoff minute.

OI is trusted only when every required 60m bar:

- exists exactly once;
- has `IsSynthetic == 0`;
- has finite OpenInterest;
- is contiguous at one-minute spacing.

The 240m directional flow is known only when every required bar is real,
contiguous, and has finite BuyQty/SellQty.

The runtime must not silently substitute the previous minute when the exact cutoff
bar is unavailable. That would create a new policy variant. Missing exact cutoff
means component B is unknown and the signal is kept.

The evaluator must not wait for the enriched collector because delayed admission
can materially worsen entry. It performs one bounded local read; timeout or lag is
fail-open and recorded.

## 8. Runtime modes

Environment contract:

```text
LOSS_FILTER_MODE=off|shadow|veto
LOSS_FILTER_RULE_ID=DS_PEAK_LOSS_AVOIDANCE_UNION_V1
LOSS_FILTER_ENRICHED_FEED_DIR=/opt/aitrader/feed
LOSS_FILTER_STATE_PATH=/data/state/deltascout/loss_filter_state.json
LOSS_FILTER_RESEARCH_ARCHIVE_DIR=/data/archive/deltascout
LOSS_FILTER_SOURCE_TIMEZONE=Europe/Bratislava
LOSS_FILTER_ENRICHED_TIMEZONE=UTC
LOSS_FILTER_EVAL_BUDGET_MS=500
```

Mode behavior:

| Mode | Calculate | Archive | Block PEAK |
|---|---:|---:|---:|
| off | no | optional disabled record | no |
| shadow | yes | yes | no |
| veto | yes | yes | only definite union=true |

The default must be `off`. Missing or invalid mode values must resolve to `off`.

## 9. Audit events and counterfactual preservation

For every would-be PEAK after the existing gates, write
`PEAK_LOSS_FILTER_DECISION` to the research archive.

Required fields:

```json
{
  "schema": 1,
  "event": "PEAK_LOSS_FILTER_DECISION",
  "ts": "original local signal timestamp",
  "signal_ts_utc": "UTC timestamp",
  "kind": "long|short",
  "rule_id": "DS_PEAK_LOSS_AVOIDANCE_UNION_V1",
  "configured_mode": "shadow|veto",
  "decision": "KEEP|BLOCK|UNKNOWN_KEEP",
  "component_a": true,
  "component_b": false,
  "union": true,
  "same_side_peak_count_24h": 12,
  "same_side_peak_percentile_24h": 41.67,
  "oi_change_60m": -123.45,
  "oi_trusted_60m": true,
  "directional_delta_pct_240m": 0.031,
  "feature_cutoff_utc": "2026-08-20T14:30:00Z",
  "enriched_last_ts_utc": "2026-08-20T14:30:00Z",
  "feature_status": "EXACT|STALE|MISSING|INVALID",
  "reason_codes": ["WEAK_SAME_SIDE_PEAK"],
  "would_be_peak": {}
}
```

In veto mode, a block is allowed only after this append succeeds. If the archive
append fails, DeltaScout emits the PEAK and logs `AUDIT_WRITE_FAILED_KEEP`.

For a successful block, also emit a concise `PEAK_LOSS_FILTER_REJECT` research
event. It must contain the complete would-be PEAK payload so the backtester can
replay the rejected opportunity later.

Extend the candidate compiler so `PEAK_LOSS_FILTER_REJECT` remains in the PEAK
counterfactual cohort with an admission status, rather than disappearing from the
dataset. Otherwise future evaluation would be biased toward admitted trades.

The live `PEAK` bus payload should remain unchanged in the first implementation.
Filter metadata belongs in the research archive, avoiding accidental Buyer,
Executor, n8n, or dedup-contract changes.

## 10. Operator visibility

When a signal is blocked in veto mode, send a separate informational webhook event
such as `LOSS_FILTER_BLOCKED`. It is not a `PEAK` action and must not be consumable
as a trade signal.

The notification should show:

- LONG/SHORT and signal price;
- A/B values and which component caused the block;
- OI 60m and directional flow 240m;
- rule version;
- confirmation that the signal was archived for counterfactual replay.

Unknown-keep events should alert only when caused by a health problem, not for
normal unavailable optional history, to avoid notification noise.

## 11. Health protection and circuit breaker

Track at least:

- evaluated, kept, blocked, and unknown counts;
- component A/B known rates;
- exact-cutoff feed availability;
- enriched-feed lag;
- evaluation duration;
- state-load/state-write failures;
- research-audit write failures.

Automatic fail-open conditions:

- evaluation exceeds the configured time budget;
- enriched feed is missing, stale, non-contiguous, duplicated, or synthetic;
- OI or volume fields are non-finite;
- timezone conversion fails;
- persistent peak state is corrupt or incomplete;
- audit append fails;
- an unexpected exception occurs.

Add a runaway circuit breaker: five consecutive would-block decisions disable
effective veto for subsequent signals and raise an operator alert until restart or
explicit acknowledgement. This protects against a broken feed, timestamp mapping,
or threshold-unit error.

## 12. Rollout plan

### Phase 0 - local implementation and parity

1. Extract the shared pure policy kernel.
2. Implement runtime feature adapter and persistent state.
3. Re-run the full historical backtest and require unchanged v2 flags/metrics.
4. Run recorded-event parity: live adapter output must equal offline features for
   every historical PEAK where inputs are trusted.
5. Test DST boundaries and local-to-UTC mapping explicitly.

No server change in this phase.

### Phase 1 - production shadow

1. Back up the current server DeltaScout source, env, compose definition, and
   relevant state.
2. Add enriched-feed read-only and filter-state read-write mounts.
3. Deploy the code with `LOSS_FILTER_MODE=shadow`.
4. Observe for at least seven consecutive days and at least five PEAK evaluations.
5. Recompute every archived decision offline and compare field-by-field.

Shadow promotion gates:

- no lost or malformed existing PEAK events;
- no DeltaScout crash/restart attributable to the evaluator;
- 100% decision parity for evaluable archived PEAKs;
- exact cutoff available for at least 99% of evaluated signals;
- evaluation p95 below 200ms and maximum below 500ms;
- all unknown decisions demonstrably fail-open;
- counterfactual reject payload is sufficient for backtester replay.

### Phase 2 - guarded PEAK veto

1. Change only `LOSS_FILTER_MODE` from `shadow` to `veto`.
2. Keep A, B, and union journaling for every PEAK.
3. Review each of the first five blocked signals individually.
4. Run a weekly counterfactual replay of blocked signals on BTCUSDC Spot.
5. After each new five blocked signals, update protected-outcome guardrails.

Veto continuation gates:

- zero blocked TP1+TP2 protected outcomes in the prospective sample;
- blocked signals remain materially worse than kept signals after costs;
- unknown rate and data lag stay within shadow thresholds;
- no threshold changes under V1.

Any protected false positive immediately returns the system to shadow pending
review. A TP1->SL block alone is not a rollback trigger under the agreed utility
policy.

### Phase 3 - optional asynchronous LLM review

Do not call the LLM synchronously inside DeltaScout. It would add credentials,
network latency, and an external failure mode to signal admission.

If model opinions are required for filter-rejected or position-locked signals, add
an asynchronous research-only consumer of `PEAK_LOSS_FILTER_REJECT` and other
counterfactual events. Its verdict journal must be separate from live execution and
must never re-open a blocked trade automatically.

## 13. Rollback

Primary rollback:

```text
LOSS_FILTER_MODE=shadow
```

Restart only DeltaScout. Executor, Buyer, n8n, collectors, open positions, and
orders are not modified by the filter rollout.

Emergency rollback:

1. restore the backed-up DeltaScout source/env/compose definition;
2. restart DeltaScout;
3. verify new PEAK bus writes and research archive growth;
4. preserve filter state and audit files for post-mortem; do not delete them.

Rollback acceptance:

- DeltaScout health is restored;
- `deltascout.log` receives the unchanged PEAK contract;
- Executor continues managing any open position;
- no collector is restarted or removed unnecessarily.

## 14. Test matrix

Required automated tests:

- A threshold below, equal to, and above 50;
- B threshold below, equal to, and above 0.06;
- LONG and SHORT directional sign symmetry;
- OI down, flat, and up;
- union three-valued truth table;
- unknown always keeps;
- current peak included in 24h percentile;
- exact 24h pruning boundary;
- restart/state restoration and corrupt-state fail-open;
- cross-midnight 60m and 240m windows;
- Europe/Bratislava DST transitions;
- exact cutoff missing/stale/duplicate/synthetic cases;
- audit failure prevents veto;
- shadow mode never changes PEAK emission;
- veto mode blocks only definite union=true;
- LONG and SHORT use the same admission helper;
- existing Buyer/Executor PEAK payload contract remains byte-compatible at field
  level;
- `PEAK_LOSS_FILTER_REJECT` compiles into counterfactual backtester candidates;
- historical v2 metrics remain unchanged after sharing the policy kernel.

## 15. Implementation work packages

### WP1 - policy kernel and tests

- create shared pure policy module;
- move offline evaluator to the shared module;
- freeze V1 constants and truth table;
- prove unchanged historical results.

### WP2 - runtime features and state

- add timezone-safe feature adapter;
- add exact enriched-feed windows;
- add persistent 24h peak history;
- add health and fail-open tests.

### WP3 - DeltaScout shadow integration

- add unified `_admit_peak` helper;
- add research decision events;
- preserve existing PEAK bus payload;
- add operator notifications and metrics.

### WP4 - counterfactual research continuity

- compile filter rejects offline;
- replay blocked signals on BTCUSDC Spot;
- report prospective operational guardrails.

### WP5 - server shadow rollout

- sync and back up authoritative server files;
- add minimal mounts/env;
- deploy shadow only;
- observe and verify before any veto authorization.

### WP6 - separately authorized veto activation

- switch the mode only after shadow gates pass;
- review first five blocks;
- maintain immediate rollback readiness.

## 16. Explicit non-goals

- no filter for ALMOST 2/3;
- no use of `oi_change_240m` as a veto;
- no threshold optimization during rollout;
- no synchronous LLM call in the admission path;
- no Executor order-management change;
- no Buyer or n8n workflow contract change;
- no silent deletion of blocked candidates from research evidence;
- no fail-closed behavior on missing data or infrastructure errors.

## 17. Definition of done

The integration is complete only when:

1. one shared V1 kernel is used by live and offline code;
2. shadow decisions reproduce offline calculations exactly;
3. every decision is auditable and every blocked PEAK remains replayable;
4. unknown and failures are proven fail-open;
5. the existing PEAK bus contract remains stable;
6. the enriched feed is read-only and no new trading credentials enter DeltaScout;
7. shadow rollout gates pass;
8. veto activation, if desired, is performed as a separate production-adjacent
   authorization with tested rollback.
