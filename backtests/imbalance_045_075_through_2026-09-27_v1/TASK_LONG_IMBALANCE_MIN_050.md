# TASK: DeltaScout side-specific LONG imbalance minimum 0.50

Repository: `D:\Project_V\btc-orderflow-system` (`Mykh-Ai/btc-orderflow-system`)

## Objective

Make the DeltaScout imbalance gate direction-specific:

- LONG: `0.50 <= imbalance <= 0.69`
- SHORT: `0.54 <= imbalance <= 0.69`

Keep every other detector gate, A/B filter, event contract and Executor behavior
unchanged. This task prepares and validates the code/configuration change. Do not
deploy, restart services or modify production state without separate explicit
authorization.

Current runtime configuration uses universal `IMB_MIN` and `IMB_MAX` values in
`delta_scout.env`, shared by LONG and SHORT. The implementation must split only
the lower bound by direction. `IMB_MAX` remains universal.

## Evidence for the change

Offline scope: 2026-03-17 through 2026-09-27, A/B union reapplied, Executor V15
dual-feed replay, V8 structural initial stop, fixed 3000 USDC notional and pinned
cost model.

- Baseline LONG/SHORT 0.54–0.69: net `+230.14 USDC`, max drawdown `108.84`.
- LONG 0.50–0.69 / SHORT 0.54–0.69: net `+393.46 USDC`, delta `+163.32`,
  max drawdown `108.84`.
- LONG 0.54–0.69 / SHORT 0.50–0.69: net `+170.86 USDC`, delta `-59.28`,
  max drawdown `135.74`.
- Added LONG sample after A/B is small (six candidates), so retain explicit
  research provenance and do not describe this as statistically proven edge.

Evidence files:

- `D:\Project_V\Executor\backtests\imbalance_045_075_through_2026-09-27_v1\report_uk.md`
- `D:\Project_V\Executor\backtests\imbalance_045_075_through_2026-09-27_v1\results_summary.json`
- authoritative run `runs\long_lower_050_feedfix_v1`

## Required preparation

1. Read repository `AGENTS.md`, inspect local Git status and preserve unrelated
   changes.
2. Compare the checked-out code and configuration contract with the deployed
   DeltaScout runtime read-only. Do not assume the Git defaults (`IMB_MIN=0.55`,
   `IMB_MAX=0.65` currently visible in `deltascout/delta_scout.py`) equal the
   values supplied by production `delta_scout.env` (`0.54–0.69` in the research
   snapshot). Verify the exact env-file path and how the DeltaScout service loads
   it.
3. Identify every consumer and emitted field for `IMB_MIN`, `IMB_MAX` and
   `reject_reason=imb_band` before editing.

## Implementation requirements

1. Introduce side-specific lower-bound configuration with clear names, for
   example `IMB_MIN_LONG` and `IMB_MIN_SHORT`.
2. Preserve backward compatibility: if the side-specific variable is absent,
   fall back to the existing `IMB_MIN` value. Do not silently change existing
   installations merely by deploying code.
3. LONG gate must use its effective LONG minimum; SHORT gate must use its
   effective SHORT minimum. Keep the inclusive boundary behavior.
4. Keep the common `IMB_MAX` contract unless inspection proves that a
   direction-specific maximum already exists and must be preserved.
5. `CANDIDATE_GATE_REJECT` and admitted/archive records must report the actual
   effective minimum used for that side. Preserve existing event names and
   fields; additive side/config metadata is acceptable if backward compatible.
6. Update `.env.example`, README/config documentation and any startup config
   snapshot so operators can verify effective LONG and SHORT values.
7. Do not change EMA/VWAP, CHOP, COH, 3/3 comparison, VWAP-distance, A/B,
   deduplication, PEAK format, stop selection or Executor logic.

## Tests

Add focused tests that prove:

- LONG `0.499` rejects, `0.500` passes the imbalance gate, and `0.539` passes.
- SHORT `0.500` and `0.539` reject; `0.540` passes.
- `0.690` passes and `0.691` rejects on both sides when `IMB_MAX=0.69`.
- With only legacy `IMB_MIN` configured, both sides retain the legacy behavior.
- Reject/archive payloads contain the correct effective side-specific minimum.
- Existing detector and research-archive tests still pass.

Run the narrow tests first, then the full DeltaScout suite. Report exact commands,
pass/fail counts and any test process that does not exit cleanly.

## Deliverables

- Focused code diff with no unrelated changes.
- Test evidence and effective-config examples for:
  `IMB_MIN_LONG=0.50`, `IMB_MIN_SHORT=0.54`, `IMB_MAX=0.69`.
- Exact proposed `delta_scout.env` change for the later authorized deployment:

  ```dotenv
  IMB_MIN=0.54
  IMB_MIN_LONG=0.50
  IMB_MIN_SHORT=0.54
  IMB_MAX=0.69
  ```

  Keep `IMB_MIN=0.54` as the compatibility fallback. Do not edit the production
  env file during this implementation task.
- Read-only production parity note listing current effective values and the exact
  later deployment/config steps.
- Rollback plan restoring LONG to `0.54`.
- No commit, push, deployment or restart unless separately requested.

## Acceptance criteria

- Direction-specific boundary tests pass exactly as listed.
- SHORT behavior remains 0.54–0.69.
- LONG behavior becomes configurable as 0.50–0.69.
- Legacy `IMB_MIN` remains a working fallback.
- Event evidence exposes the effective threshold used.
- No other detector, A/B or Executor behavior changes.
