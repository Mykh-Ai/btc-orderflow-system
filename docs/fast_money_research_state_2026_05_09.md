# Fast Money Research State: 2026-05-09

This is durable project memory for the research direction that was active before the `2026-04-23` enriched-feed incident became the blocking issue.

## Research Shift

DeltaScout research moved from PEAK/reject-only diagnostics toward movement-first and process-phase discovery.

Current `PEAK_EMIT` remains useful as:

- a reference class;
- a diagnostics surface;
- a contrast against future setup classes.

It is not the boundary of future setup discovery.

The working research order is:

```text
market state -> transition -> process phase -> entry timing
```

## What We Were Searching For

The active question became:

```text
What common birth conditions appear immediately before fast directional BTC impulses?
```

The user described these locations as pre-impulse / "fast money" points.

The target is not more generic long/short continuation labels. The target is a small number of repeatable setup families that can plausibly capture roughly `$1000+` directional BTC movement with explicit trigger grammar, invalidation, stop model, and session/context rules.

## User-Validated Proxy Entry Cases

The user confirmed that all reviewed representative proxy entries are valid entry points:

- `2026-03-23_long_c005`
- `2026-03-21_short_c004`
- `2026-04-07_long_c025`
- `2026-04-16_short_c037`
- `2026-04-12_short_c032`

Important context:

- `2026-03-23_long_c005` is an early internal long impulse inside the broader downtrend, not a confirmed regime flip by itself.
- `2026-04-07_long_c025` is the first stronger upward-reversal forerunner: first leg roughly `68700 -> 72700`, then a second upward leg toward roughly `76200` by `2026-04-14`.
- `2026-04-16_short_c037` is a theoretically tradeable counter-trend downside impulse around `15:30`; around `15:50`, US/premarket flow swept stops near `73400`, then price reversed higher toward roughly `78300` on `2026-04-17`.
- The broader regime was described as bottom/reversal probing after the major downtrend from roughly `125000` to `60000`, near the `50%` Fibonacci area. Treat it as sideways/base-building or correction inside the larger downtrend, not as clean confirmed bullish trend.

## Built Artifacts Before Feed Recovery

The main fast-money artifacts were:

- `deltascout/research_material/reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-05-05.csv`
- `deltascout/research_material/reviews/fast_money_pre_impulse_table_2026-03-17_to_2026-05-05_summary.md`
- `deltascout/research_material/reviews/fast_money_setup_cases_2026-03-17_to_2026-05-05.csv`
- `deltascout/research_material/reviews/fast_money_setup_cases_2026-03-17_to_2026-05-05_summary.md`

Pre-impulse table:

- `216` proxy rows from `108` move-first windows.
- `56` fast-money trigger rows.

Candidate-family split:

- `FAST_MONEY_COUNTERTREND_IMPULSE`: `106`
- `FAST_MONEY_LONG_FORERUNNER`: `49`
- `FAST_MONEY_LONG_PRE_IMPULSE`: `18`
- `FAST_MONEY_SHORT_PRE_IMPULSE`: `35`
- `FAST_MONEY_SHORT_LATE_RISK`: `8`

Setup-case table:

- `108` deduplicated setup cases.

Quality split:

- `A_STRONG_IMPULSE`: `1`
- `B_CLEAN_SCALP`: `6`
- `C_BARELY_HIT`: `78`
- `D_LATE_NO_EDGE`: `7`
- `F_COUNTERTREND_SWEEP`: `16`

Repeatability-family split:

- `countertrend_stop_sweep`: `56`
- `reversal_forerunner`: `23`
- `m2_density_pre_impulse`: `17`
- `late_liquidity_chase`: `7`
- `reject_supported_pre_impulse`: `2`
- `generic_pre_impulse`: `3`

## Current Interpretation

We found movement and candidate families, not finished tradable setup classes.

M2.6 process-chain material is broad enough to see many movement zones. Accepted `PEAK_EMIT` is often absent or late around the strongest movement-first windows.

Many detected moves are borderline and only barely clear the `$1000` threshold. The next stage must separate:

- strong and repeatable impulses;
- duplicate windows around the same local move;
- barely-hit or high-risk moves;
- late/no-edge states;
- true counter-trend stop-sweep families.

## Feed-Recovery Warning

The enriched feed has a known gap from `2026-04-23 17:05:00` through `2026-05-06 22:51:00` UTC.

Any fast-money artifact that includes dates after `2026-04-23 17:05:00` must be rebuilt or audited against recovered feed before new quantitative claims are made.

Use:

- `deltascout/research_material/recovered_feed/`
- `D:\Project_V\Aitrader\feed_recovered\`
- `deltascout/research_material/recovery_reports/recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv`

Do not use original flat synthetic rows in the gap as market evidence.

## Next Research Step

After rebuilding from recovered feed:

1. Rebuild minute datasets and movement/setup/fast-money artifacts for ranges overlapping the gap.
2. Compare old vs recovered fast-money cases and keep only survivors.
3. Deduplicate local impulse duplicates.
4. Build a "birth features" table for the best impulses:
   - M2.6 density;
   - delta/volume compression or expansion;
   - reject support;
   - accepted PEAK delay;
   - adverse-before-1000;
   - stop survival;
   - session timing;
   - regime and process phase.
5. Promote only repeatable families into formal setup-class candidates.
