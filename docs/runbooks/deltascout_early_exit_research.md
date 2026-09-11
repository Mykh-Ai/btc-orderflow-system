# Offline failed-impulse exit experiment

Run from the project root with `python -m deltascout.research_bundle.build_early_exit`.
This is a bounded experiment on the existing PEAK reference class, not a new
setup search or a change to live order management.

## Frozen hypothesis

At each completed minute while the position is open before TP1:

1. At least 60 minutes have elapsed from the entry's completed-bar label.
2. A favourable excursion of at least 0.5R has occurred.
3. The directional execution close relative to the actual modeled entry is <=0R.
4. Directional reference-feed delta over the last 15 completed minutes is strictly
   negative: `side_sign * sum(buy_qty - sell_qty) / sum(buy_qty + sell_qty) < 0`.

R is the absolute distance between actual modeled fill and initial stop. MFE uses
execution High/Low only from fully completed candles after the entry candle; the
entry candle contributes its close only because its wicks may predate the fill.
Zero delta is neutral and does not trigger. The rule does not require a previous
positive flow reading; it tests opposing recent flow, not a proven sign reversal.

Decisions on a candle with an existing SL or TP1 fill are ineligible. Execute at
the next contiguous execution candle's open, with baseline normal-exit commission
and slippage. Later High/Low of that execution candle cannot override the market
exit. If the open itself already touches the standing SL/TP1, preserve baseline
bracket handling instead of assuming the discretionary order wins a race.

Both entry and exit timestamps retain the baseline completed-minute convention.
The exit record also stores the open-price timestamp. Portfolio slot release and
cooldown consequently retain a conservative delay of up to one minute relative
to the modeled open-price execution. No exact intraminute latency is claimed.

## Inputs and safeguards

Required arguments:

- `--no-filter-root`: immutable corrected baseline directory.
- `--ab-root`: matching immutable baseline with the A/B admission filter.
- `--execution-root`: official Spot execution candles, stored with open labels;
  the existing loader converts labels to completed minutes in memory.
- `--reference-root`: corrected effective reference feed.
- `--quality-root`: matching corrected recovery sidecars and manifest.
- `--output-root`: a new, empty experiment directory.

The builder writes `protocol.json` before calculating results, verifies frozen
input hashes and the baseline replay package fingerprint, then reproduces both
independent and portfolio baselines. All result fields are checked except the
run fingerprint and the unused alternate same-bar-policy sensitivity flag.

The exit scan uses chronological pre-TP1 prefixes of the reproduced baseline.
Future outcome labels/PnL are excluded from decisions. Once a discretionary exit
occurs, future baseline events and metadata are discarded. All surviving
candidates, including originally blocked ones, enter a fresh portfolio pass with
the original one-position lock and cooldown. If no exit occurs, the independent
trade and its events remain identical to baseline.

Missing/synthetic execution minutes stop the early-exit scan. Missing/synthetic
reference minutes or unavailable/invalid flow skip the affected rolling window;
no forward-filling is used. Recovered reference minutes are counted at decisions.
OI, funding and liquidations are not early-exit features. Existing A/B admission
decisions remain frozen, including their existing quality constraints.

## Outputs and interpretation

- `analysis.json`: before/after metrics, paired candidate comparisons, decision
  audits, and variant trades/legs for four cohorts.
- `replay_events.json`: variant chronological events by cohort and mode.
- `protocol.json`: the fixed rule, cost/timing assumptions and research scope.
- `experiment_manifest.json`: source/output hashes and baseline verification.

Trade IDs retain baseline lineage for pairing; identify a result by its scenario
key (`all_independent`, `all_portfolio`, `ab_independent`, `ab_portfolio`) together
with its trade ID. These experiment artifacts must not replace baseline outputs.

Use A/B portfolio as the primary operational comparison and independent results
to isolate exit effects. Separate common-trade PnL changes from newly admitted or
removed trades. Drawdown is measured on the cumulative net PnL at full position
closure, matching the baseline convention; it is not intratrade marked-to-market
drawdown. Net PnL includes commissions/slippage and excludes borrow interest.

The already inspected historical sample is retrospective, not out of sample.
Do not optimize a parameter grid after seeing this result and call the selected
variant validated. Record a negative result as a rejected tested hypothesis;
positive results still require unseen data before any runtime adoption.

Validation:

```powershell
python -m pytest tests/offline/test_early_exit.py -q
```
