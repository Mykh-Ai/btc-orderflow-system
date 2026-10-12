# NEG_H4_CLOSE_V1 — frozen protocol

Frozen before new replay results, 2026-10-12. Research only. Base `966dabcc0bef0ac7289905fcdfaf93252e1d1198`.

Numeric raw delta < 0; both DELTA_MIN / DELTA_MAX event names accepted. SHORT only. No PEAK_EMIT, minimum magnitude, elapsed-time filter, H4-level-only filter, POC, VWAP, session, volatility or new score threshold.

Use unchanged verified native cached Monitor queries and corrected eligible significant upper H1/H4 references. Price must be above upper at activation; select the same first ranked zone and freeze its ID, bounds, available_at, crossed_at, sweep_start_ts, score, level type and source timeframe. Later queries never replace a pending zone.

Confirmation: first fully complete canonical H4 whose CLOSE < frozen lower, strictly after owner seed, no later than seed + exactly 4 hours. UTC buckets start at 00/04/08/12/16/20. FeedBar timestamps denote completed minutes; shift -1 minute using native minute_frame, and reuse native aggregate_timeframe("H4"). Require all 240 real, valid, contiguous minutes; no incomplete, intrabar or rolling confirmation. Exact-deadline confirmation is allowed. A failed close leads to expiry at the unchanged deadline. Record the next canonical close and expiry reason. Gaps/invalid minutes invalidate pending exactly as in H1 baseline. End-of-data is censored.

First eligible NEG owns pending. Repeated NEG never extends deadline. One attempt per frozen zone/cross episode and one SHORT per confirmation timestamp; deterministic order unchanged. Both structural types share one portfolio and dedup state. Positive seeds cannot own or suppress NEG in the new study.

Sweep stop: maximum reference minute High from the original crossing H1 start through H4 confirmation, plus existing 0.0001 buffer. No later high. Existing Scout replay unchanged: 3000 USDC, commission 0.000744 per turnover; entry/exit/stop slippage 0/1/2 bps; USDT/USDC conversion; 90-second proxy; TP1 1R, TP2 2R, thirds, BE, trailing and stop-first unchanged. Run independent and existing shared one-position portfolio, retain blocked opportunities. No production/Executor/DeltaScout edits.

Same decision range 2026-03-20 through 2026-08-17, outcome feed through 2026-08-19. Preserve warm-up since first source minute. All-time seed audits distinguish decision-eligible confirmations. Full verified existing input hashes and query-cache hashes are persisted.

Comparisons: supplied historical NEG H1 contribution (164 independent, 75 portfolio filled in all-sign study) is reported explicitly. Also run a matched NEG-only H1 control with exactly the new admission/dedup and execution; only confirmation timeframe differs between that control and NEG_H4_CLOSE_V1. No optimization. Diagnostic timing buckets: (0,60], (60,120], (120,180], (180,240] minutes.

Report independent and portfolio overall, month, H1_SWING_HIGH/H4_SWING_HIGH and timing; counts, net wins/losses, gross/cost/net expectations and net PF. Report lost/new owner-seed opportunities. In-sample and previously explored data only; no causal delta-edge or production claim. H4 candle completion may reduce frequency or alter zone ownership and stop width; improved win rate alone is insufficient.
