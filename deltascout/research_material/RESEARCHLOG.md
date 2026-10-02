# DeltaScout Research Log

## Purpose

This is the curated research memory for DeltaScout.

It should answer:

- what the research program currently believes;
- which findings are durable enough to carry forward;
- what remains unknown;
- which next research steps are worth doing.

This file is not a raw summary archive. Batch reviews, bundle markdowns, and CSVs are evidence artifacts. Durable conclusions are distilled here.

### Corrected PEAK + live A/B Executor-parity rerun (2026-09-13)

- Canonical run:
  `backtests/scout_peak_live_ab_executor_parity_240_lr25_2026-09-13_v3_final/`.
- Cohort and filter: `PEAK_EMIT_BASELINE` with `UNION_A_OR_B`; `48` candidates
  before filter, `18` blocked, `30` kept, `26` independent fills.
- Stop contract: V8 initial `1440/LR25/highest-volume/buffer50/cap1200/full-window`;
  trailing `240/LR25/buffer50/step25/confirm20`.
- Official BTCUSDC execution feed was extended through 2026-08-31 to avoid
  falsely truncating the 2026-08-18 trailing position: `166` complete days,
  `239040` rows, zero missing or duplicate minutes.
- Independent result: `+205.39 USDC`, `+7.90 USDC/fill`, PF `1.57`, `+8.99R`,
  max drawdown `127.01 USDC`. Frozen validation: `+159.62 USDC` across `12`
  fills; discovery: `+45.77 USDC` across `14` fills.
- Executor-portfolio result: `+237.30 USDC`, `+11.30 USDC/fill`, PF `1.94`, max
  drawdown `87.90 USDC`; `6` candidates were position-lock blocked.
- All `9` independent trades that reached TP2 changed under corrected trailing;
  `17` fills closed before trailing and were unchanged. Aggregate independent
  net happened to remain close to the invalid old run (`+206.49` -> `+205.39`),
  but individual stop levels, exits, holding times, and PnL changed materially.
  The old run therefore remains non-parity despite the coincidental aggregate.
- Ukrainian comparison:
  `backtests/scout_peak_live_ab_executor_parity_240_lr25_2026-09-13_v3_final/executor_parity_rerun_uk.md`.

---

## Fixed pre-TP1 failed-impulse exit: negative reference-class result — 2026-09-08

The first step-3 policy was fixed before calculation: age >=60 minutes, favourable
excursion >=0.5R from actual fill, price returned to <=0R, opposing last-15-minute
delta, next-minute Open exit. It is evaluated every completed minute until TP1
or closure, without a maximum age. No threshold optimization was performed.

On the corrected A/B portfolio, four plain SL improvements contributed +136.2108
USDC, but three former TP1->SL trades lost 35.4309 and two former TP2/trailing
trades lost 145.7924. The common-trade change was -45.0125 USDC. Recomputed slot
availability admitted one additional losing SHORT (-44.7916), giving total
portfolio change -89.8041: net +233.5086 -> +143.7044 USDC and closed-trade
drawdown 87.8964 -> 109.7581 USDC. No-filter results also deteriorated.

Reject this tested rule for adoption. A favourable push followed by a return to
entry and opposing recent delta does not sufficiently distinguish invalidated
setups from eventual winners here. This does not invalidate every early-exit
hypothesis. Future rules need a separately motivated and frozen invalidation
condition; this previously inspected historical sample is not out of sample.
PEAK remains a bounded reference class rather than the whole research program.

Source: `reviews/early_exit_failed_impulse_2026-09-08_v1/report_uk.md` and its
hashed JSON artifacts. Both corrected baselines reproduced; 104 tests passed.
Runtime/live execution was not changed.

## Current Doctrine

DeltaScout research is not primarily about loosening current `PEAK_EMIT` filters.

The current operating model is:

```text
market state -> transition -> process phase -> entry timing
```

Current `PEAK_EMIT` is useful as:

- a reference class;
- a diagnostics surface;
- a live/runtime grammar that must be handled carefully.

Current `PEAK_EMIT` is not:

- the full boundary of setup discovery;
- proof that accepted entries are the strongest possible entries;
- enough evidence by itself for profitability claims.

The core research goal remains finding repeatable market behavior that can support better entries and meaningful BTC directional movement.

---

## 2026-09-08 Recovery and execution clock correction

The May 4 wrong-side initial SL was caused by offline clock alignment, not by
trailing Low/High selection or the historical live order. Legacy local timestamps
were joined to UTC SHI without conversion, and official Spot open-time labels were
treated as completed-minute labels. Both errors are corrected in new artifacts.

Use `recovery_clock_v2_2026-09-08/effective_feed/` and its `quality/` sibling for
the frozen V8 research scope. Keep old recovery/snapshots as forensic originals;
prior recovery-dependent economics and all older dual-feed open/close-clock
results are superseded until rebuilt.

The new experiments are `backtests/scout_peak_v8_clock_corrected_2026-09-08/`
and `backtests/scout_peak_v8_clock_corrected_2026-09-08_live_ab/`.
With unchanged candidate identities, numeric policy settings and costs:

| Replay | Fills | Net USDC | PF | Max DD USDC |
|---|---:|---:|---:|---:|
| No filter independent | 44 | -14.81 | 0.983 | 284.47 |
| No filter portfolio | 32 | -119.14 | 0.823 | 297.23 |
| A/B independent | 26 | +206.49 | 1.577 | 126.83 |
| A/B portfolio | 21 | +233.51 | 1.930 | 87.90 |

The unfiltered policy no longer has positive net performance in this corrected
sample. A/B remains positive in-sample; no thresholds were tuned. Exact exchange
execution, 90-second timing, and order-book fidelity remain outside 1m replay.
Research-window overlap must be checked on the reference feed: the existing
execution-based trade overlap metric alone is insufficient.

Real May 4 SHORT: entry `78814.69`, SL `79923.07`, plain SL. Recomputed V8
counterfactual: entry `78823.71`, initial SL `79317.85`, `TP1_SL`, net `+1.3672`.
Neither statement implies that the historical live trade used the recomputed plan.
The offline post-fill invariant now fails the run on nonprotective SL geometry.

Evidence and reproducible scripts:
`reviews/entry_anomaly_2026-05-04_audit_2026-09-08/report_uk.md`.
`80` targeted tests passed. Only anomaly resolution and baseline rebuild (step 1)
were performed; trade-development analysis and early exits remain subsequent work.

## 2026-09-06 Full V8 Trailing Parity (economics superseded 2026-09-08)

Sources:

- `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_trailing_parity_v2/`
- `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_live_ab_trailing_parity_v2/`

Correction:

- The initial V8 stop selection in the 2026-09-05 runs was already structurally
  correct, but the replay trailing engine still built its fractal series from
  BTCUSDC execution-feed closes. That did not match Executor.
- The corrected replay uses BTCUSDT lows for LONG trailing swings and BTCUSDT
  highs for SHORT trailing swings. BTCUSDT close is used only for the
  post-activation confirmation break.
- Every activation/update derives a same-minute historical quote-sync proxy
  `k_trail = BTCUSDC close / BTCUSDT close`, enforces `[0.95, 1.05]`, converts the
  buffered USDT swing, rounds outward, validates the stop side in BTCUSDC, and
  retains the existing stop if synchronization is unavailable or invalid.
- Each applied trailing event now records the source swing timestamp/price, source
  USDT stop, converted BTCUSDC stop, ratio, both closes, and conversion timestamp.

Corrected result:

- No-filter independent: `48` candidates / `46` fills / `24` Plain SL /
  `6` TP1->SL / `16` protected, `+181.55 USDC`, `+3.95/fill`, PF `1.22`,
  max DD `$239.87`.
- No-filter one-position portfolio: `35` fills / `19 / 5 / 11`, `+18.16 USDC`,
  `+0.52/fill`, PF `1.027`, max DD `$193.64`.
- Current live A-or-B veto (a trade is accepted only when neither A nor B fails):
  `30` candidates / `28` independent fills / `12 / 5 / 11`, `+280.61 USDC`,
  `+10.02/fill`, PF `1.76`, max DD `$127.90`.
- Re-sequenced filtered portfolio: `24` fills / `10 / 5 / 9`, `+253.04 USDC`,
  `+10.54/fill`, PF `1.821`, max DD `$87.74`.
- Outcome classes do not change versus the 2026-09-05 runs; all `16` protected
  independent outcomes have corrected trail pricing. Net changes by `-27.39 USDC`
  without filters and `-14.00 USDC` under current live A/B.

Audited `2026-07-18 12:07 UTC` LONG:

- Initial structural selection remains `2026-07-17 16:24 UTC`, Low `63272.40`,
  volume `585.481`, buffered stop `63222.40 USDT`, converted initial stop
  `63189.24 USDC`.
- At TP2, the first trailing swing is `2026-07-21 07:26 UTC`, Low `65863.00`,
  source stop `65813.00 USDT`; the historical quote-sync proxy converts it to
  `65735.98 USDC`. Later confirmed Low swings move the stop to `65989.39` and
  `66088.23 USDC`; exit remains `2026-07-21 08:11 UTC`, net `+73.00 USDC`.

The 2026-09-05 `*_corrected_v1` economics are superseded by these runs. The
deployed Executor logic was the reference and was not changed.

---

## 2026-09-05 Corrected V8 BTCUSDT-to-BTCUSDC Contour (superseded trailing model)

Sources:

- `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_corrected_v1/`
- `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_live_ab_corrected_v1/`
- Single-candidate audit:
  `backtests/scout_peak_v8_usdt_swing_to_usdc_execution_2026_07_18_correction_v1/`

Correction:

- V8 must select and freeze the structural swing on the canonical enriched
  BTCUSDT feed first. The selected candle, its Low/High, volume, buffered USDT
  stop, and USDT 1R/2R targets are structural facts and cannot be reselected on a
  second price feed.
- Only after that USDT plan is complete is one contemporaneous
  `BTCUSDC / BTCUSDT` ratio applied. Entry/SL/TP lifecycle touches then use
  official BTCUSDC Spot bars.
- The earlier experiment
  `scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1` violated
  this boundary by selecting the swing on normalized legacy BTCUSDT Spot. Its
  no-filter `+153.84 USDC` result and derived live-A/B `+275.51 USDC` result are
  superseded and must not be used for current V8 conclusions.

Structural parity and corrected result:

- All `48/48` PEAK candidates exactly match the canonical BTCUSDT V8 run on
  swing timestamp, swing price, swing volume, and finished USDT stop.
- No-filter independent: `48` candidates / `46` fills / `24` Plain SL /
  `6` TP1->SL / `16` protected, `+208.94 USDC`, `+4.54/fill`, PF `1.256`,
  max DD `$239.75`.
- No-filter one-position portfolio: `35` fills / `19 / 5 / 11`, `+30.23 USDC`,
  `+0.86/fill`, PF `1.045`, max DD `$193.64`.
- Current live A-or-B veto, with unknown values admitted fail-open: `30`
  candidates / `28` independent fills / `12 / 5 / 11`, `+294.61 USDC`,
  `+10.52/fill`, PF `1.795`, max DD `$127.77`.
- Re-sequenced filtered portfolio: `24` fills / `10 / 5 / 9`, `+267.09 USDC`,
  `+11.13/fill`, PF `1.867`, max DD `$87.74`.

Audited `2026-07-18 12:07 UTC` LONG:

- The frozen BTCUSDT structural candle is `2026-07-17 16:24 UTC`, Low
  `63272.40`, volume `585.481`; the buffered stop is `63222.40 USDT`.
- Signal-time ratio `0.9994755394662788` converts that already-selected stop to
  `63189.24 USDC`. The corrected official-BTCUSDC replay reaches TP1 on
  `2026-07-20 15:43 UTC`, TP2 on `2026-07-21 07:43 UTC`, and exits the trailing
  remainder on `2026-07-21 08:11 UTC` for `+73.13 USDC` net before unavailable
  borrow interest.
- The deployed Executor already follows this ordering on `aggregated.csv`; the
  defect was confined to the superseded offline experiment input, so no live
  runtime change was required.

---

## Regime-First Reading Rule

When event context is available, read fields in this order:

1. `cum_delta_24h`
2. `cum_delta_180m`
3. `cum_delta_60m`
4. `ret_15m`
5. `ret_60m`

`cum_delta_24h` is regime context, not a standalone signal.

If `cum_delta_24h` is missing or zeroed in suspicious ways, say that regime framing is incomplete instead of silently continuing.

---

## Close Outcome Reading Rule

Close/outcome rows must be interpreted by their full artifact semantics, not by `close_reason` alone.

- `close_reason=SL` with `trade_lifecycle_state=plain_sl` and no TP/trailing flags means a losing stop-loss outcome.
- `close_reason=SL` with `lifecycle_trail_active=True` or a trailing lifecycle state means a protected/profitable trailing-stop outcome.
- `close_reason=SL` with `lifecycle_tp1_done=True` means TP1 was reached; if no later profit extension is shown, treat it as TP1-then-near-breakeven / practical zero until verified.

Durable implication:

- Do not collapse all `close_reason=SL` rows into one "loss" bucket.
- Accepted-flow analysis must separate losing stops, protected-profit trailing stops, near-breakeven TP1 stops, and missing/unmatched close joins.

---

## Research Timeline

### 2026-03-16 to 2026-03-20: Initial Findings

Source:

- `2026-03-16_to_2026-03-20_initial_findings.md`

Durable findings:

- The early copied archive was reject-heavy but already included one `PEAK_EMIT`.
- Comparison rejects dominated over gate rejects.
- Main visible reject reasons were `direction_mismatch` and `vwap_side`.
- The first accepted-flow close join existed for `2026-03-20`.

Durable interpretation:

- Reject-funnel research was justified.
- Accepted-flow handling should be kept in the loop, but accepted samples were too sparse to define the research center.

### 2026-03-23 to 2026-04-01: Family Split

Source:

- `2026-03-23_to_2026-04-01_family_findings.md`

Durable findings:

- The short-side reject funnel should not be treated as one undifferentiated pool.
- Family A: short-side rejects above VWAP, often `vwap_side`, earlier transition / placement-conflict lane.
- Family B: short-side rejects below VWAP, often `3of3_fail`, later aligned-failure lane.
- Accepted short cases remain reference examples, not a validated edge source.

Durable interpretation:

- Family A is the stronger transition-timing lead.
- Family B is the broader setup-discovery lane.
- Future analysis should not collapse short-side rejects back into generic reject counts.

### Family B Focused Work

Sources:

- `reviews/focused_family_b_deep_dive.md`
- `reviews/focused_family_b_b1_b2_clarification.md`
- `reviews/focused_b1_path_variants_memo.md`

Durable findings:

- Family B is not internally uniform.
- B1 is the strongest operational subtype.
- B2 is not currently supported as a distinct subtype; treat it as a weak or edge case inside B1 unless stronger evidence appears.
- B3 remains the strongest setup-discovery anomaly.

Durable interpretation:

- The strongest Family B cases are not explained well by pure directional weakness.
- The unresolved problem is likely timing, sequence conflict, exhaustion, or grammar mismatch hidden behind `3of3_fail`.

### Minute-Event Research

Sources:

- `minute_events_cross_day_evidence_review_2026-03-17_to_2026-04-04.md`
- `minute_events_cross_day_evidence_review_post_m2b_2026-03-17_to_2026-04-04.md`
- M2.6 artifacts under `minute_datasets/m2_6/`

Durable findings:

- Minute-level research is a first-class research surface, not just support material for PEAK rows.
- Process-chain interpretation is useful, but still exploratory.
- Minute-event families should be treated as early discovery classes, not final taxonomy.

Durable interpretation:

- Setup discovery should move toward process reconstruction: precursor, manipulation, truth seed, continuation, late/exhaustion.
- Move-potential testing remains mandatory before any setup class matters.

### 2026-04-06 to 2026-05-02: Coverage Extension

Source:

- latest rebuilt local review folders
- `reviews/reviews_2026-04-06_to_2026-05-02_final_research_review.md`
- `bundles/2026-03-17_to_2026-05-02/`

Durable facts:

- The local review corpus now covers `2026-03-17` through `2026-05-02` without missing dates.
- The new rebuilt range remains reject-heavy.
- For `2026-04-06_to_2026-05-02`, local CSV counts are:
  - accepted: `10`
  - rejects: `495`
  - interesting rejects: `290`
  - close outcomes: `8`
  - accepted-to-close `window_match`: `3`

Durable interpretation:

- The research center remains reject taxonomy, blocker diagnostics, and process-chain study.
- Accepted rows remain useful reference cases but still do not support outcome-strength conclusions.
- `direction_mismatch`, `vwap_side`, and `3of3_fail` remain the main blocker surfaces.

Anomaly to carry forward:

- `interesting_rejects` is effectively empty for `2026-04-24` through `2026-05-02` while reject rows exist. This needs verification before using that subrange for bucket-level conclusions.

---

## Current Working Hypotheses

1. Family A is an earlier short-transition lane where flow rotates short before structural placement confirms.
2. Family B is a later short-transition lane where short placement is already aligned, but deeper timing, sequence, or grammar failure remains.
3. B1 is the strongest current operational subtype inside Family B.
4. B3 is the strongest current setup-discovery anomaly inside Family B.
5. `vwap_side` and `direction_mismatch` should be studied as process-state evidence, not mechanically loosened.
6. M2.6 process chains may help distinguish isolated rejects from recurring market-process phases.

---

## What Is Not Proven

- Current accepted `PEAK_EMIT` rows do not prove a stable edge.
- Strong-looking rejected rows do not prove missed trades.
- Family A and Family B are not validated live setup classes.
- Bucket labels such as `possible_reversal_confirmation` or `unclear_but_constructive` are not validated setup classes.
- Sparse close outcomes are not enough for profitability claims.
- No live logic change should be shipped solely because a reject looks better than an accepted row on a few fields.

---

## Accepted Outcome Ledger: 2026-03-17 to 2026-05-02

Source:

- `reviews/accepted_outcome_ledger_2026-03-17_to_2026-05-02.md`
- `reviews/accepted_outcome_ledger_2026-03-17_to_2026-05-02.csv`

Durable facts:

- Local accepted `PEAK_EMIT` corpus contains `15` accepted rows.
- Confirmed plain/normal `SL` rows with artifact/user-confirmed joined context: `4`.
- Confirmed `protected_profit_trailing_stop` rows: `2`.
- Manual-confirmed factual `SL` results: `1`.
- User-confirmed `SL` rows with missing local artifact join: `1` (`2026-04-11 15:11`).
- User-confirmed `SL_TP1` rows with missing local artifact join: `1` (`2026-04-09 17:35`).
- User-confirmed no-trade missed entry rows: `1` (`2026-04-16 15:53`).
- Inferred `SL` rows where close outcome exists but `peak_ts` link is missing: `5`.
- Accepted rows with completely unknown outcome after user clarification: `0`.
- `SL` rows without enough lifecycle detail after user clarification: `0`.
- Explicit `missing_close_join` rows: `1`.
- Accepted rows with no close join in accepted context: `7`.

Durable interpretation:

- The previous shorthand "many SL losses" is not valid for this corpus.
- `2026-04-17 10:49`, `2026-04-21 10:48`, and `2026-04-23 10:45` have artifact-native close outcomes in `close_outcomes_*`; `2026-04-17` is TP1/TP2/trailing stop, while `2026-04-21` and `2026-04-23` are normal `SL`.
- User confirmed `2026-04-05 14:34` `manual_override` is a factual `SL` result and should be included in outcome evidence.
- User confirmed `2026-04-11 15:11` is a real accepted `PEAK_EMIT` that ended in `SL`; local close outcome/join fields are missing, so the ledger classification is user-confirmed rather than artifact-native.
- User confirmed `2026-04-09 17:35` ended as `SL_TP1`, i.e. TP1 then stop / practical breakeven; local close outcome/join fields are missing.
- User confirmed `2026-04-16 15:53` was not a trade: price moved down quickly and the bot missed entry. Treat it as a missed-entry / no-trade case, not an SL.
- Five accepted `PEAK_EMIT` rows likely have close outcomes in `close_outcomes_*.csv`, but those rows lack `peak_ts` links and appear as `join_status=missing`. Repairing this join layer is required before accepted-performance analysis.
- The accepted-context builder was corrected to propagate `close_outcomes_*` lifecycle fields from `lc_*` columns into `lifecycle_*` columns, and accepted dates were rebuilt locally.
- Accepted `PEAK_EMIT` still does not prove a stable edge, but the accepted outcome layer is more mixed than a raw `close_reason=SL` count suggests.
- Future accepted-flow analysis must use lifecycle-aware buckets before comparing accepted rows against rejected/M2.6 setup candidates.

---

## Practical Next Research Questions

1. Separate `vwap_side` rejects by regime compatibility and sequence role.
2. Decompose `direction_mismatch` into proper refusals, early precursors, and potential better-timing cases.
3. Decompose `3of3_fail` so Family B can be split by actual hidden blocker rather than terminal label.
4. Use M2.6 process-chain artifacts to decide whether important rejects are isolated, clustered, or part of a larger phase sequence.
5. Verify the `interesting_rejects` empty-output anomaly for `2026-04-24` through `2026-05-02`.

---

## Setup Candidate Discovery Surface: 2026-03-17 to 2026-05-02

Source:

- `reviews/setup_candidates_2026-03-17_to_2026-05-02.csv`
- `reviews/setup_candidates_2026-03-17_to_2026-05-02_summary.md`

Durable facts:

- The setup discovery surface contains `199` candidate rows.
- Source split: `15` accepted PEAK lifecycle reference rows, `172` M2.6 chain candidate rows, `8` interesting reject rows, and `4` non-interesting reject rows that still hit the `$1000` movement threshold.
- Track split: `15` current PEAK reference rows, `167` M2.6 process-chain rows, `5` M2.6 late/no-edge warning rows, and `12` rejected-family follow-through rows.
- Direction split: `115` long candidates and `84` short candidates.
- Accepted lifecycle coverage is carried into the same table, so current PEAK outcomes can be compared against M2.6/reject candidates without collapsing `SL`, `SL_TP1`, `SL_TRAILER`, and `NO_TRADE`.

Durable interpretation:

- The primary setup-discovery surface is now M2.6/rejected-family driven, with accepted PEAK kept as lifecycle reference rather than treated as the final signal class.
- `$1000+` movement potential appears in clustered M2.6/rejected-family evidence and must be evaluated by repeatability, lifecycle fit, and entry timing before any `AI_EMIT` promotion.
- This artifact is not a live signal spec. It is the first canonical table for selecting candidate setup families for deeper validation.

---

## Move-First Research Windows: 2026-03-17 to 2026-05-02

Source:

- `reviews/move_first_windows_2026-03-17_to_2026-05-02.csv`
- `reviews/move_first_windows_2026-03-17_to_2026-05-02.md`

Durable facts:

- This artifact starts from raw minute outcome movement, not from accepted PEAK, M2.6, or reject rows.
- It found `108` market move windows where BTC had `$1000+` directional movement potential within `60` minutes.
- Direction split: `59` long windows and `49` short windows.
- Only `2` of `108` move windows had a nearby accepted PEAK annotation.
- `106` of `108` move windows had no nearby accepted PEAK.
- All `108` move windows had nearby M2.6 candidate annotation, meaning M2.6 is broad enough to see movement zones but accepted PEAK is not.
- `58` of `108` move windows had nearby reject rows.

Durable interpretation:

- The previous setup-candidate work was still too detector-first. The correct primary research surface is now movement-first.
- Accepted PEAK is not the source of most `$1000+` movement opportunities in the current local corpus.
- M2.6 should be treated as a broad movement-zone detector, not a finished entry signal.
- The next research step should classify top move-first windows by market behavior before comparing them to PEAK/M2.6/reject annotations.

---

## Setup Cluster Review: 2026-03-17 to 2026-05-02

Source:

- `reviews/setup_cluster_review_2026-03-17_to_2026-05-02.csv`
- `reviews/setup_cluster_review_2026-03-17_to_2026-05-02.md`

Durable facts:

- The setup-candidate surface was reduced from `199` candidate rows into `50` time-local clusters using a `45` minute cluster gap.
- Cluster status split:
  - `candidate_setup`: `13`
  - `candidate_setup_with_reject_support`: `7`
  - `reject_followthrough_candidate`: `4`
  - `needs_more_evidence`: `11`
  - `reference_only`: `15`
- Strongest current clusters by priority:
  - `2026-03-23_long_c005`: M2.6 plus 3of3 reject support, max directional 60m move `2339.4`, max favorable 30m `3004.9`, max favorable 60m `2871.9`.
  - `2026-03-21_short_c004`: M2.6 short process cluster, max directional 60m move `1892.9`, max favorable 30m `1880.7`.
  - `2026-04-07_long_c025`: M2.6 plus direction-mismatch reject support, `27` rows, max directional 60m move `1789.8`, max favorable 60m `1627.4`.
  - `2026-04-16_short_c037`: M2.6 short process cluster, max directional 60m move `1342.7`, max favorable 30m `1637.9`.
  - `2026-04-12_short_c032`: M2.6 short process cluster, max directional 60m move `1613.6`, max favorable 30m `1535.5`.

Durable interpretation:

- Research should now review clusters, not isolated rows.
- The strongest immediate path toward `AI_EMIT` is manual sequence review of the top clusters to classify early entry, valid entry, late/no-edge warning, or discard.
- Clusters with rejected-family support are especially important because they may show where current `PEAK_EMIT` rejects still had setup-level movement potential.
- No cluster is promoted to live logic yet; promotion requires sequence review, lifecycle compatibility, and realistic stop placement.

---

## Top Cluster Quantitative Pre-Review: 2026-03-17 to 2026-05-02

Source:

- `reviews/top_cluster_manual_review_2026-03-17_to_2026-05-02.csv`
- `reviews/top_cluster_manual_review_2026-03-17_to_2026-05-02.md`

Durable facts:

- The first-pass quantitative pre-review used `T-180m` pre-context, cluster start/end, and `T+120m` post-context, plus a `T+180m` nearby accepted-PEAK lookahead.
- The `T-180m` timestamp is context only, not a proposed entry timestamp.
- All top 5 reviewed clusters produced `$1000+` favorable movement after a representative entry proxy.
- These rows are not manually chart-validated setup verdicts.
- `2026-03-23_long_c005`: quantitative fast-move candidate, favorable move `3004.9`, adverse before `$1000` hit `102.5`, time to `$1000` `15` minutes, with rejected-family support.
- `2026-03-21_short_c004`: quantitative move candidate, favorable move `2042`, adverse before `$1000` hit `15`, time to `$1000` `51` minutes.
- `2026-04-07_long_c025`: quantitative move candidate, favorable move `2083.4`, adverse before `$1000` hit `234.5`, time to `$1000` `28` minutes, with rejected-family support.
- `2026-04-16_short_c037`: quantitative move candidate, favorable move `1637.9`, adverse before `$1000` hit `86.4`, time to `$1000` `24` minutes. Nearby accepted PEAK was `2026-04-16 15:53 short NO_TRADE/no_trade_missed_entry`, meaning current PEAK came after the reviewed opportunity and execution missed the trade.
- `2026-04-12_short_c032`: quantitative move candidate, representative proxy `2026-04-12 00:50`, favorable move `1717.6`, adverse before `$1000` hit `117.8`, time to `$1000` `50` minutes. Nearby accepted PEAK was `2026-04-12 03:36 short SL/inferred_sl_missing_peak_link`, meaning current PEAK likely arrived later than the reviewed opportunity.

Durable interpretation:

- The immediate research path should now manually validate top clusters on chart/sequence before drafting `AI_EMIT` setup specs.
- The first two likely setup families are long process-continuation with reject support and short process-continuation before later accepted PEAK.
- `2026-04-16` and `2026-04-12` are especially important because they suggest useful short opportunities occurred before later accepted/no-trade or inferred-SL PEAK rows.
- These are still quantitative research candidates, not live candidates; next validation must define entry trigger, stop model, and repeatability criteria.

User-validated setup-entry confirmation:

- User clarified that all reviewed top-cluster representative proxy entries are valid entry points.
- Confirmed proxy-entry candidates: `2026-03-23_long_c005`, `2026-03-21_short_c004`, `2026-04-07_long_c025`, `2026-04-16_short_c037`, and `2026-04-12_short_c032`.
- This supersedes the earlier erroneous assistant note that treated `2026-04-16_short_c037` as only a no-short warning without first asking the user to review the correct time window. Do not treat that prior note as user-validated evidence.
- Treat all five clusters as manually validated setup-entry candidates, still below live-candidate status until trigger grammar, stop model, invalidation logic, and repeatability are formalized.
- `2026-03-23_long_c005` and `2026-04-07_long_c025` remain the strongest validated long candidates with rejected-family support.
- `2026-03-21_short_c004`, `2026-04-16_short_c037`, and `2026-04-12_short_c032` are validated short proxy-entry candidates and should be compared for shared short-side process grammar.
- User clarified `2026-04-16_short_c037`: the proxy entry was a theoretically tradeable counter-trend downside impulse around `15:30`, inside a broader long-market correction context. Around `15:50`, the US session/premarket flow swept stops near `73400`, then the market reversed higher and moved toward roughly `78300` on `2026-04-17`. Treat this as a counter-trend local short impulse plus broader long-context/session stop-run lesson, not as a clean standalone short setup rejection or simple short continuation class.
- User clarified the broader `2026-04-07_long_c025` to `2026-04-16_short_c037` process chain: `2026-04-07_long_c025` marks the start of the upward reversal / first leg from roughly `68700` to `72700`; the second upward leg continued toward roughly `76200` by `2026-04-14`; the subsequent correction lasted into `2026-04-16_short_c037` until roughly `15:50`. Treat `2026-04-16_short_c037` as a counter-trend correction impulse inside this larger long reversal process.
- User clarified the higher-timeframe regime context: the market is attempting to probe for a bottom / reversal after the major downtrend from roughly `125000` to `60000`, near the `50%` Fibonacci area. Globally, current structure should be treated as sideways/base-building or correction inside the larger downtrend, not as a clean confirmed bull trend.
- Within that regime, `2026-03-23_long_c005` is still inside the downtrend and should be treated as an early internal long impulse / precursor rather than confirmed trend reversal. `2026-04-07_long_c025` is the first stronger forerunner of the upward reversal process. `2026-04-16_short_c037` may be a related structure with the opposite sign: a counter-trend downside correction impulse inside the same broader base/reversal process.
- User summarized the highest-value direction: all reviewed proxy entries are pre-impulse / "fast money" locations. Future research should prioritize what conditions appear immediately before these fast directional impulses, rather than treating the rows as generic long/short continuation examples.
- Next research step: extract shared pre-impulse features across the five confirmed proxy entries, split long and short/counter-trend families, and define entry trigger, stop placement, invalidation, session context, and repeatability criteria before drafting `AI_EMIT` setup specs.

### Fast Money Pre-Impulse Extraction

Source:

- `reviews/fast_money_pre_impulse_review_2026-03-17_to_2026-05-02.md`

Durable facts:

- All five user-confirmed proxy entries are M2.6 process-chain clusters and hit `$1000+` favorable movement after the representative proxy entry.
- Accepted PEAK was absent or late around these opportunities; this supports M2.6 as the primary pre-impulse detection surface.
- Move-first windows distinguish `earliest_proxy_ts` from `best_proxy_ts`; earliest detection is often valid but can carry much larger adverse risk, while the best proxy is usually closer to acceleration with lower adverse.
- `2026-04-16_short_c037` is not a clean short-continuation class; it is a counter-trend downside impulse inside broader long/base-building context.

Durable interpretation:

- Future `AI_EMIT` research should split pre-impulse logic into at least `FAST_MONEY_LONG_FORERUNNER`, `FAST_MONEY_SHORT_PRE_IMPULSE`, and `FAST_MONEY_COUNTERTREND_IMPULSE`.
- The immediate analyzer need is a fast-money table that records M2.6 density, earliest proxy, representative proxy, best proxy, adverse-before-1000, reject support, nearby accepted PEAK timing, session context, and phase label.

---

## Current Fast-Money Research Thread Before Feed Incident

This section summarizes the active research direction that was interrupted by the `2026-04-23` feed-quality incident. Preserve it as the working research thread after feed recovery.

Durable research shift:

- The project moved away from PEAK/reject-only diagnostics toward movement-first and process-phase discovery.
- Current `PEAK_EMIT` is a reference/diagnostic class, not the boundary of future setup discovery.
- M2.6 process-chain material became the broad movement-zone detector; accepted PEAK was often absent or late around the best movement opportunities.
- The user validated all reviewed representative proxy entries as valid pre-impulse / "fast money" locations.

Confirmed user-reviewed proxy-entry cases:

- `2026-03-23_long_c005`: early internal long impulse inside the larger downtrend; a precursor rather than confirmed broad reversal.
- `2026-03-21_short_c004`: validated short proxy-entry candidate for short-side process comparison.
- `2026-04-07_long_c025`: start of the stronger upward reversal / first leg from roughly `68700` to `72700`; later continuation reached roughly `76200` by `2026-04-14`.
- `2026-04-16_short_c037`: theoretically tradeable counter-trend downside impulse around `15:30`; around `15:50` US/premarket flow swept stops near `73400`, then price reversed higher toward roughly `78300` on `2026-04-17`.
- `2026-04-12_short_c032`: validated short proxy-entry candidate; should be compared against other short/counter-trend fast-money cases.

Higher-timeframe regime context from user review:

- The market was probing for a bottom/reversal after a major downtrend from roughly `125000` to `60000`, near the `50%` Fibonacci area.
- Treat the regime as sideways/base-building or correction inside the larger downtrend, not as a clean confirmed bull trend.
- In that frame, `2026-04-07_long_c025` is the first stronger upward-reversal forerunner; `2026-04-16_short_c037` may be the opposite-sign correction impulse inside the same broader base/reversal process.

Main artifacts already built before the feed problem became the blocking issue:

- `fast_money_pre_impulse_table_2026-03-17_to_2026-05-05.csv`: `216` proxy rows from `108` move-first windows.
- Candidate-family split in the pre-impulse table:
  - `FAST_MONEY_COUNTERTREND_IMPULSE`: `106`
  - `FAST_MONEY_LONG_FORERUNNER`: `49`
  - `FAST_MONEY_LONG_PRE_IMPULSE`: `18`
  - `FAST_MONEY_SHORT_PRE_IMPULSE`: `35`
  - `FAST_MONEY_SHORT_LATE_RISK`: `8`
- `fast_money_setup_cases_2026-03-17_to_2026-05-05.csv`: `108` deduplicated setup cases.
- Setup-case quality split:
  - `A_STRONG_IMPULSE`: `1`
  - `B_CLEAN_SCALP`: `6`
  - `C_BARELY_HIT`: `78`
  - `D_LATE_NO_EDGE`: `7`
  - `F_COUNTERTREND_SWEEP`: `16`
- Repeatability-family split:
  - `countertrend_stop_sweep`: `56`
  - `reversal_forerunner`: `23`
  - `m2_density_pre_impulse`: `17`
  - `late_liquidity_chase`: `7`
  - `reject_supported_pre_impulse`: `2`
  - `generic_pre_impulse`: `3`

Interpretation:

- We found movement and candidate families, not finished tradable setup classes.
- Many detected moves only barely clear the `$1000` threshold; the next stage must separate strong/repeatable impulses from borderline and duplicate cases.
- The most important unresolved question is not whether movement exists, but what common birth conditions appear immediately before the best fast-money impulses.
- The research target is a small number of repeatable setup families with explicit trigger grammar, stop/invalidation logic, session context, and promotion criteria.

Post-recovery rule:

- Because `2026-04-24` through `2026-05-05` were polluted by flat synthetic feed rows, all fast-money artifacts that include dates after `2026-04-23 17:05:00` must be rebuilt or audited against `deltascout/research_material/recovered_feed/`.
- Pre-gap conclusions and user-validated chart/context notes remain durable.
- Post-gap quantitative counts and family splits should be treated as provisional until rebuilt from recovered feed and compared against the old outputs.

Next research steps after recovered feed:

1. Rebuild minute datasets and move-first / setup-candidate / setup-cluster / fast-money artifacts using recovered feed where the range overlaps the gap.
2. Compare old vs recovered artifacts to identify which fast-money cases survive real OHLCV reconstruction.
3. Build a "birth features" table around the best surviving impulses: pre-impulse M2.6 density, delta/volume compression or expansion, reject support, adverse-before-1000, session timing, trend/regime context, and PEAK delay.
4. Deduplicate near-identical move windows and keep only the best representative case per local impulse.
5. Promote only repeatable families into formal setup-class candidates; keep borderline rows as review material, not as backtest seeds.

### Post-Recovery Rebuild Through 2026-05-08

Source:

- `bundles/2026-03-17_to_2026-05-08/`
- `reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-05-08.csv`
- `reviews/fast_money_setup_cases_2026-03-17_to_2026-05-08.csv`
- `deltascout/research_material/effective_feed/`

Durable facts:

- The recovered/effective-feed rebuild covers `2026-03-17` through `2026-05-08`.
- Move-first windows increased from `108` to `109`.
- Fast-money setup cases increased from `108` to `109`.
- The only new post-`2026-05-05` fast-money setup case is `2026-05-06_short_fmsc109`.
- `2026-05-06_short_fmsc109` is classified as `C_BARELY_HIT`, `countertrend_stop_sweep`, and `borderline_review`, with best 60m favorable move around `1027`, time to `$1000` of `56` minutes, and adverse before `$1000` of `4`.
- This new case occurs inside the recovered-feed gap, so price/volume/delta are reconstructed market evidence, while funding and liquidation context remain degraded.

Durable interpretation:

- The post-recovery rebuild does not change the main fast-money doctrine or the five user-validated proxy-entry reference cases.
- The new `2026-05-06` case is useful as borderline review material, not as a new strong setup-family seed.
- The next research step remains birth-feature extraction and deduplication around the strongest surviving impulses, with explicit degraded-source labeling for any gap-window evidence.

### Local Refresh Through 2026-05-12

Source:

- `bundles/2026-03-17_to_2026-05-12/`
- `reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-05-12.csv`
- `reviews/fast_money_setup_cases_2026-03-17_to_2026-05-12.csv`

Durable facts:

- The local research package now covers `2026-03-17` through `2026-05-12`.
- Move-first windows increased from `109` to `112` versus the `2026-05-08` package.
- Fast-money setup cases increased from `109` to `112`.
- New cases are `2026-05-10_long_fmsc110`, `2026-05-10_short_fmsc111`, and `2026-05-11_short_fmsc112`.
- All three new cases are classified as `C_BARELY_HIT` and `borderline_review`.
- `2026-05-11 00:28:00` accepted `PEAK_EMIT` joined to the `2026-05-12` close as a plain `SL`.

Durable interpretation:

- The `2026-05-09` through `2026-05-12` extension adds coverage and borderline movement examples, but it does not change the main fast-money research direction.
- The priority remains birth-feature extraction around the strongest surviving impulses, not promotion of the new borderline cases.

---

## 2026-08-20 Loss-Avoidance Lifecycle Review

Sources:

- `reviews/losing_trade_commonality_2026-03-20_to_2026-08-20.md`
- `reviews/loss_avoidance_policy_review_2026-03-20_to_2026-08-20.md`
- `reviews/loss_avoidance_policy_review_2026-03-20_to_2026-08-20.json`
- `shadow_verdicts/2026-08-19_blocked_signal_comparison.md`

Research utility contract confirmed by user:

- `plain SL without TP1` is the loss-avoidance target.
- `TP1 -> SL` is a practical-zero / scratch attempt, including cases where commissions turn a small gross profit into a small net loss.
- `TP1 + TP2 + trailing protection` is the protected winner cohort. Blocking these trades is the main policy error.
- A candidate loss pattern may also match `TP1 -> SL` scratches without invalidating the hypothesis, provided it continues to preserve `TP1 + TP2` winners.

Current signal-joined sample:

- Plain-stop losses: `18` (`16` canonical plus `2` user-confirmed).
- TP1-then-SL scratches: `11`.
- Comparable protected TP1+TP2 controls: `7` of `8` canonical protected trades; one protected trade lacks an accepted-signal join.
- Operator test trades remain excluded.

Working loss-avoidance observation:

- The strongest conservative shadow hypothesis currently flags a signal when either:
  1. the same-side delta candidate is at or below the `50th` percentile of the preceding `24h`; or
  2. trusted `oi_change_60m < 0` and direction-adjusted `buy_sell_delta_pct_240m < 0.06`.
- In the current sample this union matches:
  - `9/18` plain-stop losses;
  - `3/11` TP1-then-SL scratches;
  - `0/7` signal-joined protected TP1+TP2 controls.
- A looser exploratory peak threshold of `<=60th` percentile matches `10/18` plain losses, `5/11` scratches, and `0/7` protected controls, but the extra threshold tuning is more exposed to in-sample overfit.

Interpretation:

- Falling OI alone is not a valid veto. It appears in protected winners and would incorrectly reject valuable trades.
- The more specific failure pattern is a weak delta event, or a local directional impulse occurring while OI is shrinking and broad `240m` direction-adjusted flow remains weak.
- This is descriptively consistent with unwind/covering or short-lived local participation rather than strong new position building, but the causal interpretation is not proven.
- The latest protected `2026-08-18 16:30` long is an important counterexample to any OI-only rule: its `oi_change_60m` was negative, but `directional_delta_240m` was about `+3318`, `directional_delta_pct_240m` was about `11.15%`, and its same-side peak percentile was `93.75`. The conservative union therefore preserves it.

TP1-then-SL commission audit:

- Net PnL after execution commission is known or reconstructed for `6/11` scratches.
- One known case, `EX_EN_1785025567`, had approximately `+3.08 USDC` gross, `4.46 USDC` estimated commission, and `-1.39 USDC` net before unavailable borrow interest.
- This fee-flipped case remains in the scratch/neutral utility bucket; it should not be treated like a full plain-stop loss.

R versus actual-profit correction:

- The executor uses approximately fixed notional, not fixed dollar risk, so normalized R must not be used as a substitute for actual dollar profitability.
- At equal `3000 USDC` notional, the actual `2026-08-18` protected trade produced about `110.38 USDC` gross (`110.32 USDC` from exchange fills).
- The two blocked `2026-08-19` long reconstructions produced about `71.04` and `73.48 USDC` gross despite their higher normalized R caused by tighter initial stops.
- Therefore the first actual trade was materially more profitable; the blocked entries were better in risk geometry, not in total reconstructed dollar profit.

Status and next validation rule:

- Treat both components as separate offline/shadow features, not as a live hard veto.
- Journal the component flags and combined shadow result prospectively for every eligible signal.
- Promotion requires out-of-sample evidence that the rule continues to cover plain losses while producing zero or near-zero matches on TP1+TP2 winners.
- Any future threshold change must be reported separately from the current `50th percentile` and `6%` reference rule to avoid silently fitting the same historical sample.

Corrected dual-feed offline replay:

- Experiment: `backtests/scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v2/`.
- Candidate and shadow features use the recovered/enriched BTCUSDT Futures contour;
  fill, SL, TP, and trailing lifecycle use official Binance Vision BTCUSDC Spot 1m
  OHLC. A frozen exact-signal-minute BTCUSDC/BTCUSDT close ratio converts the USDT
  plan into the execution contour.
- Official execution coverage is `154` complete UTC days (`221,760` bars) with `0`
  gaps and `0` duplicates.
- On corrected PEAK replay, baseline is `35` fills, `-21.06 USDC` net, and `-0.60`
  expectancy per fill. The conservative union blocks `12` fills (`7` plain SL,
  `5` TP1->SL, `0` protected); the `23` kept fills produce `+175.42 USDC` net and
  `+7.63 USDC` expectancy per fill.
- Component A alone blocks `4` PEAK fills (`3` plain, `1` scratch, `0` protected),
  leaving `+48.43 USDC` / `+1.56` per fill. Component B alone blocks `10` (`6`
  plain, `4` scratch, `0` protected), leaving `+164.99 USDC` / `+6.60` per fill.
- Operational cross-check on `28` comparable non-test accepted PEAK trades: `13`
  plain SL with `6` union flags, `8` TP1->SL with `3` flags, and `7` protected with
  `0` flags. Replay/operational lifecycle mismatch by operational class is `1/13`,
  `4/8`, and `0/7`, respectively.
- The `2026-04-23 08:45 UTC` PEAK short is blocked and now replays as `TP1_SL`, not
  protected; operationally it was `PLAIN_SL`. The remaining difference comes from
  plan-level entry/stop/target parity, not a Futures wick entering Spot execution.
- The ALMOST 2/3 transfer fails the protected-winner guardrail: the union blocks
  `32/45` replay-protected outcomes, and kept expectancy deteriorates to `-5.52`
  USDC/fill. The PEAK-derived rule must not be applied to ALMOST candidates.
- Earlier single-feed results, including `v5`, are superseded for lifecycle and
  expectancy conclusions. This remains offline evidence only; no live logic changed.

Legacy 180-minute Executor parity on the exact Spot reference contour (2026-09-02):

- Canonical experiment:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v4/`.
- The VPS legacy aggregator archive was copied read-only and normalized from its
  `Europe/Bratislava` local timestamps to UTC. Treating those timestamps as UTC was
  proven invalid and produced a discarded shifted diagnostic.
- A parity defect was fixed locally: real trades are now joined to PEAK candidates
  by signal time/side before fill evaluation. Replay `NO_FILL` is retained as an
  execution mismatch instead of disappearing from the denominator.
- `34` non-test operational trades join to PEAK candidates. The replay fills `29`;
  among those, lifecycle parity is `28/29`: real `13 / 9 / 7` versus replay
  `12 / 10 / 7` for Plain SL / TP1->SL / protected. Protected parity is `7/7`.
- The sole filled mismatch is `2026-08-07 19:37 UTC`: real Plain SL versus replay
  TP1->SL. Replay TP1 is `$61.26` below the live TP1 while the initial-stop difference
  is only `$0.86`, so this is entry/target snapshot geometry rather than the 180m stop.
- Five additional matched real trades are `NO_FILL` in replay. This confirms a fill
  model gap, but not an unconditional-fill rule. Live used `LIMIT_THEN_MARKET` with a
  90-second timeout, `max_dev=0.25R`, a past-TP1 veto, and required current bid/ask;
  replay currently terminates after two unfilled one-minute bars.
- The operational journal contains two confirmed `ABORT_deviation_too_large`
  examples: `2026-04-16` (`dev=600.55`, `max_dev=249.94`) and `2026-06-24`
  (`dev=152.63`, `max_dev=139.97`). Therefore remaining replay no-fills must be
  evaluated through the guards, not automatically changed to fills.
- Replay agrees on no-fill for `2026-04-16`, but incorrectly fills the canceled
  `2026-06-24` candidate and records Plain SL / `-31.44 USDC`. Thus the aggregate
  `+25.39 USDC` includes at least one known false replay trade.
- Full independent PEAK result on this contour is `48` candidates / `37` fills /
  `16 / 10 / 11`, `+25.39 USDC`, `+0.69 USDC/fill`, PF `1.046`. Do not treat these
  economics as final until the guarded live entry fallback is implemented in replay.
- Detailed evidence:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v4/real_trade_parity_analysis.md`.

Guarded 90-second Plan B parity follow-up (2026-09-02):

- Canonical experiment:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v7_planb_guarded/`.
- `LIMIT_THEN_MARKET_90S_GUARDED_V0_1` implements the live decision ordering:
  LIMIT window, required timeout price, `0.25R` maximum deviation, past-TP1 veto,
  then MARKET or ABORT. It persists fill method, proxy, deviation, threshold, risk,
  and abort reason per trade.
- One-minute OHLC cannot provide the exact 90-second bid/ask. The frozen proxy uses
  the first complete post-signal minute for LIMIT touch and the second post-signal
  minute open for the timeout price. Partial fills, late fills during cancellation,
  cancel-confirmation polling, book spread, and market slippage remain outside the
  historical model.
- Independent PEAK result is `48` candidates / `46` fills / `20 / 14 / 12`,
  `-42.16 USDC`, `-0.92 USDC/fill`, PF `0.939`, max DD `$238.52`. Fill decisions
  are `33` LIMIT, `13` Plan B MARKET, and `2` deviation ABORT; no past-TP1 abort
  appears in this sample.
- The `13` Plan B MARKET rows contribute `-126.70 USDC`; the `33` LIMIT rows
  contribute `+84.54 USDC`. Nine newly filled former no-trades contribute
  `-64.37 USDC`. Therefore the earlier v4 `+25.39 USDC` result is superseded, not
  confirmed.
- All `34` matched, non-test, actually opened real trades now fill in replay;
  lifecycle parity is `33/34` (`97.1%`), with the existing `2026-08-07 19:37 UTC`
  Plain-SL versus TP1-SL mismatch unchanged.
- The two recorded live entry cancellations expose the remaining boundary.
  `2026-04-16` agrees (live and replay both deviation ABORT). `2026-06-24` does not:
  live entry `62808.66` was below the `11:50` low `62941.67` and then failed the
  guard, while replay entry `62979.83` was touched by that low and falsely filled
  before Plan B. Replaying the live plan with the `11:51` open proxy produces the
  correct abort (`$154.83 > $139.97`).
- The next material parity problem is exact live planned-entry reconstruction and
  minute-touch timing. Relaxing the Plan B guard would not fix the June case.
- Detailed evidence:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v7_planb_guarded/planb_replay_analysis.md`.

V8 volume-backed structural stop on the guarded BTCUSDC contour (2026-09-02):

- Canonical experiment:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/`.
- This is the first controlled Executor-faithful comparison of the frozen V8 stop
  against the old stop with all other major replay choices held constant: normalized
  legacy BTCUSDT Spot structure, signal-minute BTCUSDT-to-BTCUSDC conversion,
  official BTCUSDC Spot lifecycle, and guarded 90-second Plan B. No A/B admission
  filter was applied.
- Independent V8 result is `48 / 47 / 20 / 9 / 18`, `+153.84 USDC`,
  `+3.27 USDC/fill`, PF `1.199`, max DD `$228.23`. Entry decisions are `33` LIMIT,
  `14` Plan B MARKET, and one deviation ABORT.
- The old `180m Close` stop on the identical contour produced `46` fills,
  `20 / 14 / 12`, and `-42.16 USDC`. V8 improves net by `+196.00 USDC`; Plain-SL
  count remains `20`, while protected outcomes rise by six.
- Position-locked V8 is only marginally positive: `36` fills, `16 / 7 / 13`,
  `+13.72 USDC`, PF `1.021`, max DD `$177.03`. This is much better than the old-stop
  `-265.32 USDC`, but not a robust portfolio edge by itself.
- The edge is regime-concentrated: pre-`2026-06-01` is `23` fills / `-110.52 USDC`,
  and the later slice is `24` fills / `+264.37 USDC`. LONG contributes `+23.22`; SHORT
  contributes `+130.62`.
- The former `+184.78 USDC` V8 result was BTCUSDT-only and LIMIT-only. For execution
  economics it is superseded by this `+153.84 USDC` BTCUSDC/Plan-B result.
- Old-trade lifecycle parity must not be used to reject the new stop: changing initial
  risk changes TP and SL geometry by design. The `33/34` live parity remains evidence
  that the old-stop replay baseline is credible, not that the V8 counterfactual must
  reproduce old live outcomes.
- Detailed evidence:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/v8_planb_result.md`.

Current live A/B admission applied to V8 BTCUSDC/Plan-B (2026-09-02):

- Candidate IDs join `48/48` between the Executor-faithful V8 outcome run and the
  frozen enriched-feed A/B feature run. This separation is necessary because the
  legacy structural feed has no OI for component B.
- Runtime semantics are `A_fail OR B_fail` veto with unknown fail-open. A matches
  `8`, B matches `15`, overlap is `5`, and the union rejects `18` candidates. Four
  B values are unknown and remain admitted.
- Independent kept result is `30` candidates / `29` fills / `11 / 4 / 14`,
  `+275.51 USDC`, `+9.50/fill`, PF `1.662`, max DD `$163.58`. The blocked 18 fills
  contribute `-121.67 USDC`; four are protected outcomes.
- Re-sequencing the one-position portfolio after admission gives `24` fills,
  `9 / 4 / 11`, `+141.60 USDC`, `+5.90/fill`, PF `1.389`, max DD `$117.17`.
  This supersedes any simple subtraction from the unfiltered portfolio because
  rejected candidates no longer occupy the position slot.
- Filtered chronology is positive on both frozen slices: pre-`2026-06-01` is
  `15` fills / `+34.81 USDC`; later is `14` fills / `+240.71 USDC`. The later-period
  concentration and small denominators remain material limitations.
- A fail-closed “both explicitly known pass” sensitivity removes the four unknown-B
  candidates and produces `25` independent fills / `+280.52 USDC`; it is not the
  current live rule and must not be presented as deployed behavior.
- Detailed evidence:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/v8_live_ab_filter_result.md`.

Local PEAK filter integration and shared-policy parity:

- WP1-WP4 are implemented locally under rule ID
  `DS_PEAK_LOSS_AVOIDANCE_UNION_V1`; no server files, container configuration, or
  live runtime mode were changed.
- DeltaScout now has explicit `off`, `shadow`, and `veto` paths. The default is
  `off`; unknown or unhealthy inputs fail open, an audit write must succeed before
  veto, and five consecutive would-block decisions open the circuit breaker.
- `PEAK_LOSS_FILTER_REJECT` preserves the complete would-be PEAK payload. The
  candidate compiler maps it back into the PEAK baseline cohort with
  `FILTER_REJECTED` admission status, so prospective blocks remain replayable.
- Shared-kernel control experiment:
  `backtests/scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v3_shared_policy/`.
  It exactly reproduces the v2 loss-avoidance metrics: PEAK union blocks `12/35`
  filled opportunities (`7` plain SL, `5` TP1->SL, `0` protected), while the `23`
  kept fills retain `+175.42 USDC` net and `+7.63 USDC/fill` expectancy.
- This parity closes local implementation drift only. It does not satisfy the
  prospective shadow promotion gates and does not authorize live veto.

VPS activation record, 2026-08-20:

- Following explicit operator authorization, DeltaScout was deployed directly in
  `veto` mode with rule `DS_PEAK_LOSS_AVOIDANCE_UNION_V1`.
- Backup before activation:
  `/root/volume-alert/backups/deltascout_loss_filter_20260820T1720Z`.
- The enriched SHI feed is mounted read-only; filter state has a dedicated writable
  mount. Executor, Buyer and n8n were not restarted.
- Initial post-recreate verification showed DeltaScout running with restart count
  `0`; both legacy and enriched feeds continued updating to the same minute.
- The recommended prospective shadow observation was bypassed by explicit operator
  direction. This activation is therefore operationally live but still requires
  prospective monitoring; it is not new evidence that the historical edge has
  generalized.
- The initial empty-cache warmup design was corrected after operator review. The
  existing DeltaScout `DELTA_MAX/MIN` archive is the canonical peak-history source;
  `loss_filter_state.json` is only a bounded, rebuildable runtime cache.
- On startup the VPS now reconstructs the exact trailing 24-hour window from the
  archive. First production verification recovered `17` extrema with status
  `ARCHIVE_BOOTSTRAPPED`, so component A no longer waits 24 hours after restart.
- Component B remains eligible only with an exact, contiguous, real enriched-feed
  window.

---

## 2026-09-01 V8 24-Hour Volume-Swing Initial Stop

Sources:

- `backtests/scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed/volume_swing_summary.md`
- `backtests/scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed/run_manifest.json`
- `backtests/scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed/independent_trades.csv`
- `backtests/scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed/portfolio_trades.csv`

Frozen policy:

- Policy ID: `V8_VOLUME_SWING_24H_LR25_BUFFER50_CAP1200`.
- For each already-valid PEAK, inspect the preceding `1,440` one-minute BTCUSDT
  bars and find direction-appropriate strict fractal swings with `25` bars on both
  sides. Right-side confirmation must be complete before the signal, so the
  selector has no post-signal lookahead.
- Synthetic rows cannot define or confirm a swing.
- LONG stop is `swing Low - $50`; SHORT stop is `swing High + $50`. The existing
  0.2% far-stop floor remains active.
- Discard swings whose finished stop is more than `$1,200` from planned entry, then
  choose the remaining swing with the highest one-minute volume; break an equal-
  volume tie in favor of the most recent swing.
- A candidate is blocked if the full 24-hour window is unavailable or no swing
  survives. There is no fallback to the current executor stop.
- Each replay row persists the selected swing timestamp, extreme, volume, eligible
  count, and confirmed count for audit.

Scope and provenance:

- Cohort: `PEAK_EMIT_BASELINE` only, `48` candidates and `35` independent fills.
- Candidate range: `2026-03-20` through `2026-08-25`; frozen signal/execution feed:
  `2026-03-18` through `2026-08-25`.
- V8 uses the BTCUSDT USD-M Futures signal and execution contour with identity price
  conversion. This experiment does not reconstruct BTCUSDC Spot execution.
- Fixed `3,000` quote-notional, pinned cost/fill/trailing rules, and conservative
  same-bar stop-first handling.
- Canonical run fingerprint:
  `460289254c776cc07a79a79bc6ded407294da2545f671fc9f864d9782957e4b4`.

Independent result without A/B filters:

- The primary result was run with **no loss filter A or B**: `48` candidates,
  `35` fills, `17` plain SL, `8` TP1-to-SL scratches, and `10` protected outcomes.
- Net PnL is `+184.78 USDC`, expectancy is `+5.28 USDC/fill`, profit factor is
  `1.342`, and maximum drawdown is `$210.42`.
- Current V8 `180m Close / $0` stop baseline on the same cohort produced `35` fills,
  `17 / 6 / 12` lifecycle counts, `-59.81 USDC`, `-1.71 USDC/fill`, PF `0.892`,
  and `$286.46` maximum drawdown.
- The blanket `240m Low/High + $50` variant produced `35` fills, `17 / 7 / 11`,
  `-71.85 USDC`, `-2.05 USDC/fill`, PF `0.888`, and `$382.27` maximum drawdown.
- Relative to the current stop, the 24-hour volume-swing policy improves net by
  `$244.59` and reduces maximum drawdown by `$76.04`.
- Plain-SL count remains `17` and protected outcomes fall from `12` to `10`.
  Therefore the improvement comes from changed stop/target payoff geometry and
  outcome magnitude, not from converting more trades into protected winners.

Independent A/B admission counterfactual:

| Admission policy | Blocked candidates / fills | Kept candidates / fills | SL / TP1-SL / protected | Net PnL | Expectancy/fill | PF | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| No filter | 0 / 0 | 48 / 35 | 17 / 8 / 10 | +$184.78 | +$5.28 | 1.342 | $210.42 |
| Block on A_fail only | 8 / 5 | 40 / 30 | 14 / 8 / 8 | +$92.37 | +$3.08 | 1.202 | $200.93 |
| Block on B_fail only | 15 / 11 | 33 / 24 | 11 / 6 / 7 | +$116.23 | +$4.84 | 1.338 | $120.60 |
| Block on A_fail OR B_fail (live rule) | 18 / 13 | 30 / 22 | 9 / 6 / 7 | +$189.35 | +$8.61 | 1.700 | $120.60 |
| Block only when A_fail AND B_fail | 5 / 3 | 43 / 32 | 16 / 8 / 8 | +$19.26 | +$0.60 | 1.036 | $200.93 |

Filter interpretation:

- In the implementation, `A=True` and `B=True` mean that the corresponding loss
  blocker matched; they do not mean that a trade passed a filter. Live admission
  blocks on `A_fail OR B_fail`, which is equivalent to requiring
  `A_pass AND B_pass` when both inputs are known. Unknown inputs are fail-open/kept.
- The live union has the strongest expectancy and drawdown in the independent
  counterfactual, but it blocks `3/10` replay-protected outcomes.
- The `13` blocked fills collectively contributed only `-4.56 USDC` under the new
  stop policy, so the union improves net PnL only slightly from `+184.78` to
  `+189.35 USDC`. The larger expectancy gain mainly reflects fewer kept fills.
- These filter results are an independent-opportunity counterfactual. A filtered
  one-position portfolio has not been re-sequenced and must not be inferred from
  this table.

Chronology and swing audit:

- Without filters, the pre-`2026-06-01` slice had `16` fills, `+47.19 USDC`, and
  `+2.95 USDC/fill`; the later slice had `19` fills, `+137.59 USDC`, and
  `+7.24 USDC/fill`.
- With the live A-or-B veto, the corresponding slices were `12` fills /
  `+107.60 USDC` / `+8.97` and `10` fills / `+81.75 USDC` / `+8.17`.
- All `48` candidates had a full window and at least one eligible swing. The
  `$1,200` cap removed individual distant swings but rejected no complete candidate
  in this sample.
- Selected swing age ranged from `25` to `1,382` minutes, with median `696.5`.
  Selected one-minute volume ranged from `80.484` to `2,669.996`, with median
  `615.551`.
- Filled initial stop distance ranged from `$130.04` to `$1,199.84`, with median
  `$760.96`. The maximum verifies that the `$1,200` cap is applied after the `$50`
  structural buffer and 0.2% far-stop floor.

Position-locked portfolio replay:

- The unfiltered one-position replay produced `28` fills; `10` otherwise fillable
  candidates were position-lock blocked.
- Lifecycle counts were `13` plain SL, `7` TP1-to-SL, and `8` protected outcomes.
- Net PnL was `+102.07 USDC`, expectancy `+3.65 USDC/fill`, PF `1.229`, and maximum
  drawdown `$166.24`.
- The current 180-minute portfolio baseline was `-94.00 USDC` with `$285.42`
  maximum drawdown.

Durable interpretation and limitation:

- This is the first tested structural initial-stop variant to improve both the
  full-history independent and position-locked V8 PEAK results relative to the
  current stop. The blanket four-hour extreme did not improve results.
- This is promising but in-sample evidence from only `35` independent fills. The
  policy was developed after inspecting later trades, including the `2026-08-18`
  case, so the post-`2026-06-01` rows are descriptive and are not an untouched
  validation set.
- Keep the policy frozen and record prospective shadow selections before considering
  executor promotion. No current result authorizes a live stop-policy change.
- Implementation remains an opt-in local backtester path. The offline backtester
  suite passed `47` tests; no Executor, Buyer, VPS, or live DeltaScout stop behavior
  was changed.

---

## 2026-09-05 ALMOST 2/3 Volume-Fail with V8 24h Volume-Swing Stop

Sources:

- `backtests/scout_almost_peak_v8_volume_swing_24h_lr25_buffer50_cap1200_full_feed_v3_final/`
- `backtests/scout_almost_peak_v8_volume_swing_24h_lr25_buffer50_cap1200_full_feed_v3_final/almost_volume_fail_volume_swing_result.md`

Frozen comparison:

- The counterfactual applies the PEAK-derived `1,440m`, strict `25/25`,
  Low/High, `$50` buffer, `$1,200` cap, highest-volume initial-stop selector to
  all `256` ALMOST 2/3 candidates on the same BTCUSDT contour as the prior
  180m-close comparison run.
- Candidate range is `2026-03-20` through `2026-08-25`; discovery ends before
  `2026-06-01T00:00:00Z` and validation starts at that boundary.
- All candidates have a selected eligible swing. No candidate falls back to the
  old stop, and no comparison classification is invalid or ambiguous.

Primary result:

- `ALMOST_2OF3_VOLUME_FAIL` keeps the same `75` candidates and `51` fills but
  changes from `20 / 13 / 17` Plain SL / TP1->SL / protected and `+154.05 USDC`
  (`+3.02/fill`) under the 180m-close stop to `28 / 12 / 10` and `-365.54 USDC`
  (`-7.17/fill`) under the 24h volume-swing stop.
- Net deterioration is `-$519.59`; median initial risk expands from `$422.29` to
  `$660.64`.
- Discovery changes from `+51.76` to `-251.10 USDC`; validation changes from
  `+102.29` to `-114.44 USDC`. The degradation therefore has the same sign on
  both sides of the frozen boundary.
- SHORT deteriorates from `+63.39` to `-261.06 USDC`; LONG deteriorates from
  `+90.66` to `-104.47 USDC`.
- The narrow `LONG + current volume > 50 + component-B veto` cohort changes from
  `17` fills, `+130.19 USDC`, and `+7.66/fill` to `-196.08 USDC` and
  `-11.53/fill`. Both its discovery and validation slices turn negative.

Lifecycle interpretation:

- Eleven previously protected Volume-fail outcomes become non-protected, while
  only four previously non-protected outcomes become protected.
- The wider structural stop moves 1R/2R targets farther away and increases
  fixed-notional loss magnitude. For this ALMOST entry family, isolated saved
  stopouts do not compensate for reduced target reach.
- The audited `2026-08-18 05:44 UTC` LONG is genuinely improved from Plain SL
  `-14.22` to protected `+16.62`, but the cohort-level result rejects using one
  saved example as a stop-policy justification.

Durable verdict:

- Reject the frozen PEAK 24h highest-volume swing stop as a replacement for the
  current 180m-close research stop on `ALMOST_2OF3_VOLUME_FAIL`.
- The proposed `LONG + volume > 50 + B veto` lane is specifically weakened, not
  strengthened, by the new stop.
- Stop policy and setup family interact materially. The positive PEAK result does
  not transfer to ALMOST Volume-fail, and no live logic change is authorized by
  this offline run.

Other 2-of-3 isolated completeness check:

- Separate Price-fail and VWAP-fail runs were replayed with explicit cohort
  selectors under both the 180m-close control and the frozen 24h volume-swing
  stop. Their independent results reproduce the matching full-run slices.
- Price-fail changes from `42` fills, `-266.58 USDC`, and `-6.35/fill` to
  `-17.07 USDC` and `-0.41/fill`. Discovery remains `-168.98 USDC`, while the
  `29`-fill validation slice becomes `+151.91 USDC` (`+5.24/fill`). The
  improvement is concentrated in LONG (`-192.01` to `+68.37 USDC`); SHORT
  remains negative. Treat this as a regime-dependent research anomaly, not an
  edge or promotion candidate.
- VWAP-fail changes from `74` fills, `-338.78 USDC`, and `-4.58/fill` to
  `-347.39 USDC` and `-4.69/fill`. Discovery improves but remains negative;
  validation deteriorates from `-186.89` to `-260.97 USDC`. Its previously
  positive SHORT slice changes from `+108.00` to `-84.60 USDC`.
- Cohort-isolated one-position portfolio runs hit the declared state-unknown
  boundary after untrusted post-entry feed coverage. Price-fail blocks `40`
  later candidates after `2026-06-11 17:29 UTC`; both VWAP runs block `51`
  after `2026-06-14 14:43 UTC`. Portfolio totals are therefore truncated
  diagnostics; independent-opportunity results remain primary.
- Detailed comparison:
  `backtests/scout_almost_peak_v8_volume_swing_24h_lr25_buffer50_cap1200_full_feed_v3_final/other_2of3_isolated_volume_swing_result.md`.
- Combined verdict across all three 2-of-3 families: strongly harmful for
  Volume-fail, mixed and chronology-dependent for Price-fail, and non-improving
  for VWAP-fail. No live logic change is authorized.

A-or-B pre-replay filter check:

- The two other 2-of-3 cohorts were rerun in isolation after applying the frozen
  `A_fail OR B_fail` veto before both independent and one-position replay. Only
  definite `true` decisions are blocked; unknown/untrusted values remain admitted
  fail-open. The final runs use the same merged VPS feed snapshot through
  `2026-08-25` as the unfiltered comparison.
- Price-fail keeps `30/70` candidates and `21` fills after blocking `40`
  candidates. The 180m control produces `12 / 5 / 4` Plain / TP1->SL / protected,
  `-146.87 USDC`, and `-6.99/fill`; the 24h volume-swing stop produces
  `13 / 3 / 4`, `-235.02 USDC`, and `-11.19/fill`. The new stop is worse by
  `-88.15 USDC`.
- The filter reverses the earlier unfiltered Price-fail anomaly: it improves the
  old stop by `+119.71 USDC` but worsens the new stop by `-217.94 USDC`. Its
  validation slice changes from `+29.09` under the old stop to `-56.36 USDC`
  under the new stop. The filter and stop policy interact materially.
- VWAP-fail keeps `48/111` candidates and `29` fills after blocking `63`.
  The 180m control produces `16 / 5 / 6`, `-201.49 USDC`, and `-6.95/fill`;
  the 24h volume-swing stop produces `18 / 3 / 6`, `-224.38 USDC`, and
  `-7.74/fill`. The new stop is worse by `-22.89 USDC`.
- A-or-B improves VWAP-fail versus no filter under both stops, but both remain
  negative. Its positive validation slice has only `11` fills and is offset by
  strongly negative discovery.
- Verdict: reject the frozen 24h volume-swing stop for A-or-B-filtered Price-fail
  and VWAP-fail. Do not combine the unfiltered Price-fail lead with the A-or-B veto.
  No live rule change is authorized.
- Detailed comparison:
  `backtests/scout_almost_peak_v8_volume_swing_24h_lr25_buffer50_cap1200_full_feed_v3_final/other_2of3_a_or_b_filtered_volume_swing_result.md`.

---

## 2026-09-13 Blocked-PEAK Counterfactual Durability and VPS Archive Check

Implementation:

- The offline candidate compiler now accepts a durable
  `PEAK_LOSS_FILTER_DECISION` with `effective_action=BLOCK` as a fallback source
  when the subsequent `PEAK_LOSS_FILTER_REJECT` row is missing.
- An explicit reject remains the primary source. Decision fallbacks and rejects
  share the same PEAK identity key, so the normal two-row audit sequence compiles
  to exactly one `PEAK_EMIT_BASELINE` candidate with `FILTER_REJECTED` admission.
- Regression coverage proves both decision-only recovery and decision-plus-reject
  deduplication.

Read-only VPS archive check from the 2026-08-20 veto activation through
2026-09-13:

- Active DeltaScout container reports `LOSS_FILTER_MODE=veto`.
- The container archive contains `2` `PEAK_LOSS_FILTER_DECISION` rows:
  one `KEEP` and one `BLOCK`.
- The kept signal was a LONG at `2026-08-31 08:58 UTC`; A and B were both false,
  and the PEAK was emitted.
- The blocked signal was a LONG at `2026-09-04 08:39 UTC`, price
  `81118.467283`. Component A was true at same-side 24h percentile `25.0`;
  component B was false. The archive contains both the decision and its matching
  `PEAK_LOSS_FILTER_REJECT` with the complete `would_be_peak` payload.
- Therefore one PEAK has been rejected since activation, and there are currently
  no observed decision-only gaps requiring fallback recovery.

### 2026-09-13 Counterfactual outcome of the first live-blocked PEAK

- Canonical experiment:
  `backtests/scout_peak_rejected_2026-09-04_0839_live_agg_reference_v1/`.
- The one blocked candidate was replayed with the deployed V8 structural initial
  stop, guarded 90-second Plan B entry, the historical Executor AGG structural
  contour, and the official Binance Vision BTCUSDC Spot execution contour.
- Replay filled the LONG by LIMIT at `81074.48` and placed the initial BTCUSDC stop
  at `80513.53`; TP1 was `81705.31`.
- TP1 was not reached. The highest pre-stop high was `81420.81`; the candle opened
  at `2026-09-04 12:30 UTC` crossed the stop with a low of `80175.41`.
- Outcome: `PLAIN_SL` at completed-minute timestamp `2026-09-04 12:31 UTC`.
  With the frozen `3000 USDC` notional and cost model, net PnL is `-25.80 USDC`
  before borrow interest (`-20.76` gross, `-4.45` commission, `-0.60` modeled
  adverse slippage).
- Conservative stop-first and target-first sensitivity agree, with no same-bar
  collision. The official Spot source has complete `1440/1440` daily coverage and
  no gaps or duplicates for every normalized day from `2026-09-01` through
  `2026-09-12`.
- The lifecycle conclusion is robust, but exact PnL remains model-based because
  one-minute OHLC cannot reconstruct the historical live bid/ask and exact fill.
- Detailed Ukrainian note:
  `backtests/scout_peak_rejected_2026-09-04_0839_v8_planb_counterfactual_v1/rejected_peak_result_uk.md`.

### Reversal-short annotation for the same episode

- Research label:
  `REVERSAL_SHORT_CANDIDATE / POSSIBLE_LONG_EXHAUSTION`.
- Replaying the same timestamp with direction changed from the emitted LONG thesis
  to an artificial SHORT gives a LIMIT fill at `81108.44`, V8 initial stop
  `81680.40`, TP1 `80536.48`, and TP2 `79964.52` when the historical Executor AGG
  structural contour is used.
- The ordinary 1m replay reports `TP1_SL` / `+2.09 USDC` because the crash candle
  contains both its pre-drop high and its later TP1 crossing. This is an OHLC
  ordering ambiguity, not reliable evidence of a post-TP1 return to breakeven.
- Checksum-verified official Binance Vision BTCUSDC aggregate trades resolve the
  sequence: TP1 first crossed at `2026-09-04 12:30:13.268065 UTC`, TP2 at
  `12:31:35.410754 UTC`, and no trade returned to the `81108.44` breakeven after
  TP1 during the rest of the UTC day. The initial stop was not touched before TP1.
- Splitting only that collision minute at the audited TP1 trade confirms that the
  third leg survives through TP2. Under the actual deployed Executor trailing
  contract (`240/LR25`, buffer `50`, step `25`, confirmation buffer `20`), the
  third leg exits at `79612.50` at completed-minute `16:33 UTC`; modeled net is
  `+34.77 USDC` on `3000 USDC` notional.
- Interpretation: this episode is consistent with a weak LONG PEAK marking
  exhaustion, but one post-hoc example cannot authorize an inverse-entry rule.
  Test the complete future blocked-A cohort symmetrically before considering a
  detector or live change.
- Detailed note and reproducible intraminute inspector:
  `backtests/scout_peak_rejected_2026-09-04_0839_reverse_short_v8_planb_v1/`.

### Trailing parity correction found during the reversal audit

- `VOLUME_SWING_24H_LR25` is the initial V8 stop (1,440 rows, strict 25/25
  swings, highest-volume eligible swing). The active trailing path is separate:
  `AGG`, lookback `240`, `LR=25`, buffer `50`, step `25`, confirmation buffer
  `20`, update interval `60s`.
- The first reversal run's `80012.19` stop was invalid. It came from backtester
  defaults `LR=2`, step `20`, confirmation buffer `0` and the wrong structural
  feed.
- Current Executor env and both pre-V8 deployment backups carry the same deployed
  trailing values. `SWING_MINS=180` is wired to the legacy initial-stop helper,
  not to trailing; treating it as the trailing lookback was an audit error.
- This is confirmed by actual execution evidence, not config alone. Six archived
  `TRAIL_SL_UPDATED` prices from the 2026-08-19 LONG (`67775`, `67992`, `68054`,
  `68574`, `68930`, `69110`) each exactly equal the contemporaneous LR25 swing low
  minus `$50`; the rolling-180m values differ at every event.
- The canonical Executor-parity result is therefore `79612.50` / completed minute
  `16:33 UTC` / `+34.77 USDC`. The discarded rolling-180 calculation is not an
  Executor result.
- The backtester defaults and CLI were aligned to the deployed `240/LR25/50/25/20`
  contract on 2026-09-13. Full reports created earlier with implicit
  `240/LR2/50/20/0` trailing defaults remain non-parity and require a new run;
  forensic artifacts are not overwritten.
- Detailed diagnosis and reproducible comparison against live August stop events:
  `backtests/scout_peak_rejected_2026-09-04_0839_reverse_short_v8_planb_v1/trailing_parity_audit_uk.md`.

### 2026-09-13 Filter-B-only rejected PEAK audit

- Executor-parity replay selected 10 real `PEAK_EMIT_BASELINE` candidates from
  2026-03-20 through 2026-08-25 with component B true and component A false.
- In the original PEAK direction all 10 filled: eight ended `PLAIN_SL`, two ended
  `TP1_TP2_TRAILING_STOP`, and aggregate modeled net PnL was `-$167.04`.
- The two profitable signals incorrectly vetoed by B-only were the 2026-05-08
  17:31 UTC LONG (`+$39.43`) and 2026-06-11 23:41 UTC LONG (`+$80.67`).
- Reversing B-only is not supported as a rule: nine reversals filled, aggregate
  modeled net PnL remained negative at `-$52.67`; one candidate was blocked by
  `NO_CONFIRMED_VOLUME_SWING`.
- The B-only veto therefore avoided a net-negative original cohort. The raw
  independent A+B slice is `+$76.62`, but its two protected winners (`+$96.23`
  and `+$100.38`, both 2026-08-19) were already unavailable because the
  2026-08-18 LONG occupied the Executor slot. After position-lock-first
  attribution, the A+B veto-eligible slice is three `PLAIN_SL` fills totaling
  `-$119.99`; independent-opportunity and portfolio-attributed claims must not be
  mixed.
- Reproducible artifact:
  `backtests/scout_peak_filter_b_original_executor_parity_2026-09-13_v1/`.

---

## Update Rule

Update this file only when a workflow produces durable research conclusions.

Do not update this file for routine sync, rebuild, or bundle generation unless the interpretation changed.

## 2026-10-02 — LONG 0.50–0.69 strategy checkpoint

### Scope and frozen policy

This checkpoint consolidates the imbalance-band study, all configured detector
gates, the A-or-B veto, Executor single-position replay, and the resolved organic
trade of 2026-10-01/02 into one strategy result.

- LONG imbalance: 0.50–0.69.
- SHORT imbalance: 0.54–0.69.
- Comparison, EMA/VWAP regime, VWAP side, CHOP and COH gates enforced.
- Loss avoidance: `DS_PEAK_LOSS_AVOIDANCE_UNION_V1`, A-or-B veto, unknown values
  kept fail-open.
- Executor V15 single-position portfolio, structural initial stop capped at
  1200 USD, frozen trailing and cost settings from the run manifest.
- Manual mechanics tests excluded by exact trade key through
  `D:/Project_V/Executor/backtests/TEST_TRADE_EXCLUSIONS.csv`.

### Why LONG 0.50 was retained

The study tested baseline 0.54–0.69, lower 0.45–0.69, upper 0.54–0.75, and
combined 0.45–0.75 variants. Keeping SHORT at 0.54 and lowering LONG to 0.50
was the strongest tested asymmetric policy: +393.46 USDC versus baseline
+230.14 USDC, an improvement of +163.32 USDC with the same modeled maximum
drawdown of 108.84 USDC. Lowering SHORT to 0.50 reduced the portfolio to
+170.86 USDC. Relaxing CHOP/COH reduced the selected-policy result to +142.45
USDC and raised maximum drawdown to 195.92 USDC. The checkpoint therefore keeps
CHOP/COH and the asymmetric imbalance limits unchanged.

### Unified result

The deterministic single-position portfolio through 2026-09-27 produced 27
filled positions: 16 reached at least TP1 and 11 ended in Plain SL. A
current-code verification on 2026-10-02 reproduced every economic row: TP1
hit rate 16/27 = 59.26%, Plain SL 11/27 = 40.74%, net +393.46 USDC, maximum
drawdown 108.84 USDC. Lifecycle split was 5 `TP1_SL`, 11
`TP1_TP2_TRAILING_STOP`, and 11 `PLAIN_SL`; LONG was 12/20 TP1-positive and
SHORT was 4/7 TP1-positive.

The next resolved policy-valid single-position episode was organic LONG
`EX_EN_1790867120`. DeltaScout emitted it at 2026-10-01 15:05 UTC with imbalance
0.626 after exact A PASS and B PASS. Executor filled at 84213.50, reached TP1
85118.61 and TP2 86023.73, then closed the remaining leg through the trailing
stop at 85845.36 on 2026-10-02. Executor reported approximate net
+47.05517603555 USDC. A second LONG PEAK one minute later occurred while this
position was already active and is not another filled episode. The trade is not
in the manual-test exclusion list.

The dated checkpoint is therefore **28 resolved filled positions**, counted once
per single-position episode:

| Metric | Result |
|---|---:|
| Reached at least TP1 | **17/28 = 60.71%** |
| Plain SL | **11/28 = 39.29%** |
| Positive : negative | **17:11 = 1.55:1** |
| Calendar scope | 2026-03-17 through 2026-10-02 |
| Approximate frequency | **4.26 fills/month** |

This checkpoint combines 27 deterministic portfolio outcomes with the next one
durable live outcome under the same policy. Preserve the provenance, but count
the live trade as part of this single strategy result rather than as a separate
study. When a future expanded replay includes the 2026-10-01 signal, replace its
current live bridge and do not count it twice.

Evidence:

- `D:/Project_V/Executor/backtests/imbalance_045_075_through_2026-09-27_v1/report_uk.md`;
- `D:/Project_V/Executor/backtests/imbalance_045_075_through_2026-09-27_v1/runs/long_lower_050_currentcode_20261002_v1/`;
- `D:/Project_V/Executor/backtests/imbalance_045_075_through_2026-09-27_v1/chop_coh_backtest_analysis.json`;
- `D:/Project_V/Executor/server_journals/2026-10-02/state/trade_outcomes.jsonl`;
- `D:/Project_V/Executor/server_journals/2026-10-02/state/trade_execution_snapshots.jsonl`;
- `D:/Project_V/Executor/server_journals/2026-10-02/deltascout/2026-10-01.jsonl`;
- `D:/Project_V/Executor/LOG.md` entry for `EX_EN_1790867120`.

Review again on **2027-03-02** using evidence through 2027-03-01. Compare filled
count, TP1-positive rate, Plain-SL rate, LONG/SHORT split, net PnL, maximum
drawdown, monthly frequency, A/B blocked count, and any policy/runtime changes.
No production configuration, services, state, or orders were changed.


### Post-cutoff candidate inventory used by this checkpoint

- 2026-09-28: no `PEAK_EMIT`; the two imbalance gate rejects were outside the
  retained asymmetric bands (LONG 0.411 and SHORT 0.757).
- 2026-09-29: 17 DELTA extrema, all rejected; no `PEAK_EMIT` or A/B decision.
  The only CHOP/COH reject was SHORT imbalance 0.314 and would also fail the
  active SHORT minimum 0.54.
- 2026-09-30: 16 DELTA extrema, all rejected at comparison: 11
  `direction_mismatch`, 3 `vwap_side`, and 2 `3of3_fail`; no gate reject,
  `PEAK_EMIT`, or A/B decision.
- 2026-10-01: two adjacent LONG `PEAK_EMIT` rows at 15:05 and 15:06 UTC, both
  A/B KEEP, formed one single-position episode. The first produced organic trade
  `EX_EN_1790867120`; the second is not another fill.
- 2026-10-02 archive checked through 10:05 Bratislava/Budapest local time: no
  additional `PEAK_EMIT` in the checked portion.

Daily archive snapshots and the durable trade journals remain under
`D:/Project_V/Executor/server_journals/`. These inventory facts support the
single added filled episode; they are not separate strategy studies.

\n