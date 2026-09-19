# Executor refactor pre-merge safety gate

Starting HEAD: `aad153a2b426d849973e00beab4af90518617e65`.
Branch: `codex/refactor-executor-finalization-v1`.
Audit performed before SC-01 edits on 2026-09-17.

## SC-01 evidence audit before editing

- `pending_entry_flow.py` strictly validates terminal executedQty at poll,
  timeout lookup, and post-cancel lookup. ValueError bypasses clear/Plan-B and
  retains PENDING, but the outer catch logs only LIVE_POLL_ERROR, without webhook.
- `order_utils.validated_executed_qty` rejects missing, boolean, malformed,
  non-finite, negative and unrepresentable quantities. No parser change needed.
- `reconciliation.py` already uses position.recon.last_emit with
  RECON_THROTTLE_SEC, falling back to INVAR_THROTTLE_SEC/default 600 seconds;
  its no-tag path saves the timestamp before alerting.
- `state_store.save_state/load_state` atomically preserves nested position
  metadata. `has_open_position` treats PENDING as owned, blocking new entries.
- Baseline: `python -m pytest -q test/sc01/`: 33 passed in 0.50s.
- Existing tests prove retained ownership but do not require an explicit event,
  webhook or durable unknown-entry-quantity alert throttle.

## Gate 1: PRODUCTION_FEED_INCOMPATIBLE for the refactor pipeline

Read-only SSH via existing vps95 configuration. Docker inspect selected config
and mounts; docker exec read /proc/1/environ and streamed CSV with csv.reader.
No Executor module imports, exchange calls, production writes or restart were used.

Running container: executor (running true; Up 3 days at inspection).
Docker Config.Env and /proc/1/environ both:
AGG_CSV=/data/feed/aggregated.csv.
INITIAL_STOP_POLICY=VOLUME_SWING_24H_LR25.
Bind mount: /root/volume-alert/data/feed -> /data/feed, RW=false.
Host feed: /root/volume-alert/data/feed/aggregated.csv.
Code mounts (RW=false): /root/volume-alert/executor.py -> /app/executor.py;
/root/volume-alert/executor_mod -> /app/executor_mod.

CSV header:
```csv
Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice
```
1500 data rows; timestamp range 2026-09-16 18:26:00 through
2026-09-17 19:25:00 (as stored, no timezone suffix).
Zero non-60-second adjacent intervals. Last five rows:
```csv
2026-09-17 19:21:00,1322,6.540640,0.004948,3.341170,3.199470,76861.638019,76860,76868,76848
2026-09-17 19:22:00,1341,11.112720,0.008287,5.537410,5.575310,76865.760013,76886,76886,76852
2026-09-17 19:23:00,1723,55.045840,0.031948,51.943770,3.102070,76899.633936,76923,76935,76886
2026-09-17 19:24:00,4649,23.308350,0.005014,17.367380,5.940970,76924.513420,76950,76950,76904
2026-09-17 19:25:00,2772,6.482110,0.002338,0.476820,6.005290,76918.203699,76897,76950,76897
```
All four raw CSV columns are absent: low_usdt, high_usdt, volume_1m,
swing_row_real.

The mounted running v2.0 loader /app/executor_mod/market_data.py:65-68
normalizes HiPrice -> high_usdt, LowPrice -> low_usdt, TotalQty -> volume_1m,
and derives swing_row_real from positive, valid numeric close/high/low/volume/
trade-count data and high >= low. These are production-derived values, not
required raw CSV columns. The mounted /app/executor.py:696 selector requires
these normalized columns at lines 733-740; entry flow calls the loader at 2736
and the selector at 2754. Thus column absence in raw CSV alone does NOT show
that the running v2.0 pipeline is incompatible.

Mounted source SHA256 (UTF-8 text):
- market_data.py: c5496a5fbeed675ef43cbcf2017b8dad8892674afe2af485b7f7fddf53895550
- executor.py: fa675335c54fccb53cdf67cdd2896658e102c60631849f30abab5bf96b3475c3

However the audited refactor HEAD's executor_mod/market_data.py:21 loader
omits all four derived columns. open_entry_flow.py:90 passes this DataFrame
straight to the selector at 107; entry_math.py:246-255 requires the four columns
and raises INITIAL_SWING_SCHEMA_MISSING. Its tests supply those columns
explicitly (test/v20/test_refactor_safety.py:21-24). Therefore the branch's exact
initial-stop pipeline cannot consume the actual production feed as-is.

Mismatch source: refactor loader versus mounted production loader; this is
not evidence of an aggregator defect. Local v2.0:market_data.py also lacks the
mounted normalization, so local v2.0 is not evidence of deployed source parity.
Gate 1 stops for architect review. No feed/aggregator/loader fix is made here.

## SC-01 implementation and validation

Changed runtime file: executor_mod/pending_entry_flow.py only.
A local Optional[float] helper preserves the existing nonterminal conversion and
strictly validates terminal CANCELED/EXPIRED/REJECTED executedQty. On ValueError:

1. Log ENTRY_TERMINAL_QTY_UNKNOWN with severity CRITICAL, order/status/phase,
   trade key, validation reason, quantity-presence and suppression flags.
2. Reuse position.recon.last_emit["entry_terminal_qty_unknown:<order_id>"].
   The timestamp is seconds since epoch. All terminal statuses and bad values
   for the same owned order share one key.
3. Use existing RECON_THROTTLE_SEC, else INVAR_THROTTLE_SEC, else 600 seconds.
   Suppressed attempts do not move the timestamp; expiry permits a fresh alert.
4. Save ownership and the alert reservation before sending the operator webhook.
   A failed webhook attempt is still throttled, with its transport exception
   additionally logged by the existing LIVE_POLL_ERROR catch.
5. Stop the pending flow before clear/finalization, cancellation (when not already
   performed), promotion, exits or Plan-B. Return False preserves existing main
   ingestion; the existing PENDING guard blocks any competing new entry.

No additional state machine, configuration variable, exchange endpoint or state
migration is introduced. Atomic JSON persistence already preserves this map.
No SC-03/SC-06, SL/TP/trailing/strategy, feed or aggregator change.

New tests: test/sc01/test_unknown_exposure_alert.py (114 test cases).
- 108 cases: three terminal statuses x three lookup phases x 12 unreliable
  payloads (missing, None, empty, malformed, NaN, positive/negative infinity,
  negative, both booleans, underflow and overflow).
- Assert retained PENDING identity/qty/prices/orders, no slot clear, finalization,
  close hook/archive/snapshot, Plan-B MARKET or competing entry/borrow/order.
- Assert critical event and webhook, timestamp durable before webhook.
- Three phase-specific tests cover same-process repeats, immediate reload,
  persisted suppression and exact throttle boundary without changing alert state.
- Status/value changes share the order key; existing reconciliation metadata and
  INVAR_THROTTLE_SEC fallback are preserved.
- Webhook exception retains durable reservation and ownership across reload.

Validation:
- Focused command: python -m pytest -q test/sc01/
  test/v20/test_refactor_safety.py test/test_pending_entry_flow_module.py
  test/test_pending_entry_flow.py
- Focused result: 270 passed, 3 subtests passed (exit 0).
- Full suite: python -m pytest -q in a temporary git archive HEAD export with
  the three task files overlaid. No test selection, skip or disabling. User-owned
  AGENTS.md edit and untracked transfer_out/ archive are excluded; exporting avoids
  duplicate collection from the untracked archive.
- Full result: 1 failed, 808 passed, 24 subtests passed (exit 1).
- Only failure: test/test_llm_trade_judge.py:432,
  TestMarketContextUntilCutoff.test_prompt_mentions_market_context_and_no_hindsight.
  It expects market_context.deltascout in the newer entry-only prompt. Known,
  unrelated, and unchanged as explicitly permitted by the task.
- python compile checks: executor.py and all executor_mod/*.py passed.
- git diff --check: passed (exit 0; CRLF normalization notices only).

Task files:
- executor_mod/pending_entry_flow.py
- test/sc01/test_unknown_exposure_alert.py
- docs/refactor-premerge-safety-gate.md

Ending HEAD: aad153a2b426d849973e00beab4af90518617e65.
Changes remain local and uncommitted; this task did not authorize commit/push.
User-owned AGENTS.md changes and transfer_out/ are preserved.
Primary v2.0 stays at 71b4af9747f9ba62d09cf4dab9c1f055bce870a9 and clean.
No merge, deployment, restart, feed write or Binance order was performed.

Final result: BLOCKED. SC-01 validation passes. Gate 1 requires architect review
of refactor-versus-mounted-runtime loader divergence; no speculative fix made.
