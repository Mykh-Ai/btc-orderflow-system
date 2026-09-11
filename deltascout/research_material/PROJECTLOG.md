# DeltaScout Project Log

## 2026-09-11 — LLM entry boundary, A/B provenance, and v39A monitor deployment

- Runtime subsystem/game name: `LLM Trade Judge Game`; the advisory component is
  `LLM Trade Judge`. Production mode is `openai`, configured model `gpt-5.5`.
- DeltaScout PEAK events now carry additive `loss_filter_admission` provenance:
  filter A and B status, purpose, evaluated conditions, and overall
  `KEEP/BLOCK/UNKNOWN`. The LLM is not given an unexplained “A/B passed” phrase.
- Executor now builds `LLM_ENTRY_SNAPSHOT_V2` and renders
  `LLM_ENTRY_PROMPT_V2`. The model-facing prompt contains entry-time signal,
  A/B admission meaning, initial execution geometry, and monitor evidence. It
  excludes orders/order ids, outcome, PnL, position-management state, and
  trailing-stop data.
- Added and deployed opt-in `market_monitor_snapshot_v39a` with exact closed UTC
  5/15/30/60/240/1440-minute windows, missing/duplicate checks, future-row
  exclusion, per-window RAW/RECOVERED quality, source lineage, and atomic state
  carry-forward across calls and UTC midnight. Existing v1/37E state and zones
  remain the explicitly labelled underlying monitor source.
- Production flags enable v39A and persist state at
  `/data/state/market_monitor_state_v39a.json`. Final real-feed smoke cutoff was
  `2026-09-11T15:10:00Z`: all six windows complete, zero future rows, state
  continuity `CONTINUOUS_CARRY_FORWARD`.
- Validation: `58 passed` in the targeted Executor/DeltaScout/monitor suite;
  deployed hook and v39A module hashes matched local files. Commit `9825123`
  was pushed to `codex/scout-replay-backtester-v0-1` for the entry boundary,
  v39A adapter, hook, tests, and runbook. DeltaScout A/B runtime changes remain
  separate uncommitted working-tree changes and were not folded into that commit.
- No entry, SL/TP, trailing, order-management, or PnL policy changed in this
  deployment. The LLM remains a one-time advisory entry-quality verdict.

## 2026-09-09 — LLM monitor runtime audit and offline data boundary

- Read-only runtime audit: 24 verdict records through 2026-08-31; 20 success,
  4 errors; 16 monitor snapshots / 9 repaired 37E states. No new verdict after
  the current V8 process start on 2026-09-03. Historical exact prompts and
  execution-policy/code hashes are not journaled and remain unknown.
- All 33 monitor files plus the judge match the Aug20 copy. Current process
  initial stop is V8 1440/LR25/$50/cap1200. **Trailing differs from prior frozen
  research settings:** current LR25/step25/confirm20, research LR2/step20/confirm0.
  Preserve old PnL/early-exit results as their own configuration; rebuild a
  separate current-config baseline before further PnL attribution.
- Added research-only `monitor_feed_contract.py`, snapshot CLI, runbook and
  17 passing tests. Exact 5/15/30/60/240/1440 windows, explicit SHI UTC flush-close
  labels, complete HTF bars, row quality, nullable enrichment and recovery-v2
  hashes. No live hook/model call/deployment, no AiTrader raw/mirror changes.
- Actual 2026-07-26 00:26 control: 60m/240m coverage improves 27→60/240 rows;
  240m delta imbalance changes +32.01%→+7.56%. Numerical input correction,
  not evidence of forecast or trading edge. Snapshot live eligibility is false.
- Artifacts/report: `reviews/llm_monitor_runtime_2026-09-09/report_uk.md`.
  Next narrow work: 39A-reviewed chronological closed-H1 state/level bridge,
  then explicit forecast/evidence v2 and separate calibration/utility checks.

## Purpose

This is the human entrypoint for the local DeltaScout research workspace.

Read this file first when you need to understand:

- what the latest operational state is;
- which date range is covered locally;
- where the latest usable bundle is;
- which workflow prompt to run next;
- which artifacts are machine outputs rather than human memory.

This file is operational memory. Durable research conclusions belong in `RESEARCHLOG.md`.

---

## Current State

Last updated: 2026-09-08

### Step 3 first early-exit hypothesis tested and rejected — 2026-09-08

- Frozen rule: each completed minute from age 60, before TP1, actual-fill MFE
  >=0.5R, directional execution close <=0R, opposing last-15-minute reference
  delta. Exit at next Open; no maximum age, threshold search, or runtime change.
- New additive builder: `deltascout/research_bundle/build_early_exit.py`.
  Runbook: `docs/runbooks/deltascout_early_exit_research.md`.
- Verified 636 frozen inputs and replay code; reproduced both corrected
  baselines before applying the rule and recomputing portfolio admission.
- A/B portfolio: 21 -> 22 fills, net `233.5086 -> 143.7044 USDC`, closed-trade
  drawdown `87.8964 -> 109.7581 USDC`; 9 early exits.
  Common-trade change `-45.0125`, added April 11 SHORT `-44.7916`;
  total change `-89.8041 USDC`. No-filter portfolio also deteriorated.
- Result rejects this fixed policy on the inspected sample. Do not tune its
  thresholds after the fact and present them as validated. Existing live
  management stays unchanged; broader early-exit hypotheses remain untested.
- Evidence: `reviews/early_exit_failed_impulse_2026-09-08_v1/report_uk.md`,
  `analysis.json`, `protocol.json`, `replay_events.json`, `experiment_manifest.json`.
  104 tests passed; exported quantities/costs/PnL reconcile for 127 filled
  scenario records. No server operations, source archive edits or commits.

### May 4 entry anomaly closed; recovery and execution clocks corrected — 2026-09-08

- The anomaly was offline: recovery joined Bratislava-local legacy timestamps to
  UTC SHI without conversion. In addition, official Spot open-time labels were
  compared with SHI/legacy completed-minute labels, leaking the next Spot close.
  Both clocks are corrected; trailing Low/High logic and all strategy parameters
  are unchanged. Runtime/VPS/AiTrader files were not changed.
- Real May 4 SHORT remains verified from raw `trade_outcomes.jsonl`: actual entry
  `78814.69`, protective SL `79923.07`. New V8 replay entry `78823.71`, SL
  `79317.85`, `TP1_SL`, net `+1.3672 USDC`. This replay is a policy counterfactual,
  not a reconstruction of that historical live order stream.
- Current corrected recovery/effective inputs:
  `recovery_clock_v2_2026-09-08/recovered_feed/`, `effective_feed/`, `quality/`.
  Old recovery and frozen snapshots are preserved for audit and are superseded
  for recovery-window economics. There are `19067` recovered minutes, `1093`
  preserved SHI rows, and no missing source minutes after clock normalization.
- Canonical new no-filter experiment:
  `backtests/scout_peak_v8_clock_corrected_2026-09-08/`.
  Independent: `48` candidates, `44` fills, `23 / 8 / 13`, net `-14.81`,
  PF `0.983`, max DD `284.47`. Portfolio: `32` fills, `16 / 8 / 8`,
  net `-119.14`, PF `0.823`, max DD `297.23` USDC.
- Canonical new A/B experiment:
  `backtests/scout_peak_v8_clock_corrected_2026-09-08_live_ab/`.
  Independent: `30` candidates, `26` fills, `9 / 8 / 9`, net `+206.49`,
  PF `1.577`, max DD `126.83`. Portfolio: `21` fills, `6 / 8 / 7`,
  net `+233.51`, PF `1.930`, max DD `87.90` USDC.
- Post-fill wrong-side initial SL now fails the replay rather than inventing a
  profitable SL or hiding exposure as NO_TRADE. `80` targeted tests passed;
  the exact old May 4 anomaly was reproduced and rejected by the new invariant.
- Evidence, exact commands, hashes, and trade-by-trade comparison:
  `reviews/entry_anomaly_2026-05-04_audit_2026-09-08/report_uk.md`.
  Only step 1 was performed. Old derived studies using the recovery window need
  their own rebuild before reuse; the AiTrader mirror is not clock-corrected here.

### Trade development at 240 and 1440 minutes — 2026-09-08

- New checkpoint dataset and workbook:
  `reviews/trade_development_2026-09-08_h1440_v1/` and
  `outputs/01a07785-f5ae-71b2-bd60-b0c48f8c8036/trade_development_2026-09-08_h1440_v1.xlsx`.
- The analysis keeps terminal labels separate from as-of measurements. It records
  realized legs, mark-to-market remainder, incurred costs, estimated remaining exit
  cost, market MFE/MAE, position MFE/MAE lower bounds, signed delta response and
  initial-swing structure state at 5/15/30/60/240/1440 minutes.
- A/B one-position portfolio (21 fills): median position net if closed now is
  `-0.027R` at 240 minutes and `+0.152R` at 1440 minutes. By lifecycle at 1440:
  `PLAIN_SL -1.158R`, `TP1_SL +0.162R`, `TP2/trailing +1.349R`.
- These are retrospective outcome groups, not exit-policy tests. Market MFE may
  include post-exit movement; position PnL is frozen after closure. The positive
  240-minute median of eventual TP2/trailing trades does not mean they had reached
  TP2 at that time: only 2/7 had reached TP1. At 60 minutes, 6/7 still had no TP1.
- A read-only diagnostic of open pre-TP1 trades with price <= entry and signed
  cumulative delta <= 0 selects 2 eventual plain SL, 3 TP1_SL and 2 TP2/trailing
  at 60 minutes in the A/B portfolio; at 240 minutes it selects 2/2/3. This does
  not establish profitable early exits or a benefit from longer holding. Step 3
  must evaluate an as-of rule and resequence the portfolio with changed exits.
- At 1440 minutes, one A/B portfolio reference window is incomplete. Across all
  cohorts, incomplete windows are retained as unavailable. No zero or future price
  substitutes are used. See the report's horizon section for the full table and
  definitions.

### Full V8 trailing parity in BTCUSDT -> BTCUSDC replay — 2026-09-06 (economics superseded by clock correction)

- Canonical no-filter experiment:
  `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_trailing_parity_v2/`.
- Canonical current live-A/B experiment:
  `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_live_ab_trailing_parity_v2/`.
- The replay trailing model now matches the deployed Executor's market-data
  semantics: LONG swings use BTCUSDT `LowPrice`, SHORT swings use BTCUSDT
  `HiPrice`, BTCUSDT `ClosePrice` is used only for the post-activation confirmation
  break, and each successful trail quote receives a fresh historical same-minute
  `BTCUSDC close / BTCUSDT close` conversion with the `[0.95, 1.05]` sanity band.
  The converted stop is rounded outward, checked against the BTCUSDC price, and
  compared with the active stop in BTCUSDC units.
- No-filter independent result: `48` candidates / `46` fills / `24 / 6 / 16`,
  `+181.55 USDC`, `+3.95/fill`, PF `1.22`, max DD `$239.87`. No-filter
  one-position portfolio: `35` fills / `19 / 5 / 11`, `+18.16 USDC`,
  `+0.52/fill`, PF `1.027`, max DD `$193.64`.
- Current live A/B result (`A_fail OR B_fail` rejects; both filters must pass):
  `30` candidates / `28` independent fills / `12 / 5 / 11`, `+280.61 USDC`,
  `+10.02/fill`, PF `1.76`, max DD `$127.90`. Re-sequenced filtered portfolio:
  `24` fills / `10 / 5 / 9`, `+253.04 USDC`, `+10.54/fill`, PF `1.821`,
  max DD `$87.74`.
- Relative to the 2026-09-05 replay, lifecycle counts are unchanged. All `16`
  protected independent trades receive corrected trailing prices; aggregate net
  decreases by `$27.39` without filters and `$14.00` with live A/B.
- The 2026-09-05 `*_corrected_v1` figures are now superseded for economics because
  their initial V8 structural selection was correct but their trailing fractal
  still used execution-feed closes. No Executor, VPS, container, or live
  configuration was changed by this offline correction.

### Corrected V8 BTCUSDT structural selection -> BTCUSDC execution — 2026-09-05 (superseded trailing model)

- Corrected no-filter experiment:
  `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_corrected_v1/`.
- Corrected live-A/B experiment:
  `backtests/scout_peak_v8_btcusdt_structural_selection_to_btcusdc_execution_live_ab_corrected_v1/`.
- The structural candle is selected once on the canonical BTCUSDT enriched feed,
  the completed USDT entry/SL/TP plan is converted at the signal snapshot, and
  only the resulting BTCUSDC levels are replayed on official BTCUSDC Spot.
  Structural parity with the canonical USDT V8 run is `48/48`; timestamp, swing
  price, swing volume, and `initial_stop_price_usdt` have zero mismatches.
- Corrected no-filter independent result: `48` candidates / `46` fills /
  `24 / 6 / 16`, `+208.94 USDC`, `+4.54/fill`, PF `1.256`, max DD `$239.75`.
  Corrected unfiltered one-position portfolio: `35` fills / `19 / 5 / 11`,
  `+30.23 USDC`, `+0.86/fill`, PF `1.045`, max DD `$193.64`.
- Corrected current live A/B result: `30` candidates / `28` independent fills /
  `12 / 5 / 11`, `+294.61 USDC`, `+10.52/fill`, PF `1.795`, max DD `$127.77`.
  Re-sequenced filtered portfolio: `24` fills / `10 / 5 / 9`, `+267.09 USDC`,
  `+11.13/fill`, PF `1.867`, max DD `$87.74`.
- The previous `scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1`
  experiment and its `v8_live_ab_filter_result.md` are superseded for V8 economics:
  they reselected the structural swing on normalized legacy BTCUSDT Spot instead
  of preserving the candle selected on the canonical enriched BTCUSDT feed.
  Their `+153.84` no-filter and `+275.51` filtered figures must not be cited as
  current V8 results.
- This was an offline research-input correction. The deployed Executor already
  selects the swing from its BTCUSDT `aggregated.csv` before converting the finished
  plan to BTCUSDC, so no live code, configuration, container, or VPS state changed.

### V8 with current live A/B admission — 2026-09-02

- Filter analysis:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/v8_live_ab_filter_result.md`.
- Current runtime semantics were preserved: reject on `A_fail OR B_fail`; unknown
  inputs fail open. A blocks `8`, B blocks `15`, overlap is `5`, union blocks `18`
  and keeps `30` of `48` candidates.
- Independent kept result: `30` candidates / `29` fills / `11 / 4 / 14`,
  `+275.51 USDC`, `+9.50/fill`, PF `1.662`, max DD `$163.58`. The `18` blocked
  fills contribute `-121.67 USDC` under the V8 counterfactual.
- Re-sequenced one-position portfolio: `24` fills / `9 / 4 / 11`,
  `+141.60 USDC`, `+5.90/fill`, PF `1.389`, max DD `$117.17`; five eligible
  candidates are position-blocked and one accepted candidate aborts entry.
- Four B values are unknown and admitted by live fail-open behavior. A separate
  fail-closed sensitivity is slightly stronger but is not the deployed policy.

### V8 volume-swing stop with guarded Plan B — 2026-09-02

- Canonical experiment:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/`.
- Executor-faithful comparison uses normalized legacy BTCUSDT Spot for the 24-hour
  structural swing, signal-minute conversion into BTCUSDC, official BTCUSDC Spot
  lifecycle, and the guarded 90-second Plan B fill model. No A/B admission filter.
- Independent result: `48` candidates / `47` fills / `20 / 9 / 18`,
  `+153.84 USDC`, `+3.27/fill`, PF `1.199`, max DD `$228.23`.
- On the identical contour, the old `180m Close` stop was `-42.16 USDC`; V8 improves
  net by `+196.00 USDC`, with unchanged Plain-SL count but six more protected
  outcomes.
- Position-locked portfolio improves from `-265.32` to `+13.72 USDC`; max drawdown
  falls from `$358.12` to `$177.03`.
- Stability remains weak: pre-`2026-06-01` is `-110.52 USDC`, while the later slice
  is `+264.37 USDC`; most net comes from SHORT. Treat as in-sample, regime-
  concentrated support for prospective shadowing, not deployment authorization.
- Detailed report:
  `backtests/scout_peak_v8_volume_swing_btcusdc_spot_reference_planb_guarded_v1/v8_planb_result.md`.

### Guarded 90-second entry fallback replay — 2026-09-02

- Canonical experiment:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v7_planb_guarded/`.
- Backtester fill model `LIMIT_THEN_MARKET_90S_GUARDED_V0_1` now records LIMIT,
  Plan B MARKET, and explicit ABORT decisions. Frozen live guards are `0.25R`, no
  absolute-dollar override, required price, and past-TP1 veto.
- One-minute limitation is explicit: first complete post-signal bar is the LIMIT
  window and the second bar open is the 90-second executable-price proxy. Historical
  bid/ask, partial fills, and cancel races are not reconstructed.
- Independent PEAK result: `48` candidates / `46` fills / `20 / 14 / 12`,
  `-42.16 USDC`, `-0.92 USDC/fill`, PF `0.939`; `33` LIMIT fills, `13` Plan B
  MARKET fills, and `2` deviation aborts.
- All `34` matched actually-opened real PEAK trades now fill in replay and lifecycle
  matches `33/34`. The five former false replay no-fills are resolved.
- Known cancellation parity is `1/2`: `2026-04-16` aborts correctly; `2026-06-24`
  still falsely fills because replay rebuilt entry `62979.83` instead of live
  `62808.66`, causing the minute low to touch only the replay limit. The remaining
  defect is planned-entry snapshot parity, not the Plan B guard.
- The earlier LIMIT-only `+25.39 USDC` economics are superseded. Detailed analysis:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v7_planb_guarded/planb_replay_analysis.md`.
- Offline tests: `57 passed`. No VPS, live Executor, Buyer, or DeltaScout runtime
  behavior was changed.

### Superseded LIMIT-only legacy 180m parity control — 2026-09-02

- Canonical audit:
  `backtests/scout_peak_real_parity_btcusdc_180m_close_spot_reference_v4/`.
- Read-only VPS legacy BTCUSDT aggregator history was normalized from local
  `Europe/Bratislava` timestamps to UTC and paired with official BTCUSDC Spot 1m
  execution bars.
- Stable signal-first parity join finds `34` non-test real PEAK trades. Replay fills
  `29`; lifecycle matches `28/29`, including `7/7` protected outcomes. One filled
  mismatch remains (`2026-08-07 19:37 UTC`, real Plain SL versus replay TP1->SL).
- Five real trades are false `NO_FILL` outcomes in replay because live Executor uses
  a guarded `LIMIT_THEN_MARKET` fallback after 90 seconds while the current replay
  only checks two limit-touch bars. The guard is dynamic `0.25R`, not a fixed `$200`,
  and also rejects execution past TP1 or without current bid/ask.
- Two confirmed operational Plan B cancellations are preserved: `2026-04-16`
  (`$600.55 > $249.94`) and `2026-06-24` (`$152.63 > $139.97`). Replay no-fills
  must therefore be classified through the guards rather than filled unconditionally.
- The current replay agrees on `2026-04-16` no-fill but falsely fills the canceled
  `2026-06-24` entry as Plain SL (`-31.44 USDC`), so aggregate economics contain a
  known false trade until Plan B parity is implemented.
- Full independent result is `48` candidates / `37` fills / `16 / 10 / 11`,
  `+25.39 USDC`; economics are provisional until the entry fallback is modeled.
- No VPS runtime file or configuration was changed.

### Executor V8 initial-stop and quote synchronization — 2026-09-02

- Technical contract:
  `docs/Executor_V8_Initial_Stop_USDT_USDC_Spec_v0_1.md`.
- Local Executor now selects the frozen V8 initial stop from an exact 1,440-row
  BTCUSDT window ending at the exact signal minute: strict 25/25 LowPrice/HiPrice swings, greatest
  one-minute TotalQty, `$50` structural buffer, existing 0.2% far-stop floor, and
  `$1,200` finished-distance cap. Missing window or eligible swing rejects the
  candidate without legacy fallback.
- Initial entry/SL/TP geometry remains in BTCUSDT and is converted as one plan to
  BTCUSDC with a frozen entry-time `BTCUSDC_mid / BTCUSDT_mid` ratio.
- USDT-derived trailing swings now receive a fresh BTCUSDC/BTCUSDT conversion before
  every BTCUSDC activation, restoration, or update. The converted stop must also be
  on the protective side of current BTCUSDC mid before cancel/replace.
- Quote-sync failure retains the existing protective trailing stop; a raw BTCUSDT
  level is never sent as a BTCUSDC order price. Conversion inputs and selected
  structural swing fields are persisted for audit.
- Targeted Executor and Scout replay validation passed: `57` tests and exact
  structural selection parity on `48/48` canonical V8 PEAK candidates. No
  VPS/container/runtime deployment was performed during this phase; activation
  followed separately on 2026-09-03.

### Executor V8 VPS activation — 2026-09-03

- The first attempted full-file activation exposed source drift: the local
  single-file snapshot lacked newer modular live-runtime integrations and booted
  with `dry=true`. It was immediately rolled back from the exact pre-change backup
  while the position remained null; it was never enabled for live order placement.
- V8 was then re-applied as a narrow merge on top of the current VPS Executor
  source. The final deployment changed only `/root/volume-alert/executor.py`,
  `/root/volume-alert/executor_mod/market_data.py`, and the explicit V8 keys in
  `/root/volume-alert/.executor.env`.
- Final backup:
  `/root/volume-alert/backups/executor_v8_20260903T025903Z`.
- Deployed hashes:
  `executor.py = 3442decee0b5017fab1216153944ab9f80434cfb5ca4c4fe637f53a7d90a1e82`;
  `market_data.py = 35e524d398f57d83debc14b138365b32a1e7a4042b6e570e07fedc59cc5ee318`.
- Merged-runtime validation passed: syntax compile, `12/12` targeted tests, and
  exact V8 structural parity on `48/48` canonical candidates. A current live-feed
  snapshot loaded all 1,500 rows and supplied a full gap-free 1,440-row window.
- Only the `executor` container was recreated. Post-start state was
  `running`, restart count `0`, `TRADE_MODE=margin`, `SYMBOL=BTCUSDC`,
  `ENTRY_MODE=LIMIT_THEN_MARKET`, and `position=null`. DeltaScout and SHI
  Aggregator were not restarted.
- After activation, the local production snapshot was brought forward to the same
  modular source: `executor/executor.py` plus 27 Python modules under
  `executor_mod/`. Local hashes for `executor.py` and `market_data.py` exactly match
  the deployed runtime hashes. The superseded local single-file V8 source is kept
  only in `deployment_staging/executor.local_stale_v8.py` for forensic comparison.

### V8 structural initial-stop research — 2026-09-01

- Canonical experiment:
  `backtests/scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed/`.
- The tested policy is `V8_VOLUME_SWING_24H_LR25_BUFFER50_CAP1200`: use the
  highest-volume confirmed 25/25 swing in the preceding 24 hours, place the
  structural stop $50 beyond its low/high, and admit only finished stop distances
  no greater than $1,200. A full 24-hour window and at least one eligible swing are
  required; no fallback is used.
- Scope is V8 `PEAK_EMIT_BASELINE` on the BTCUSDT Futures signal/execution contour,
  fixed 3,000 quote-notional, conservative same-bar stop-first handling, and the
  frozen feed snapshot through `2026-08-25`.
- The primary `+184.78 USDC` result is explicitly the **no-A/B-filter** independent
  replay: `48` candidates, `35` fills, `17` plain SL, `8` TP1-to-SL scratches, `10`
  protected outcomes, `+5.28 USDC/fill`, PF `1.342`, and `$210.42` maximum drawdown.
- Current V8 initial-stop baseline (`180m Close`, no buffer) produced `-59.81 USDC`
  with `$286.46` maximum drawdown. The blanket `240m Low/High + $50` experiment was
  also negative at `-71.85 USDC` with `$382.27` maximum drawdown.
- The separate live-admission counterfactual blocks when `A_fail OR B_fail`, which
  is equivalent to admitting only `A_pass AND B_pass` when both inputs are known.
  Unknown B is fail-open/kept. It retained `30` candidates / `22` fills and
  produced `+189.35 USDC`,
  `+8.61 USDC/fill`, PF `1.700`, and `$120.60` maximum drawdown. It blocked `13`
  otherwise filled opportunities, including `3` protected outcomes; their combined
  no-filter contribution was only `-4.56 USDC`, so net improvement over no filter is
  small.
- The position-locked portfolio replay was run without A/B filtering: `28` fills,
  `13 / 7 / 8` plain-SL / TP1-SL / protected, `+102.07 USDC` net,
  `+3.65 USDC/fill`, PF `1.229`, and `$166.24` maximum drawdown. Filtered portfolio
  sequencing has not been recomputed.
- All `48` candidates had a complete window and an eligible swing. Filled initial
  stop distance ranged from `$130.04` to `$1,199.84`, confirming that the cap is
  applied after the buffer and existing 0.2% far-stop floor.
- The policy is implemented only as an opt-in local backtester variant and its
  offline test suite passes (`47` tests). Executor, Buyer, VPS configuration, and
  live stop placement were not changed.
- This is promising in-sample structural-stop evidence, not authorization for live
  deployment. The hypothesis was shaped after reviewing later trades, including
  `2026-08-18`; future frozen shadow decisions are required for out-of-sample
  validation.

### Live PEAK loss-filter rollout — 2026-08-20

- VPS DeltaScout is running in `veto` mode with rule
  `DS_PEAK_LOSS_AVOIDANCE_UNION_V1`; Executor remains on its existing execution
  code and receives only admitted PEAK bus events.
- A would-be PEAK is vetoed when component A or component B is definitely true,
  inputs are trustworthy, the decision audit append succeeds, and the circuit
  breaker is closed. Any missing/invalid data or audit failure is fail-open.
- Every evaluated would-be PEAK is archived as `PEAK_LOSS_FILTER_DECISION`. A
  successful veto also writes `PEAK_LOSS_FILTER_REJECT` with the complete
  `would_be_peak` payload. The candidate compiler maps it back to
  `PEAK_EMIT_BASELINE` with `FILTER_REJECTED` status for BTCUSDC Spot replay.
- The canonical component-A history source is the existing append-only DeltaScout
  `DELTA_MAX/MIN` archive. `loss_filter_state.json` is only a bounded runtime cache
  and is rebuilt/merged from the exact trailing 24-hour archive window on startup.
  First production bootstrap recovered `17` extrema with
  `ARCHIVE_BOOTSTRAPPED`, so A does not require a new 24-hour warmup after restart.
- DeltaScout, Executor and Buyer were verified running with restart count `0` after
  deployment. Legacy and enriched feeds continued updating to the same minute.
- n8n workflow `DeltaScout` remains active and healthy. Telegram
  `appendAttribution` was explicitly set to `false`, removing the automatic n8n
  footer/link from future delta notifications.
- No post-rollout final PEAK had yet produced a live
  `PEAK_LOSS_FILTER_DECISION/REJECT` at the last verification. Review each of the
  first five live vetoes individually and preserve their counterfactual outcomes.
- Server rollback backups:
  - `/root/volume-alert/backups/deltascout_loss_filter_20260820T1720Z`;
  - `/root/volume-alert/backups/deltascout_archive_bootstrap_20260820T1735Z`;
  - `/root/volume-alert/backups/n8n_delta_scout_no_attribution_20260820T2010Z`.
- Runtime was deployed from the current local working tree. The related changes
  have not yet been committed or pushed to GitHub.

Current local review coverage:

- start: `2026-03-17`
- end: `2026-08-18`
- daily review folders: `155`
- missing dates in that span: `0`

Latest full workflow run:

- requested mode: normal latest workflow with no explicit date range
- effective range: `2026-08-05` to `2026-08-18`, excluding the in-progress `2026-08-19` UTC day
- effective mode: inferred `latest_sync`, automatically switched to `cover_missing_days` with a full local offline rebuild
- reason for local rebuild: server raw archive/enriched feed covered the range, but watcher datasets remained stopped after `2026-05-15`; the verified local offline pipeline was used again

Operational result:

- server `post_close_watcher_state.json` remained at `2026-05-15`; the canonical `trade_outcomes.jsonl` reached `2026-08-10`, while DeltaScout raw archive and enriched feed reached `2026-08-19`
- the watcher cron still referenced removed `/opt/aitrader/.venv/bin/python`; this workflow did not repair cron or recreate a host environment
- production `shi-aggregator`, DeltaScout, executor, and related containers were observed running; no container was restarted
- local raw archive/feed synced for `2026-08-05` through `2026-08-18`; the current partial `2026-08-19` enriched feed was synced to `18:43 UTC` with `1124` rows but remains outside review coverage
- `deltascout/research_material/effective_feed/` was extended with normal production feed outside the historical recovery gap
- all `14` inferred missing daily review packages were rebuilt locally with the documented four-step offline pipeline
- review validation passed for the full `155`-day span: every daily folder has all `11` expected non-empty artifacts
- feed validation passed for every added completed day: `1440` rows, `IsSynthetic=0`, positive Close/Volume/AggTrades
- feed validation found one `1439`-minute day (`2026-05-18`) and `24` preserved synthetic/zero-volume rows across `2026-06-04`, `2026-06-11`, `2026-06-15`, `2026-06-25`, `2026-07-02`, and `2026-07-12`
- minute datasets materialized for `2026-08-05` through `2026-08-18`, with `20160` rows in each of base, mechanics, and outcomes and no between-layer count mismatch
- M2.6 process-chain artifacts rebuilt for `2026-03-17` through `2026-08-18`
- standard research bundle and derived discovery surfaces built for `2026-03-17` through `2026-08-18`
- the package is ready for `RUN_LLM_RESEARCH_ANALYSIS.md`; `RESEARCHLOG.md` was not changed because no new durable research conclusion was produced
- no live trading runtime, deployment script, or server collector logic was intentionally changed during this workflow

Follow-up local cleanup on `2026-05-03` did intentionally change local research tooling/tests:

- `deltascout/delta_analyzer/modules/build_review_tables.py`
  - maps `lc_*` close outcome fields into `lifecycle_*` accepted context fields
- `deltascout/research_bundle/build_index_summary.py`
  - reports accepted outcome surface as `SL`, `SL_TP1`, or `SL_TRAILER` when lifecycle fields support it
- `deltascout/test/test_delta_analyzer_phase2_contracts.py`
  - updates the test fixture for the current `EventsBaseRow` comparison-diagnostics contract

No live trading runtime or deployment behavior was intentionally changed.

---

## Latest Usable Artifacts

Latest local bundle:

- `deltascout/research_material/bundles/2026-03-17_to_2026-08-18/`

Main files in that bundle:

- `reviews_2026-03-17_to_2026-08-18_final_research_review.md`
- `reviews_2026-03-17_to_2026-08-18_index_summary.csv`
- `selected_cases_2026-03-17_to_2026-08-18.csv`
- `selected_case_sequence_context_2026-03-17_to_2026-08-18.csv`
- `selected_case_raw_feed_micro_2026-03-17_to_2026-08-18.csv`
- `selected_case_blocker_breakdown_2026-03-17_to_2026-08-18.csv`
- `research_bundle_manifest.csv`

Latest range-specific review:

- `deltascout/research_material/bundles/2026-03-17_to_2026-08-18/reviews_2026-03-17_to_2026-08-18_final_research_review.md`

Latest accepted outcome ledger:

- `deltascout/research_material/reviews/accepted_outcome_ledger_2026-03-17_to_2026-05-02.md`
- `deltascout/research_material/reviews/accepted_outcome_ledger_2026-03-17_to_2026-05-02.csv`

Latest M2.6 artifacts:

- `deltascout/research_material/minute_datasets/m2_6/minute_event_chain_candidates_2026-03-17_to_2026-08-18.csv`
- `deltascout/research_material/minute_datasets/m2_6/minute_event_chain_reference_cases_2026-03-17_to_2026-08-18.csv`
- `deltascout/research_material/minute_datasets/m2_6/chain_cluster_summaries_2026-03-17_to_2026-08-18.csv`

---

## Latest Workflow Counts

For `2026-08-05_to_2026-08-18`, counted directly from local CSV files:

- days: `14`
- accepted rows: `6`
- reject rows: `236`
- interesting reject rows: `174`
- close outcome rows: `3`
- accepted-to-close joined rows: `0`

Full bundle totals for `2026-03-17_to_2026-08-18`:

- accepted rows: `46`
- reject rows: `2800`
- interesting reject rows: `2083`
- close outcome rows: `39`
- accepted-to-close joined rows: `17`

M2.6 row counts for `2026-03-17_to_2026-08-18`:

- chain candidates: `28253`
- reference cases: `5`
- cluster summaries: `6126`

Latest rebuilt bundle status for `2026-03-17_to_2026-08-18`:

- daily folders: `155`
- selected cases: `12`
- sequence context: `complete`, rows `50`
- raw micro: `complete`, rows `705`
- blocker breakdown: `partial`, rows `12`
- missing sequence cases: `0`
- missing raw micro cases: `0`
- accepted outcome surface in index summary now distinguishes `SL`, `SL_TP1`, and `SL_TRAILER` where lifecycle artifacts support it

Latest setup discovery artifacts for `2026-03-17_to_2026-08-18`:

- `deltascout/research_material/reviews/move_first_windows_2026-03-17_to_2026-08-18.csv`
- `deltascout/research_material/reviews/move_first_windows_2026-03-17_to_2026-08-18.md`
- move-first builder: `python -m deltascout.research_bundle.build_move_first_windows --review-root deltascout/research_material/reviews --minute-dataset-root deltascout/research_material/minute_datasets --output-root deltascout/research_material/reviews`
- move-first rows: `246`
- move-first accepted PEAK coverage: `3` with nearby accepted PEAK, `243` without nearby accepted PEAK; all `246` have nearby M2.6 coverage
- `deltascout/research_material/reviews/setup_candidates_2026-03-17_to_2026-08-18.csv`
- `deltascout/research_material/reviews/setup_candidates_2026-03-17_to_2026-08-18_summary.md`
- builder: `python -m deltascout.research_bundle.build_setup_candidates --review-root deltascout/research_material/reviews --minute-dataset-root deltascout/research_material/minute_datasets --output-root deltascout/research_material/reviews`
- rows: `551`
- source split: `15` accepted PEAK lifecycle reference, `504` M2.6 chain candidates, `26` interesting rejects, `6` reject `$1000` follow-through rows

Latest setup cluster review artifacts for `2026-03-17_to_2026-08-18`:

- `deltascout/research_material/reviews/setup_cluster_review_2026-03-17_to_2026-08-18.csv`
- `deltascout/research_material/reviews/setup_cluster_review_2026-03-17_to_2026-08-18.md`
- builder: `python -m deltascout.research_bundle.build_setup_cluster_review --setup-candidates deltascout/research_material/reviews/setup_candidates_2026-03-17_to_2026-08-18.csv --output-root deltascout/research_material/reviews`
- rows: `101`
- status split: `41` candidate setup, `19` candidate setup with reject support, `6` reject follow-through candidate, `20` needs more evidence, `15` reference only

New `2026-05-03_to_2026-05-05` note:

- no new `$1000+` move-first windows, setup candidates, or setup clusters were added under current builders

New `2026-05-06_to_2026-05-08` note:

- one new `$1000+` move-first / fast-money setup case was added: `2026-05-06_short_fmsc109`
- `2026-05-06_short_fmsc109` is inside the recovered-feed gap and is classified as `C_BARELY_HIT`, `countertrend_stop_sweep`, `borderline_review`; use it as review material only and do not use funding/liquidation evidence from this window without degraded-source labeling

New `2026-05-09_to_2026-05-12` note:

- three new `$1000+` move-first / fast-money setup cases were added: `2026-05-10_long_fmsc110`, `2026-05-10_short_fmsc111`, and `2026-05-11_short_fmsc112`
- all three are classified as `C_BARELY_HIT` and `borderline_review`; they add review material but do not change the current top setup-family priorities

Latest top-cluster quantitative pre-review artifacts for `2026-03-17_to_2026-05-02`:

- `deltascout/research_material/reviews/top_cluster_manual_review_2026-03-17_to_2026-05-02.csv`
- `deltascout/research_material/reviews/top_cluster_manual_review_2026-03-17_to_2026-05-02.md`
- builder: `python -m deltascout.research_bundle.build_top_cluster_manual_review --cluster-review deltascout/research_material/reviews/setup_cluster_review_2026-03-17_to_2026-05-02.csv --setup-candidates deltascout/research_material/reviews/setup_candidates_2026-03-17_to_2026-05-02.csv --accepted-ledger deltascout/research_material/reviews/accepted_outcome_ledger_2026-03-17_to_2026-05-02.csv --minute-dataset-root deltascout/research_material/minute_datasets --output-root deltascout/research_material/reviews`
- reviewed clusters: `5`
- all 5 quantified clusters hit `$1000+` favorable movement after representative entry proxy
- this is not manual chart validation; the `T-180m` pre-context window is not an entry window
- user-validated setup-entry confirmation: all 5 reviewed representative proxy entries are valid entry points (`2026-03-23_long_c005`, `2026-03-21_short_c004`, `2026-04-07_long_c025`, `2026-04-16_short_c037`, `2026-04-12_short_c032`); this supersedes the earlier erroneous assistant note that treated `2026-04-16_short_c037` as no-short-only without first asking the user to review the correct time window
- `2026-04-16_short_c037` follow-up: user clarified the proxy entry was a theoretically tradeable counter-trend downside impulse around `15:30`, within broader long-market correction context; around `15:50`, US session/premarket flow swept stops near `73400`, then price reversed higher toward roughly `78300` on `2026-04-17`; preserve this as counter-trend local-short plus broader-long/session-context research context
- broader process-chain clarification: user classified `2026-04-07_long_c025` as the start of the upward reversal / first leg from roughly `68700` to `72700`, followed by a second upward leg toward roughly `76200` by `2026-04-14`, then correction into `2026-04-16_short_c037` until roughly `15:50`
- higher-timeframe regime clarification: user describes the market as probing for bottom/reversal after the major downtrend from roughly `125000` to `60000`, near the `50%` Fibonacci area; globally treat the current environment as sideways/base-building or correction within the larger downtrend. In this frame, `2026-03-23_long_c005` is an early internal long impulse inside the downtrend, `2026-04-07_long_c025` is the first stronger upward-reversal forerunner, and `2026-04-16_short_c037` may be a related opposite-sign counter-trend correction impulse.
- user priority call: all reviewed proxy entries are pre-impulse / "fast money" locations; next research should focus on shared pre-impulse conditions before fast directional moves, not generic continuation labels
- extracted review: `deltascout/research_material/reviews/fast_money_pre_impulse_review_2026-03-17_to_2026-05-02.md`; durable conclusion is to build a fast-money table around M2.6 density, earliest proxy, representative proxy, best proxy, adverse-before-1000, reject support, accepted PEAK timing, session context, and phase labels
- fast-money pre-impulse builder: `python -m deltascout.research_bundle.build_fast_money_pre_impulse_table --review-root deltascout/research_material/reviews --minute-dataset-root deltascout/research_material/minute_datasets --output-root deltascout/research_material/reviews --move-first deltascout/research_material/reviews/move_first_windows_2026-03-17_to_2026-08-18.csv`
- latest fast-money pre-impulse artifacts: `deltascout/research_material/reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-08-18.csv` and `deltascout/research_material/reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-08-18_summary.md`
- latest fast-money pre-impulse counts: `492` proxy rows from `246` move-first windows, including `96` fast-money trigger rows; family split is `243` counter-trend impulse, `81` long forerunner, `40` long pre-impulse, `101` short pre-impulse, and `27` short late-risk rows
- fast-money setup-case builder: `python -m deltascout.research_bundle.build_fast_money_setup_cases --pre-impulse-table deltascout/research_material/reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-08-18.csv --output-root deltascout/research_material/reviews`
- latest fast-money setup-case artifacts: `deltascout/research_material/reviews/fast_money_setup_cases_2026-03-17_to_2026-08-18.csv` and `deltascout/research_material/reviews/fast_money_setup_cases_2026-03-17_to_2026-08-18_summary.md`
- latest fast-money setup-case counts: `246` deduplicated setup cases; quality split is `2` strong impulse, `26` clean scalp, `172` barely-hit/borderline, `11` late/no-edge, and `35` counter-trend sweep cases; review-priority split is `17` top manual review, `26` candidate family review, `20` countertrend review, `11` timing-filter review, and `172` borderline review
- current research thread to resume after feed recovery: movement-first / fast-money pre-impulse discovery. The key question is now what common birth conditions appear before the best fast directional impulses, not whether movement exists. Preserve the user-validated proxy-entry cases (`2026-03-23_long_c005`, `2026-03-21_short_c004`, `2026-04-07_long_c025`, `2026-04-16_short_c037`, `2026-04-12_short_c032`) as the starting manual reference set, but rebuild or audit all post-`2026-04-23 17:05:00` quantitative surfaces against `deltascout/research_material/recovered_feed/` before making new family/count claims.

---

## Known Anomalies

- Resolved production feed-quality anomaly: local `raw_feed` and derived `minute_datasets` from `2026-04-24` through `2026-05-05` were originally polluted by flat synthetic rows (`IsSynthetic=1`, `Volume=0`, constant `Close=77973.5`). The current research rebuild uses `deltascout/research_material/effective_feed/`, with recovered files for the gap and normal production feed outside it.
- Server root-cause check: `/opt/aitrader/feed` is written by Docker container `shi-aggregator` running `/opt/aitrader/binance_aggregator_shi.py`. At `2026-04-23 17:03:09 UTC`, its Binance Futures WS connection logged `Connection to remote host was lost`; it reconnected at `17:04:11`, but after that `aggTrade/markPrice` data stopped updating while REST open-interest polling continued. First synthetic row is `2026-04-23 17:05:00`. Runtime was later fixed to use the routed Binance Futures market stream endpoint, and `2026-05-09` verification showed `shi-aggregator` alive with `WS=OK`, fresh trade/mark ages, and `consecutive_synthetic=0`.
- Recovery source found: the separate runtime archive contour `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv` remained live after `2026-04-23` and contains real `ClosePrice`, `HiPrice`, `LowPrice`, `TotalQty`, `BuyQty`, and `SellQty` rows for `2026-04-24` through at least `2026-05-06`. It lacks enriched fields such as OI/funding/liquidations, so use it as a price/volume/delta recovery source or convert it to an enriched-like research feed before rebuilding minute datasets.
- Feed recovery builder implemented: `python -m deltascout.research_bundle.build_recovered_feed_gap --mirror-output-root D:\Project_V\Aitrader\feed_recovered`. It writes SHI-compatible recovered daily CSVs to `deltascout/research_material/recovered_feed/` and mirrors them to `D:\Project_V\Aitrader\feed_recovered/` without overwriting original raw feeds. Recovery window is `2026-04-23 17:05:00` through `2026-05-06 22:51:00` UTC; latest run wrote `14` daily files / `20160` output rows, with sidecar provenance in `deltascout/research_material/recovery_reports/recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv`. Price/volume/delta are recovered from legacy archive; OI is copied/forward-filled from SHI where possible; funding is schema-fill/untrusted during the WS gap; historical liquidations remain missing.
- `interesting_rejects` is effectively empty for `2026-04-24` through `2026-05-05` while reject rows still exist. Treat this as a coverage or heuristic-output anomaly until verified.
- Accepted/outcome evidence is still sparse. Do not infer profitability from current accepted rows or sparse close joins.
- Close rows must be interpreted by exact artifact fields, not by `close_reason` alone. `close_reason=SL` plus `plain_sl` and no TP/trailing flags is a losing stop; `close_reason=SL` plus trailing lifecycle fields is a protected/profitable trailing stop; `close_reason=SL` plus TP1 fields means TP1 was reached and may be near-breakeven / practical zero. Do not collapse all `SL` rows into one loss bucket.
- Current accepted outcome ledger classifies `15` accepted rows as: `4` plain/normal SL losses, `2` protected/profitable trailing-stop outcomes, `1` manual-confirmed factual `SL` result, `1` user-confirmed `SL` without artifact join (`2026-04-11`), `1` user-confirmed `SL_TP1` without artifact join (`2026-04-09`), `1` no-trade missed entry (`2026-04-16`), and `5` inferred SL outcomes whose close rows exist but lack `peak_ts`. `2026-04-17`, `2026-04-21`, and `2026-04-23` close outcomes are artifact-native in `close_outcomes_*`; accepted context was rebuilt after fixing `lc_*` to `lifecycle_*` propagation. User confirmed `2026-04-11` ended in `SL`, `2026-04-09` is `SL_TP1`, and `2026-04-16` was missed by the bot with no trade opened.
- Bundle markdown files are handoff artifacts. They are not the canonical research memory.

---

## Human Reading Order

For current state:

1. `PROJECTLOG.md`
2. `RESEARCHLOG.md`
3. latest bundle markdown only if deeper analysis is needed
4. CSV artifacts only for verification or drill-down

For agent execution:

1. `runbooks/RUN_AGENT_RESEARCH_WORKFLOW.md`

For deeper LLM or analyst interpretation:

1. `runbooks/RUN_LLM_RESEARCH_ANALYSIS.md`

---

## What To Run Next

Use only these two prompts as normal entrypoints:

- `runbooks/RUN_AGENT_RESEARCH_WORKFLOW.md`
  - Use when new days need to be covered, synced, rebuilt, bundled, or checked.
- `runbooks/RUN_LLM_RESEARCH_ANALYSIS.md`
  - Use when the package is ready and you want strategic research interpretation or next-step recommendations.

Do not manually choose among the deprecated stage prompts unless you are debugging an old workflow.
