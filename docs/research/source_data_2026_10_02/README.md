# VNV research source snapshot — 2026-10-02

This immutable Git snapshot gives GitHub Work direct access to the raw market feed and DeltaScout research archive without relying on the local Windows machine. It is **research input**, not a deployment package. No server service, production state, or source file was changed when collecting it. The public repository contains these market and signal records at the user's request; the collection scan found no credential-like field names, email addresses, or token/private-key patterns.

| Dataset | Server source | Files | Records | Frozen coverage |
|---|---|---:|---:|---|
| `enriched_feed/` | `/opt/aitrader_data/feed/YYYY-MM-DD.csv` | 206 | 294,836 minute rows | 2026-03-11 through 2026-10-02 08:33 UTC |
| `legacy_feed/` | `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv` | 201 | 287,365 minute rows | 2026-03-16 through 2026-10-02 10:58 as recorded in the legacy local clock |
| `deltascout/` | `/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl` | 201 | 7,356 events | 2026-03-16 through 2026-10-02; last event's raw `ts` is 10:05 |

The three October 2 files are **partial snapshots of an active day** and will not automatically update on GitHub. The corresponding `copied_at_utc`, last recorded timestamp, row count, byte size, and SHA-256 are in `MANIFEST.csv`. All 605 earlier daily files matched SHA-256 computed independently on VNV after transfer (`*_complete.sha256`). `SHA256SUMS.txt` includes all 608 copied files, including the three partial ones, for verification from this directory:

```bash
sha256sum -c SHA256SUMS.txt
```

The enriched feed is UTC completed-minute data. It contains 19,051 rows marked synthetic across 27 daily files; preserve `IsSynthetic` during analysis. Four historical enriched days have fewer than 1440 rows: March 11 (starts 13:45), March 15 (1439), May 6 (1389), and May 18 (1439). October 2 is partial by design. No duplicate minute labels were found within the copied enriched daily files, and no date in its March 11–October 2 range is missing.

The legacy Executor feed has a **different clock and schema**; its `Timestamp` is a local naive time, not UTC. It starts on March 16. March 29 has 1380 rows because of the local daylight-saving transition; March 16 starts at 20:31, June 15 has 1438 rows, August 12 has 1439, and October 2 is partial. Normalize the legacy clock with `Europe/Bratislava` before joining it to UTC enriched rows or DeltaScout `signal_ts_utc`. DeltaScout archive `ts` is also a local naive clock; use explicit `signal_ts_utc` when present. The two feeds are not interchangeable.

The frozen predictor Snapshot V2 source manifest remains at `../gpt56_prompt_abc_snapshot_v2/required_source_feed_hashes.csv` and covers its original 155 daily files. These source snapshots do not change any frozen prompt, prediction, or outcome artifact. Before new research, select files by cutoff, verify hashes, exclude post-cutoff rows, and mark incomplete or synthetic evidence. Do not infer a complete current day from the October 2 partial files.
