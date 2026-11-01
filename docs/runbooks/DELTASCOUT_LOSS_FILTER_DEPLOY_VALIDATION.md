# DeltaScout loss-filter deployment verification

Date: 2026-11-01. Review target: `a8edff3` plus the local cache-compatibility correction.

The original commit's bootstrap could reject precision duplicates persisted by
the preceding version and then suppress every eligible new PEAK in veto mode.
The local correction merges events by UTC timestamp + side and treats numeric
disagreement as value reconciliation, not a history-health veto. Recovery
backfills missing cached events from the archive and retains valid cache-only
events; it does not require the two copies to be identical. Healthy evaluations
do not read the archive. The actual predecessor-generated cache upgrade now
passes locally. No manual cache cleanup is needed. Server deployment and
verification remain pending.

This runbook is a verification plan, not authorization to deploy, change server
configuration, or place a live trade. None of those operations were performed
during the local review.

## Local acceptance before server work

1. Exercise the transition from actual predecessor-generated state containing
   rounded/full-precision duplicates, in both rounding directions. The upgraded
   runtime must count each timestamp/side once and retain precise compatible
   values. Larger numeric differences use the canonical archive without a
   technical veto. Confirm archive-only events backfill the cache and valid
   cache-only events survive. Equal deltas at different timestamps or sides
   must remain separate events.
2. Check healthy A/B PASS, trustworthy A/B BLOCK, unknown data, the approved
   one/two-synthetic-minute exception, and three-synthetic-minute rejection.
3. Verify that a blocked event followed by a healthy event does not latch
   admission closed. Confirm recovery fills missing archived extrema before
   evaluating A, and that archive reads stop after successful recovery.
   Preserve the requirement that known BLOCKs survive audit errors and repeated
   rejection.
4. Check the actual executor reader and entry loop with exchange calls replaced:
   LONG and SHORT, MARKET and LIMIT, plus position/cooldown/lock guards. A local
   stubbed exit call does not validate live protection orders.
5. Run the focused DeltaScout/executor tests. Review only changes from the
   deployment candidate; exclude unrelated local research work.

## Server preflight after operator authorization

1. Identify the actual running DeltaScout and executor containers, mounted
   runtime files, configuration source, and revision. Use the deployed compose
   configuration, not the repository's demo compose file. Verify the server
   Python/venv path before assuming how a diagnostic must run.
2. Preserve a timestamped backup of the runtime files being replaced, the
   loss-filter state, and relevant configuration. Keep forensic archives intact.
3. Inspect a copy of the existing state alongside the current canonical 24-hour
   archive. Confirm the copied inputs can backfill the trailing window. The
   corrected runtime merges repeated and missing representations during normal
   loading; do not delete, manually rewrite, or reset the live cache.
4. Verify the archive/state/feed mounts, their expected timezone contracts and
   access rights, and the active `LOSS_FILTER_MODE`. Confirm that the archive
   writer and loss-filter reader address the same daily files.
5. Inspect recent actual signal cutoffs against enriched feed availability. The
   filter requires the exact cutoff minute and a contiguous 240-minute window;
   the detector does not retry a rejected timestamp when enriched data arrives
   later. Persistent feed lag is a stop condition for this rollout.
6. Inspect current positions and pending orders on both the exchange and in
   executor state. Do not clear a position, lock, cooldown, watermark, or dedup
   record to force a successful test.

## Minimal deployment and immediate verification

1. Deploy only the corrected runtime files required for this change. The reviewed
   commit changes `deltascout/delta_scout.py` and
   `deltascout/loss_avoidance_runtime.py`; tests and review probes stay local.
   Include any additional runtime files only if the eventual fix requires them.
2. Restart/recreate only the necessary DeltaScout service. The reviewed change
   does not require an executor restart. Verify the loaded file hashes/revision.
3. Verify successful history bootstrap or verified recovery, with no unresolved
   state mismatch. Check A/B inputs and the exact enriched cutoff on actual
   evaluation output, not just container health.
4. Observe both admitted and rejected candidates. For an admitted candidate,
   trace the same timestamp/side through the research decision, live PEAK JSON,
   executor read/dedup handling, and executor outcome. A legitimate executor
   skip must retain its existing reason.
5. Confirm data blocks have `PEAK_LOSS_FILTER_DATA_BLOCK` and the corresponding
   warning; rule blocks remain distinct. A webhook response alone is not proof
   that the operator received the Telegram message.
6. Stop rollout on persistent unexpected UNKNOWN/data blocks, repeated
   bootstrap errors, missing admitted signals, or execution/protection errors.
   Restore the reviewed backup under the agreed rollback procedure; do not
   silently change the filter to off or shadow.

## Optional single live order test

Perform this only after the upgrade defect is resolved, preflight passes, and
the operator explicitly authorizes the trade and its maximum notional. Prefer
tracing a real admitted signal when it provides sufficient execution evidence.

- A directly injected PEAK in `deltascout.log` tests only the downstream executor.
  It bypasses all original detector gates and `_admit_peak`; pair any such
  authorized downstream test with independent admission verification. Do not
  place fabricated rows into canonical market data or research archives.
- If the chosen maximum is 100 USD, first verify the active sizing input is
  `QTY_USD`, the actual symbol/trade mode, current exchange lot/notional filters,
  available funds or margin, and the sizes of individual exit legs. The local
  default or a successful local calculation is insufficient.
- A global `QTY_USD` change affects every new entry while active. Define how the
  test is restricted to one event without bypassing normal position protection;
  agree the restored configuration and cleanup before sending anything.
- Record the event identifier, actual order ID, accepted quantity/notional,
  actual fill, and exchange-confirmed SL/TP orders. An `OPEN` notification can
  represent a pending LIMIT order; it does not establish a fill.
- Verify the agreed close/cancel outcome, remaining exchange orders, position
  state and restored sizing. Do not leave a test position or test-only override
  unattended.

Apply the repository's Windows SSH ACL cleanup and verification requirements at
the end of any SSH session.

## Verified server layout on 2026-11-01

- Host: `root@95.216.139.172`; runtime directory: `/root/volume-alert`.
  This directory has no Git checkout. GitHub integration targets `research`;
  the GitHub default `v2.0` contains the separate Executor layout.
- Container: `deltascout`, command `python -u delta_scout.py`, working directory
  `/app`. Its Python is `/usr/local/bin/python`, version 3.10.21. The suggested
  host project `.venv` does not exist; validate using the container interpreter.
- Deploy `deltascout/delta_scout.py` to `/root/volume-alert/delta_scout.py` and
  `deltascout/loss_avoidance_runtime.py` to
  `/root/volume-alert/loss_avoidance_runtime.py`. Both are individual bind mounts
  under `/app`. `loss_avoidance_policy.py` is already present and unchanged.
- Mode remains `veto`. The enriched mount is
  `/opt/aitrader_data/feed -> /opt/aitrader/feed`; state is under
  `/root/volume-alert/data/state/deltascout`. The running DeltaScout environment
  matches its declared compose environment at preflight.
- Preserve the running container configuration. Stage and validate the release,
  back up the original two runtime files and state, stop only `deltascout`, write
  the two verified files in place while preserving the bind-mounted inodes, and
  start the same container. Verify hashes, startup and continuing feed handling.
  Replacing a host path by rename without recreating the container can leave an
  individual bind mount attached to the old inode, so do not use that approach.
- Keep Executor, Buyer, n8n, all environment files, trade sizing and exchange
  orders unchanged. Preserve the original runtime files for a code rollback;
  restore their contents in place and restart only DeltaScout if required.
- Deployment preflight must instantiate the new evaluator with a temporary copy
  of the existing state and real read-only archive/feed inputs. Do not run a
  second evaluator against the live state path and do not inject a live PEAK.
