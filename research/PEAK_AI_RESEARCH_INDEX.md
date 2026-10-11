# Peak_Ai research consolidation — 2026-10-11

This branch consolidates all code, tests, protocols and substantive results from
this research session. It does not promote any result to production or live trading.
The corresponding Monitor adapter and audit are in Mykh-Ai/aitrader on the same
branch name: `codex/peak-ai-research-consolidated-2026-10-11`.

## Current completed result: H1 SHORT, both delta signs

Start with [the corrected report](peak_ai_delta_h1_all_signs/REPORT_UA.md),
[protocol](peak_ai_delta_h1_all_signs/PROTOCOL.md), and
[reproduction README](peak_ai_delta_h1_all_signs/README.md).

Every new raw DELTA_MIN/MAX, independent of sign, may arm the same SHORT:
price above a significant H1/H4 upper zone, followed by a completed H1 close
below its lower boundary within four hours. Shared pending state and one portfolio.
No LONG entries. No PEAK_EMIT entry selection.

2846 raw delta events; 516 unique confirmations, 515 in the tested interval.
226 closed simulated portfolio trades; net -1401.95 USDC after costs.
Positive triggers: 151 trades, -995.77 USDC. Negative: 75 trades, -406.18 USDC.
Both groups negative. Fixed notional 3000 USDC; March20-August17 decisions,
outcomes through August19. No unresolved positions; 289 blocked by an open position.

Seven correction checks and 34 ledger checks passed. The unchanged adapter using
cached as-of queries exactly reproduced all 400 earlier positive-only candidate
records and 2846 seed statuses. Full current query count verified at 2846 before
candidate generation. See VERIFICATION.json for preparation recovery details.

Downloadable current code/result package:
[Peak_Ai_H1_SHORT_both_signs_2026-10-11.zip](../docs/research/peak_ai/Peak_Ai_H1_SHORT_both_signs_2026-10-11.zip).
That package focuses on H1 v1 and the corrected H1 both-sign result. Earlier
experiments are separately retained below in this Git branch.

## Earlier experiments — preserve distinctions

| Folder | Actual scope | Status |
|---|---|---|
| `peak_ai_v1` | Earliest feed-derived extreme-delta prototypes, labelled Futures signal feed; multiple entry mechanisms and both sides | Historical wrong-source attempt for the user's Spot-delta task. Do not treat as the intended H1 hypothesis. |
| `peak_ai_raw_v2` | Spot raw DELTA_MIN/MAX, continuation/reversal rules, LONG and SHORT | Different historical study; selected `break_reverse__resistance` had 173 closed portfolio trades across three segments, total -403.43 USDC. |
| `peak_ai_delta_h1/results_v1` | Initial incomplete H1 preparation | Interruption evidence only; no completed replay here. |
| `peak_ai_delta_h1/results_v1_checkpointed` | H1 SHORT from positive DELTA_MAX only | Completed but incomplete requested scope: 210 closed trades, -1242.08 USDC. Negative triggers wrongly excluded. |
| `peak_ai_delta_h1_all_signs/results_v2` | Corrected H1 SHORT from both raw delta signs | CURRENT completed result: 226 closed trades, -1401.95 USDC. |

Preserve the frozen historical files even where their original wording was
incomplete. This index and the corrected audit explain the scope corrections.
Do not combine PnL across different rules, overlapping sensitivity runs or
independent-opportunity/portfolio modes. Per-sign splits of the shared portfolio
are contributions, not independently executed sign-only strategies.

## Scope and storage

H1/H4 individual-zone research adapter only, not full Monitor 39A. Native lifecycle
and scoring, same normalized Spot price/delta/structure source, BTCUSDC execution.
Liquidations unavailable; no independent new holdout, without-delta control,
borrow-interest or order-book execution model. No profitable strategy established.

Canonical bases: Replay `84fcb9ec257dd2c28b04ff6149b48b52d628fdca`;
Monitor `064247c4e3081a02ef9fc227e333ae6ca8dc6cec`.
Raw source inputs remain in the existing handoff bundles. Local pickle caches,
bytecode and an incomplete temporary source download are not research deliverables
and are intentionally not committed. Full readable ledgers and query evidence are.
