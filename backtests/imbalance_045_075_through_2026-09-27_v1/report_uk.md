# DeltaScout imbalance 0.45–0.75 + Executor replay

## Scope

- Signal dates: 2026-03-17 through 2026-09-27 inclusive.
- DeltaScout source: production research archive copied read-only from
  `/root/volume-alert/data/archive/deltascout/`.
- Structural feed: production legacy archive through Sep27.
- Signal/enrichment feed: production enriched feed through Sep27, with the
  documented Apr23–May6 recovery files overlaid.
- Execution feed: official Binance Vision BTCUSDC Spot 1m, 195 complete days,
  280,800 unique minutes, zero missing or duplicate minutes.
- Candidate rule: an existing PEAK/A-B record, or a
  `CANDIDATE_GATE_REJECT / imb_band`; other gate rejects are excluded.
- A/B: current `UNION_A_OR_B` policy reapplied before execution replay.
- Executor model: `EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2`, guarded 90-second
  Plan B proxy, V8 volume-confirmed swing stop (1440/LR25/buffer50/cap1200),
  deployed trailing defaults, 3000 USDC fixed notional, commission 0.000744,
  adverse slippage 0/1/2 bps.

The archive contains 3,582 DELTA extrema in scope. There are 148 historical
`imb_band` rejects among 296 gate rejects.

## Candidate counts

| Cohort | Before A/B | LONG | SHORT | Kept after A/B | Integrity-evaluable |
|---|---:|---:|---:|---:|---:|
| Baseline 0.54–0.69 | 56 | 32 | 24 | 34 | 33 |
| Added by lower bound 0.45–<0.54 | 29 | 18 | 11 | 18 | 18 |
| Added by upper bound >0.69–0.75 | 28 | 13 | 15 | 21 | 20 |

The combined policy had 113 pre-A/B candidates; A/B blocked 40 and kept 73.
Ten kept candidates had an unknown union value and remained admitted by the
declared fail-open policy.

Two SHORT candidates in the documented recovered-feed interval are excluded
from economics because the replay integrity guard raised
`INITIAL_STOP_WRONG_SIDE_AFTER_FILL`:

- 2026-04-23 17:41 UTC, high-added cohort;
- 2026-05-04 10:08 UTC, baseline cohort.

They are not forced into wins or losses.

## Independent opportunity results for newly added candidates

| Expansion | Side | Evaluable candidates | Filled | Plain SL | TP1 | TP2 | Net PnL USDC |
|---|---|---:|---:|---:|---:|---:|---:|
| Lower 0.45–<0.54 | LONG | 13 | 11 | 4 | 7 | 5 | **+197.67** |
| Lower 0.45–<0.54 | SHORT | 5 | 3 | 2 | 1 | 0 | **−52.30** |
| Upper >0.69–0.75 | LONG | 11 | 11 | 6 | 5 | 3 | **+60.20** |
| Upper >0.69–0.75 | SHORT | 9 | 9 | 8 | 1 | 0 | **−332.85** |

Independent totals:

- lower expansion: **+145.38 USDC**;
- upper expansion: **−272.65 USDC**.

The lower expansion's positive result comes from LONG. Lower-band SHORT was
negative. The upper expansion is dominated by upper-band SHORT losses: eight
of nine filled SHORTs ended in Plain SL. Upper-band LONG was positive in total,
but six of eleven fills ended in Plain SL.

## Single-position Executor portfolio

| Policy | Evaluable candidates | Filled | Position-blocked | Net PnL USDC | Delta vs baseline | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Baseline 0.54–0.69 | 33 | 23 | 7 | **+230.14** | — | 108.84 |
| Lower only 0.45–0.69 | 51 | 32 | 13 | **+255.49** | **+25.35** | 186.28 |
| Upper only 0.54–0.75 | 53 | 38 | 12 | **+28.88** | **−201.26** | 263.35 |
| Combined 0.45–0.75 | 71 | 44 | 21 | **−0.20** | **−230.34** | 217.32 |
| LONG-only lower: LONG 0.45–0.69, SHORT 0.54–0.69 | 46 | 29 | 12 | **+307.79** | **+77.65** | 159.38 |
| LONG-only lower: LONG 0.50–0.69, SHORT 0.54–0.69 | 39 | 27 | 8 | **+393.46** | **+163.32** | 108.84 |
| SHORT-only lower: LONG 0.54–0.69, SHORT 0.50–0.69 | 36 | 25 | 7 | **+170.86** | **−59.28** | 135.74 |
| Baseline LONG only: LONG 0.54–0.69, SHORT disabled | 19 | 16 | 3 | **+128.77** | **−101.36** | 134.57 |

The portfolio differences include signal competition: a new candidate can hold
the single Executor position and prevent a later baseline trade. Therefore the
portfolio delta is not the sum of independent candidate PnL.

The directional LONG-only lower-bound variant is the strongest tested policy:
it keeps SHORT at the baseline band and admits only the 0.45–<0.54 LONG cohort.
The added LONGs contributed +91.77 USDC inside the portfolio; displacement of
baseline trades reduced the policy-level improvement to +77.65 USDC. Max
drawdown still rose from 108.84 to 159.38 USDC.

Raising the experimental LONG minimum from 0.45 to 0.50 removed the weakest
part of the added cohort. Three of four Plain SL outcomes in the original
0.45–<0.54 independent cohort occurred below 0.50 (imbalances 0.464, 0.481 and
0.496); the remaining Plain SL was at 0.524. With LONG 0.50–0.69 and SHORT
unchanged at 0.54–0.69, portfolio net rose to +393.46 USDC, +163.32 versus
baseline, while max drawdown stayed at the baseline 108.84 USDC.

The 0.50 policy added six post-A/B LONG candidates: four portfolio fills, one
position-blocked candidate and one no-fill. Their direct portfolio net was
+130.56 USDC. The changed position timeline added another +32.76: it avoided a
baseline -58.33 Plain SL but admitted a previously blocked baseline LONG that
lost -25.57.

The symmetric SHORT follow-up did not support lowering the SHORT minimum to
0.50. It added three post-A/B SHORT candidates at imbalance 0.535, 0.529 and
0.504. The 0.535 candidate did not fill; the other two both ended in Plain SL,
at -26.90 and -32.38 USDC. Added net was **-59.28 USDC**. These candidates did
not displace any baseline trade, so the portfolio change is exactly -59.28 and
max drawdown increased from 108.84 to 135.74 USDC.

The baseline LONG-only replay disabled all SHORT signals while retaining the
0.54–0.69 band, A/B union, V8 stop policy and single-position rules. It produced
19 evaluable candidates, 16 fills, 9 positive and 7 negative fills, net
**+128.77 USDC**, with max drawdown **134.57 USDC**. The full baseline produced
+230.14 USDC. Removing SHORT therefore reduced net by **101.36 USDC** and
increased drawdown by 25.74 USDC. No common LONG result changed; the difference
is exactly the contribution of the seven filled baseline SHORT trades: four
positive, three negative, net +101.36 USDC.

### Baseline SHORT imbalance by outcome

The seven filled baseline SHORTs covered imbalance **0.551–0.690**. The three
Plain SL trades were at **0.559, 0.650 and 0.690** (range 0.559–0.690, mean
0.633; combined net -60.75 USDC). The four trades that reached at least TP1
were at **0.551, 0.576, 0.657 and 0.667** (range 0.551–0.667, mean 0.61275;
combined net +162.11 USDC). Of those, 0.551 reached TP1 and later stopped;
0.576, 0.657 and 0.667 reached TP2 and closed through trailing stops.

The groups overlap substantially: 0.650 lost while 0.657 and 0.667 won, and the
highest baseline value 0.690 lost. This seven-fill sample does not support a
clean additional SHORT cutoff inside 0.54–0.69. The separately tested added
SHORTs at 0.504 and 0.529 also ended in Plain SL; 0.535 did not fill.

## CHOP/COH relaxation follow-up

The archive contained 132 `CANDIDATE_GATE_REJECT / chop_coh` events. Twenty-nine
also fit the research imbalance bands LONG 0.50–0.69 / SHORT 0.54–0.69 and had
passed every preceding detector gate. Exact cutoff-safe A/B blocked 9 and
retained 20 under live fail-open semantics (19 KEEP, one UNKNOWN_KEEP).

Those 20 were added to the authoritative LONG 0.50 / SHORT 0.54 policy and
replayed with the same V8 stop, execution and cost settings:

| Policy | Evaluable | Filled | Position-blocked | Plain SL | Net PnL | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| LONG 0.50 / SHORT 0.54, CHOP/COH enforced | 39 | 27 | 8 | 11 | **+393.46** | 108.84 |
| Same policy, CHOP/COH bypassed | 59 | 41 | 13 | 20 | **+142.45** | 195.92 |

The policy delta is **-251.02 USDC**. Independently, all 20 added candidates
filled: 8 positive, 12 negative, 12 Plain SL, net **-178.38 USDC**. In the
single-position portfolio, 14 filled and 6 were blocked; their direct net was
**-196.18 USDC**. Changes to the baseline timeline cost another **-54.84 USDC**:
one +10.05 baseline LONG was blocked, and one previously blocked baseline SHORT
became a filled -44.79 Plain SL.

Independent subgroup evidence does not support bypassing CHOP: CHOP-only
failures were -164.40 USDC across LONG and SHORT. COH-only LONG was independently
positive (+96.17), but inside the full relaxed portfolio its direct contribution
was -50.70 because three of seven were position-blocked and the remaining
timeline differed. A separate COH-only policy replay would be required before
drawing a conclusion about narrowly lowering `COH10_MIN`; the combined gate
must not be removed based on this sample.

Authoritative run:
`runs/chop_coh_relaxed_long050_short054_feedfix_v2/`. The prior `...feedfix_v1`
run is superseded because it selected baseline candidates before shadow A/B
enrichment and did not reproduce `long_lower_050` parity.

Displacement itself was net harmful by 14.12 USDC. The altered position
timeline removed two profitable baseline trades (+1.42 and +45.47), avoided one
baseline Plain SL (-58.33), and admitted one baseline candidate that had
previously been position-blocked and then lost -25.57. The arithmetic is:
`-1.42 -45.47 +58.33 -25.57 = -14.12 USDC`. The policy still improved
because the newly admitted LONG trades contributed +91.77 USDC directly:
`+91.77 -14.12 = +77.65 USDC`.

In the isolated lower-only portfolio, newly admitted LONGs contributed +91.77
USDC and newly admitted SHORTs −52.30 USDC. Their direct total was +39.47 USDC,
while displacement of baseline trades reduced the policy-level improvement to
25.35 USDC.

In the isolated upper-only portfolio, newly admitted LONGs contributed +51.40
USDC and newly admitted SHORTs −244.31 USDC. Their direct total was −192.91
USDC; after signal competition, the full policy was −201.26 USDC below baseline.

## Interpretation

The symmetric `0.45–0.75` change is harmful in this replay. It removes nearly
all baseline portfolio profit because the added high-imbalance SHORT cohort
performs poorly and changes position availability.

The evidence supports a narrower follow-up hypothesis rather than a production
change:

- lowering the minimum toward 0.45 may be useful primarily for LONG;
- lowering the minimum for SHORT was negative in this sample, including the
  narrower 0.50–<0.54 test;
- raising the maximum to 0.75 for SHORT was strongly negative;
- baseline SHORT signals made a positive net contribution, so disabling SHORT
  entirely also worsened the portfolio;
- the modest positive upper-band LONG result needs holdout or walk-forward
  validation before promotion.

No production code, thresholds, services, state, or orders were changed.

## Evidence

- `results_summary.json`
- `incremental_independent_metrics.csv`
- `incremental_portfolio_metrics.csv`
- `portfolio_variant_metrics.csv`
- `long_lower_displacement_analysis.csv`
- `long_lower_imbalance_bins.csv`
- `directional_followups.json`
- `baseline_short_outcomes_by_imbalance.csv`
- `chop_coh_ab_results.csv`
- `chop_coh_backtest_analysis.json`
- `chop_coh_added_portfolio_outcomes.csv`
- `chop_coh_displacement_analysis.csv`
- `source_snapshot_manifest.json`
- authoritative run directories under `runs/*_feedfix_v1/`

The earlier same-named run directories without `_feedfix_v1` used a stale
partial Aug19 effective-feed file and are superseded. They are retained only
for audit and must not be used for conclusions.

Validation caveat: the scout_backtester test suite displayed 86 passing test
dots and 100% without failures, but the process did not return a final summary
or exit and was interrupted. This is not recorded as a clean completed suite
pass. All eight authoritative replay commands themselves completed with exit
code 0. Candidate quality tables are empty, and no same-bar sensitivity changed
an outcome. `validation.json` passes source cutoffs, execution-feed quality and
row-count/sensitivity checks for all eight runs.
