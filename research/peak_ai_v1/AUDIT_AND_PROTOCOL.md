# Peak_Ai v1 — evidence audit, ADR and frozen research protocol

Date: 2026-10-09. Scope: offline research only, explicitly requested new signal family. No live code, orders, services, strategy gates or execution semantics changes. Starting checkout: 84fcb9ec257dd2c28b04ff6149b48b52d628fdca.

## Evidence audit
Commands executed: git status --short; git log --oneline -n 30; git log -p -S prev_pass_3of3 -- deltascout/delta_scout.py; git blame -L 630,700 deltascout/delta_scout.py; numbered source inspection; rg searches in detector, execution_policy, replay_engine, portfolio, feed_loader and candidate_compiler. Initial checkout clean. Existing offline suite: 86 passed.

Detector evidence: delta_scout.py prev_pass_3of3 compares current/previous price, volume and VWAP. handle_row detects rolling max/min delta and writes DELTA_MAX/MIN before comparison and admission gates. Peak_Ai will instead generate candidates directly from historical feed, without pretending they are archived PEAK_EMIT events.

Backtester: Candidate is a pure frozen dataclass. replay_candidate uses execution_policy for structural SL, guarded entry, partial TP1/TP2, breakeven and trailing. replay_portfolio owns one-position and cooldown restrictions; unknown execution coverage blocks subsequent entries. Feed loader converts official Spot open timestamps to completed-minute availability (+1 minute), and consumes recovered signal feed and quality sidecars. Modules are offline and independent of live adapters. There is no exchange reconciliation, watchdog, persistent live state or margin borrowing in this experiment. Borrow interest and bid/ask/partial-fill latency are not modeled. Gross R is not net R.

Both bundled archives match the SHA256s in the handoff. Source data are immutable. Known recovery interval April 23–May 6 uses effective_feed and sidecars; original broken enriched feed is forbidden.

## ADR: invariants and design
1. Only completed feed bars at or before decision time. Rolling references exclude current bar. No centered windows in signal generation.
2. Delta = BuyQty - SellQty. Signal contour BTCUSDT Futures; execution BTCUSDC Spot, using existing conversion rules.
3. New extreme: positive delta exceeds previous 180 real contiguous minute deltas, or negative delta is below previous 180. Require absolute delta / volume >= 0.15 or >= 0.30 (the only two strength variants).
4. Three hypotheses, two strengths = SIX predeclared candidates. No further threshold search after outcomes.
   - continuation: extreme + close breaks previous 20-minute high/low, close in directional final 30% of bar, directional 60-minute net flow positive; emit at closed extreme bar.
   - pullback: continuation seed; within next 10 closed minutes, observe retrace of at least 25% of seed range while closes remain above/below seed midpoint. Emit first later bar closing beyond preceding bar high/low with aligned current delta. One signal per seed; reset on invalidation, timeout or discontinuity.
   - failed_extreme: extreme tests previous 20-minute high/low but closes back inside it and on opposite half of current bar; emit opposite direction at this close.
5. Never use outcome information to filter individual candidates. Explicit no-fill, no-stop, integrity errors and unresolved counts remain visible.
6. Same frozen V8 exit policy for new family and PEAK. LIMIT_THEN_MARKET_90S_GUARDED_V0_1; conservative stop-first; notional 3000 USDC; commission 0.000744 of turnover; entry/TP/SL slippage 0/1/2 bps. Existing defaults: initial swing 1440, LR25, buffer50, cap1200; trail 240, LR25, buffer50, step25, confirmation20. Three-minute portfolio cooldown.
7. Baselines: archived ADMITTED PEAK_EMIT (historical changing detector configuration), and those same events with currently coded UNION_A_OR_B reapplied from causal shadow evidence. These are archived-cohort comparisons, not a full current DeltaScout detector rerun.
8. Chronological split, UTC, portfolio starts flat per split: development signals Mar20–May29, outcomes through May31; validation signals Jun1–Jun28, outcomes through Jun30; untouched test signals Jul1–Aug17, outcomes through Aug19. Last two days reserved for closing; unresolved positions are reported, not silently force-closed. No training outcome beyond split end.
9. Select one rule using development + validation only. Eligible if >=20 resolved portfolio trades in development and >=10 in validation, positive net PnL and PF>=1.05 in BOTH. Rank by minimum of two profit factors, then validation net/max drawdown, then name. If none qualifies, choose best minimum PF solely as a rejected diagnostic; never call it a validated strategy.
10. Freeze selection JSON before test replay. Test selected rule only, baselines, target-first sensitivity and 2x slippage sensitivity; no post-test optimization. Bootstrap daily net PnL with fixed random seed as exploratory uncertainty, not proof.
11. Tests: append-future/prefix invariance; synthetic/gap rejection; pending trigger cannot see current future; dedup and directional symmetry; existing 86 execution tests. No execution model edits.

## Acceptance and rollback
Deliver causal candidate generator, replay driver, per-trade evidence, input/code hashes, frozen selection and Ukrainian report including negative results. Deployment/merge decision: NO-MERGE to production regardless of one historical test. No state migration. Rollback: stop using research outputs; no production rollback needed. Full independent replay and single-position portfolio are both reported. Drawdown is closed-trade equity, not intratrade account drawdown.
