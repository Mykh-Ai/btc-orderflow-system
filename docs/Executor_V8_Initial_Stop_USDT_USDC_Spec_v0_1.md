# Executor V8 Initial Stop and USDT/USDC Synchronization — Technical Specification v0.1

Status: deployed to the VPS Executor runtime on 2026-09-03 after merge with the
current modular production source.

Date: 2026-09-02.

## Objective

Replace Executor's legacy initial stop (`180m` minimum/maximum of `ClosePrice`)
with the frozen structural policy that produced the latest positive V8 PEAK replay,
while preserving the live quote-space boundary:

- structural analysis is performed on the BTCUSDT one-minute runtime feed;
- every Binance order for `BTCUSDC` uses a level converted to BTCUSDC;
- a raw BTCUSDT structural level must never be submitted as a BTCUSDC stop.

The same boundary applies to both the initial stop and every trailing-stop
activation, restoration, or update.

## Frozen Initial-Stop Policy

Policy ID: `VOLUME_SWING_24H_LR25`.

For each already-admitted DeltaScout PEAK:

1. Resolve the exact signal minute in `aggregated.csv`. Do not substitute the most
   recent row if the signal minute is missing.
2. Read exactly `1,440` one-minute BTCUSDT rows ending at that signal minute. This
   is normally 24 hours. To preserve parity with the frozen V8 replay, timestamp
   gaps are counted and audited but do not introduce an additional rejection rule.
3. For LONG, find strict swing lows using `LowPrice`; for SHORT, find strict swing
   highs using `HiPrice`.
4. A swing requires `25` strictly lower/higher bars on the left and `25` on the
   right. The right side must be complete by the signal cutoff; no post-signal data
   is allowed.
5. Rows with invalid OHLC, no trades, or non-positive one-minute volume cannot
   define or confirm a swing.
6. Construct the structural stop in BTCUSDT:
   - LONG: `swing Low - 50`;
   - SHORT: `swing High + 50`.
7. Preserve the existing 0.2% far-stop floor:
   - LONG uses the farther/lower of structural stop and `entry * (1 - 0.002)`;
   - SHORT uses the farther/higher of structural stop and `entry * (1 + 0.002)`.
8. Apply directional tick rounding, then discard any swing whose finished distance
   from planned BTCUSDT entry exceeds `$1,200`.
9. Select the eligible swing with the greatest `TotalQty` for its one-minute bar.
   Equal volume selects the most recent swing.
10. If the full window is unavailable or no swing survives, reject the candidate.
    Do not fall back to the legacy stop.

TP1 and TP2 remain `1R` and `2R`, computed in BTCUSDT from the selected initial
risk before quote conversion.

## Initial BTCUSDT to BTCUSDC Conversion

At entry planning time, read a same-cycle public book-ticker snapshot:

```text
k_entry = BTCUSDC_mid / BTCUSDT_mid
```

Use the single frozen `k_entry` for entry, initial SL, TP1, and TP2 so their risk
geometry remains internally consistent. Then apply the existing directional
BTCUSDC tick rounding, validate ordering, and verify that the LONG stop is below
the current BTCUSDC mid or the SHORT stop is above it before placing orders.

Persist at least:

- BTCUSDT entry, stop, TP1, and TP2;
- BTCUSDC entry, stop, TP1, and TP2;
- `k_entry`, both reference mids, and observation timestamp;
- selected swing timestamp, price, volume, confirmed count, and eligible count.

## Trailing-Stop Quote Synchronization

Trailing swing discovery remains based on the BTCUSDT `aggregated.csv` contour.
Every time Executor activates, restores, or updates a trailing stop:

1. Calculate the desired trailing swing and `$50` buffer in BTCUSDT.
2. Read a fresh same-cycle pair of public mids.
3. Calculate `k_trail = BTCUSDC_mid / BTCUSDT_mid`.
4. Convert `desired_stop_usdt * k_trail` into BTCUSDC.
5. Round outward: down for a LONG protective sell stop, up for a SHORT protective
   buy stop.
6. Verify the converted LONG stop is below current BTCUSDC mid, or the converted
   SHORT stop is above current BTCUSDC mid.
7. Only after successful synchronization and validation may Executor cancel and
   replace the existing stop.

The confirmation reference for a USDT-derived swing must be stored as
`trail_ref_price_usdt` and compared only with BTCUSDT closes. The placed stop and
step-improvement comparison remain in BTCUSDC.

Persist for each successful USDT-derived trailing placement:

- source stop in BTCUSDT;
- placed stop in BTCUSDC;
- `k_trail`, both mids, and observation timestamp.

## Failure Policy

- Missing exact signal minute, fewer than 1,440 history rows, or no eligible initial
  swing: skip the new trade and log the explicit reason. Timestamp gaps inside a
  1,440-row window are audited separately.
- Missing/invalid BTCUSDT or BTCUSDC mid, or ratio outside `[0.95, 1.05]`: do not
  place the new initial plan.
- Trailing quote-sync failure: retain the existing protective stop and retry later;
  never use the raw BTCUSDT level as BTCUSDC.
- An optional Binance-native trailing fallback, when explicitly configured, is
  already in BTCUSDC and therefore does not receive another conversion.

## Configuration

```text
INITIAL_STOP_POLICY=VOLUME_SWING_24H_LR25
INITIAL_SWING_LOOKBACK=1440
INITIAL_SWING_LR=25
INITIAL_SWING_BUFFER_USD=50
INITIAL_SWING_MAX_DISTANCE_USD=1200
INITIAL_SWING_REQUIRE_FULL_WINDOW=true
SL_PCT=0.002
USDT_USDC_RATIO_MIN=0.95
USDT_USDC_RATIO_MAX=1.05
```

The rolling `aggregated.csv` must retain at least 1,440 complete minutes. The
current documented 1,500-row runtime buffer is sufficient but leaves little
operational margin.

## Acceptance Criteria

- LONG and SHORT swing selection matches the V8 backtester for identical BTCUSDT
  bars and configuration.
- Highest-volume selection, recent tie-break, `$50` buffer, 0.2% far floor, and
  `$1,200` cap have deterministic tests.
- Missing exact minute, incomplete 1,440-row window, and untrusted swing
  neighborhood reject without legacy fallback; timestamp gaps are audited without
  changing the frozen V8 selection result.
- Initial order plans retain one frozen `k_entry` across entry/SL/TP levels.
- Every USDT-derived trailing order has an audited current `k_trail` conversion and
  passes the BTCUSDC-mid side check before cancel/replace.
- Quote-sync failure cannot remove the existing protective stop.
- Existing exit-order validation, quantity splitting, TP lifecycle, and position
  lock behavior remain unchanged.
- Before VPS activation, run a BTCUSDC execution-contour replay of the frozen policy
  and compare it with the BTCUSDT V8 result. The existing `+184.78 USDC` figure is a
  BTCUSDT-contour research result, not yet proof of live BTCUSDC parity.

## Rollout Record

Production-adjacent activation was explicitly authorized and completed on
`2026-09-03`. The runtime was flat before activation. The deployed implementation
was merged onto the current modular VPS source rather than replacing it with the
older local single-file snapshot. The final pre-deployment backup is:

`/root/volume-alert/backups/executor_v8_20260903T025903Z`

Only `executor` was recreated. DeltaScout, SHI Aggregator, and other services were
not restarted. Post-start verification confirmed `TRADE_MODE=margin`,
`SYMBOL=BTCUSDC`, `ENTRY_MODE=LIMIT_THEN_MARKET`, a null position, a complete
1,500-row runtime feed, the expected runtime hashes, and restart count `0`.

## Local Validation Record

On `2026-09-02`:

- targeted Executor plus Scout backtester suite: `57 passed`;
- full frozen-cohort parity: `48/48` V8 PEAK candidates selected the same BTCUSDT
  swing, stop, volume, eligible count, and confirmed count as the canonical
  `scout_peak_v8_initial_stop_24h_volume_swing_lr25_buffer50_cap1200_full_feed`
  replay;
- syntax compilation passed;
- no VPS or live container was changed during this local-validation phase.

On `2026-09-03` against the merged current VPS runtime:

- syntax compilation passed for `executor.py` and `executor_mod/market_data.py`;
- `12/12` targeted runtime tests passed, including fail-safe retention of the
  existing protective order when trailing quote synchronization fails;
- frozen structural selection parity remained `48/48`;
- the current VPS `aggregated.csv` snapshot loaded all `1,500` data rows with the
  V8 trust fields and provided a full gap-free 1,440-row selection window.
