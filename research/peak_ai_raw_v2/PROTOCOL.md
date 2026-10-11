# Peak_Ai raw v2 — protocol fixed before new outcomes

2026-10-09; offline only; base 84fcb9ec257dd2c28b04ff6149b48b52d628fdca.
No production modifications, remote writes, orders or deployment. Prior v1 remains immutable.

## Evidence and input correction

DeltaScout handle_row writes DELTA_MAX/MIN before comparison/admission gates.
aggregator/aggregator.py consumes stream.binance.com BTCUSDT Spot trades.
All 2,846 unique archived raw extrema (March17–August18 local dates) match normalized
legacy BTCUSDT Spot at the same UTC minute to rounding (delta and volume <=0.011 BTC).
The SHI effective feed is BTCUSDT Futures and is a different market, not a timestamp
correction. It is NOT an input to this experiment. No PEAK_EMIT, rejected PEAK,
admission decisions, current gates, A/B flags, or previous v1 rules are inputs.

Legacy normalized bars are completed-minute labels, with Open synthesized from the
previous Close and High/Low expanded to include it by the supplied normalizer.
Signals use Close/High/Low, not synthesized Open. That High/Low convention also
applies to structural stops, so this remains an approximate archived replay.
Official BTCUSDC Spot execution bars use the existing loader (+1 minute from OPEN
timestamp to availability). Normalized legacy bars receive NO additional time shift.
Missing minutes are not filled. All seeds remain in an audit ledger, even if unusable.

## Fixed search space: four entry modes × four contexts = 16 rules

Each archived raw extremum is a seed. DELTA_MAX direction LONG; DELTA_MIN SHORT.
Require real valid seed plus 60 preceding contiguous valid one-minute bars.
Preflight correction before ANY outcome run: flat High=Low bars with positive traded
volume are valid history, not missing data (15,078 such bars in the normalized feed).
A flat seed can enter the all/activity/trend groups, but has undefined close location
and cannot qualify for resistance. Initial preflight overexcluded these bars; the
first inventory was superseded before any outcome calculation or selection.
1. immediate_follow: signal at seed close in seed direction.
2. immediate_fade: signal at seed close in opposite direction.
3. break_follow: first subsequent completed bar, within 10 minutes, closing beyond
   seed High (LONG) / seed Low (SHORT). Signal after this close, never retroactively.
4. break_reverse: first subsequent completed bar, within 10 minutes, closing beyond
   seed Low (SHORT from MAX) / seed High (LONG from MIN).
Each waiting hypothesis is independent; stop scanning at a gap, bad bar or 10m expiry.
One emission per seed/mode. Same-minute/same-side duplicates within each family keep
the earliest seed only, with duplicate lineage separately recorded.

Contexts are evaluated at the seed, before entry confirmation:
- all: no extra filter;
- activity: seed volume >=2× median of the PRECEDING 60 bar volumes;
- resistance: seed close lies in the half of its range opposing the seed direction;
- trend: seed close minus close 60 minutes earlier agrees with the proposed trade side.
No additional threshold search, no historical profitable-only seed selection.

## Research splits and selection

Use March20–May29 decisions, outcomes through May31 (development); June1–28,
outcomes through June30 (validation); July1–August17, outcomes through August19
(historical retest). Each portfolio starts flat; two closing-only days. Unresolved
positions remain unresolved. Require seed and decision in same signal interval.
All these periods were previously available to the project and v1; this is NOT a
fresh untouched holdout. A new period is still needed before any deployment claim.

Full native backtest of all 16 on development, then freeze one context per entry
mode: rank by (eligible: >=25 closed, positive net, PF>=1.10), PF, net/drawdown,
then name. Ineligible leaders remain explicitly diagnostic.
Only these four advance to validation. Eligibility requires development gate AND
>=10 validation closed, positive validation net, PF>=1.10. Rank by eligibility,
minimum development/validation PF, validation net/drawdown, name. Freeze one
winner (or explicitly rejected diagnostic) before historical retest. Do not tune.
Run double-slippage and target-first sensitivity for the frozen selection.
All counts, losing rules, failures and unresolved positions must be reported.

## Execution model and evidential limits

Existing replay_candidate/replay_portfolio unchanged: 3000 USDC per position,
0.000744 commission per turnover, 0/1/2 bps entry/exit/stop slippage; 90s guarded
limit-to-market proxy; initial volume swing 1440/LR25/buffer50/cap1200/full window;
TP1/TP2, BE and trail240/LR25/buffer50/step25/confirm20; one position, 180s cooldown.
Structural reference = legacy BTCUSDT Spot; execution = official BTCUSDC Spot.
Report closed-trade equity drawdown, not account mark-to-market. No borrow interest,
spread/order-book/latency/partial-fill model. Approximate hypothetical trades only.
BacktestContractError is recorded as INVALID/INTEGRITY_ERROR, never a guessed PnL;
any affected family is disqualified even if remaining rows look profitable.
No claim that these 16 hypotheses exhaust all possible useful entry patterns.
