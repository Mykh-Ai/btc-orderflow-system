# Recovery clock correction and replay

Run offline commands from the project root. Use new output directories and retain
all original archives and prior experiments. No server operation is required.

## Input contracts

- Legacy aggregator CSV timestamps are local `Europe/Bratislava`, including DST.
  They label the completed aggregation minute. The recovery builder converts to
  UTC and rounds occasional second-level clock jitter to the nearest minute.
  Ambiguous/nonexistent local times and duplicate normalized minutes are errors.
- SHI timestamps are UTC completed-minute labels. Do not shift enrichment fields.
- Include adjacent local archive dates: a UTC evening can require the following
  local date. Inspect the quality sidecar for missing source minutes.
- Official Binance Spot CSVs from `acquire_binance_spot_klines` use UTC **open**
  timestamps. The replay loader converts these to completed-minute labels in
  memory. Do not shift those CSVs yourself.
- Recovery retains the existing restrictions: OI only when supported by SHI;
  funding untrusted; historical liquidation data unavailable. Recovery is not
  evidence of historical bid/ask, queue position or exact fills.

## Build and compose

Choose explicit paths for the local archives and new outputs:

```powershell
python -m deltascout.research_bundle.build_recovered_feed_gap `
  --legacy-root <legacy-archive-root> `
  --shi-root <original-shi-root> `
  --legacy-source-timezone Europe/Bratislava `
  --output-root <new-recovery-root> `
  --quality-root <new-quality-root>
```

The builder refuses to overwrite existing daily outputs, sidecars or its manifest.
Inspect `recovery_quality_*.csv`, `recovery_report_*.md` and
`recovery_manifest.json`. Every recovered row includes its local timestamp,
timezone, offset and original file/row. The manifest hashes source files and the
builder. Missing legacy minutes are explicitly excluded, never silently filled
with unrelated prices.

Compose a new effective feed from a frozen complete baseline. Replace only UTC
rows inside the recovery interval with the new recovered rows, including removing
old misaligned rows. Preserve all rows outside the interval. Record hashes of the
frozen files and composed outputs. Do not overlay corrected prices on an already
recovered file and use that as the original SHI input.

## Replay and verify

Run the usual V8 replay twice with the new effective feed/quality roots and fresh
experiment IDs, once with `--candidate-loss-filter NONE`, once with
`--candidate-loss-filter UNION_A_OR_B`. Pin the previous date range, candidate
groups, commission, notional, slippage, stop and entry parameters. Compare the
resolved manifests; clock correction is not a parameter optimization.

Verify candidate identities, entry/SL ordering after every fill, lifecycle and
portfolio sequencing changes, and net PnL after costs. `INITIAL_STOP_WRONG_SIDE_AFTER_FILL`
fails the run because an already-modeled fill cannot honestly be rewritten as
NO_TRADE. Reconcile its timestamps/prices before using aggregate performance.

Targeted validation:

```powershell
python -m pytest tests/offline/test_recovered_feed_gap.py tests/offline/scout_backtester -q
```

Compare real historical outcomes separately using the canonical raw outcome
archive. A replay of a frozen V8 policy is not a reconstruction of the historical
live order stream. Do not promote old recovery-based economics after this fix;
rebuild each dependent study before reusing its numbers.
