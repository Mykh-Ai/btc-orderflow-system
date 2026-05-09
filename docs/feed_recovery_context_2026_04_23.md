# Feed Recovery Context: 2026-04-23 Binance Futures WS Migration

This document is durable project memory for agents. It records a known data-quality gap and the recovery contract for DeltaScout/AiTrader research.

## Incident

- Affected enriched feed window: `2026-04-23 17:05:00` through `2026-05-06 22:51:00` UTC.
- Broken source: `/opt/aitrader/feed/YYYY-MM-DD.csv`.
- Symptom: repeated flat or zero synthetic rows with `IsSynthetic=1`, `Volume=0`, and stale or zero `Close`.
- Root cause: Binance USD-M Futures legacy WebSocket endpoint `wss://fstream.binance.com/stream?streams=...` stopped pushing market/private stream payloads after `2026-04-23`.
- Runtime fix: collector code must use `wss://fstream.binance.com/market/stream?streams=...`.

## Recovery Sources

- Real price/volume/delta source: `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv`.
- Broken/enriched SHI source for OI/funding context: `/opt/aitrader/feed/YYYY-MM-DD.csv`.
- Local source copies:
  - `deltascout/research_material/source_archives/legacy_volume_alert_feed/`
  - `deltascout/research_material/source_archives/aitrader_shi_feed/`

## Recovered Outputs

- DeltaScout recovered feed: `deltascout/research_material/recovered_feed/YYYY-MM-DD.csv`.
- AiTrader mirror feed: `D:\Project_V\Aitrader\feed_recovered\YYYY-MM-DD.csv`.
- Quality sidecar: `deltascout/research_material/recovery_reports/recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv`.
- Human report: `deltascout/research_material/recovery_reports/recovery_report_2026-04-23_1705_to_2026-05-06_2251.md`.

## Builder

Run from the `btc-orderflow-system` repository root:

```powershell
python -m deltascout.research_bundle.build_recovered_feed_gap --mirror-output-root D:\Project_V\Aitrader\feed_recovered
```

The builder must not overwrite forensic raw originals.

## Interpretation Rules

- Price/OHLCV/trades/buy/sell/VWAP in recovered rows are real legacy archive values.
- OpenInterest is copied or forward-filled from SHI where possible.
- FundingRate during the WS gap is schema-fill/copy/forward-fill and must be treated as untrusted unless separately verified.
- Historical liquidation quantities are missing because the `forceOrder` stream was not archived in the legacy feed.
- Do not make funding/liquidation-based research claims inside the affected window unless explicitly marked degraded or unsupported.
- For Analyzer/Backtester work in the affected window, use `feed_recovered/` rather than the original broken `feed/`.
