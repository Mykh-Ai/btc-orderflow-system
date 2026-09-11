# LLM monitor: offline data boundary

Status: research implementation, not connected to the live judge. The existing
Executor/AiTrader monitor and order management are unchanged.

The first implementation module is
`deltascout.research_bundle.monitor_feed_contract`. Build an artifact from the
repository root:

```powershell
python -m deltascout.research_bundle.build_monitor_data_snapshot `
  --feed-root <frozen-shi-daily-files> `
  --cutoff 2026-07-26T00:26:00Z `
  --history-minutes 1440 `
  --output-root <new-output-directory>
```

The output directory must be new. It contains `snapshot.json` and
`manifest.json`. No API/model calls, order hooks or raw-feed writes occur.
Default history is 30 days; 1440 minutes is sufficient only for local window
diagnostics. Neither setting reconstructs the full stateful monitor.

## Input and time contract

- Source: SHI daily CSV, historical or protected column names, UTC timestamps.
  The source profile explicitly assumes SHI flush-close labels. Do not pass
  exchange klines with open labels or a local-naive legacy archive to this adapter.
- Decision cutoff must include a timezone. Eligible labels satisfy
  `cutoff - history < Timestamp <= cutoff`.
- SHI currently labels the buffer flush at the minute boundary. These labels
  must not receive the +1 minute correction used for official spot open klines.
  Flush timing is not proof of exact exchange-event candle boundaries, nor of
  when the row became visible to a consumer. First/startup or shutdown flushes
  can also cover a partial interval without encoding that fact.
- Read only date files intersecting the requested interval. Validate numeric
  values and row quality after cutoff filtering. Unlocatable invalid timestamps
  still reject the file because they cannot safely be assigned to either side.
- Duplicate close labels reject the input. Do not silently keep the last row.
- Windows 5/15/30/60/240/1440 use elapsed UTC minutes, including prior-day rows.
  Missing minutes never cause an older row to be pulled into the window.
- M15/H1/H4 use right-closed, right-labelled intervals. H1 ending 01:00 consists
  of minute-close labels 00:01 through 01:00. Partial or unusable bars are
  excluded. This helper does not yet replace the legacy structure-level code;
  its consumer must also timestamp swing confirmation at the confirming close.

## Quality, units and lineage

Required values: OHLC, total/buy/sell quantity and trade count. Invalid OHLC,
negative/invalid quantities, inconsistent buy/sell totals, unknown synthetic
flags or synthetic rows cannot produce complete-window metrics. OI, funding and
liquidations may be null; absence never becomes a fabricated numeric zero.

`delta_fraction` and `return_fraction` are fractions; there is no ambiguous
`delta_pct`. Price quote is BTCUSDT. `PriceSource` distinguishes SHI USD-M from
recovered legacy PVD whose venue is not certified by this adapter. These prices
are not silently compared with an Executor BTCUSDC fill. The next evidence-pack
layer must carry the execution quote, conversion ratio/source/time and R.

During the known April/May gap, raw inputs are unusable without corrected
recovery provenance. For a recovery diagnostic supply all three:

```text
--recovery-quality <quality-sidecar.csv>
--recovery-manifest <recovery_manifest.json>
--recovery-lineage recovery_clock_v2_2026-09-08
```

The adapter verifies the `RECOVERY_CLOCK_V2` output hashes for loaded gap files
and sidecar, then matches row timestamp, recovery class/source and close. Both
forensic originals and older recovered copies remain unchanged. Recovered PVD
is usable only as degraded evidence. OI/funding/liquidations are conservatively
null in recovered rows; partial historical OI needs its own future field-level
validation before use. Mixed price-source windows need explicit review.

Whole-file hashes are recorded in the manifest. The snapshot has a separate
eligible-prefix hash. Appending a future synthetic/numerically invalid suffix
may change the file manifest but must not change pre-cutoff evidence.

`local_window_readiness=READY` means local numeric coverage passes these checks.
It does **not** certify collector interval completeness, individual OI/funding/
liquidation stream freshness, original arrival time, market-state completeness
or trading utility. `live_decision_eligible` is always false in this version.
Source-label age is measured from the latest usable row, not the synthetic tail.

## Validation and remaining integration

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -q tests/offline/test_monitor_feed_contract.py
```

Before promoting a monitor bridge:

1. Use this data contract in a versioned candidate, with the old bridge retained
   for an offline comparison. Validate completed-minute/arrival-time semantics
   with collector instrumentation before claiming a strictly live-ready snapshot.
2. Review 39A and scope one change: chronological closed-H1 state and level
   continuity, including complete eligible level inventory. Do not copy run
   scripts or the entire 38/39 chain into runtime.
3. Add evidence v2 with signal cutoff, fill/decision time, execution-policy
   identity, price domains, geometry/R and nullable costs. Preserve exact prompt,
   input and code/config identities for each new verdict.
4. Freeze current process settings for a new replay baseline. Initial SL V8
   parity alone does not imply trailing-configuration parity.
5. Evaluate the new forecast on separate data, calibration and action utility.
   Entry-outcome prediction and an early-exit policy require different tests.
6. Only after review, connect an asynchronous advisory worker. Deployment and
   trading-policy changes are separate operations.
