# BTCUSDC Spot 1m raw archive — 2026-09-27

Path on this branch: `docs/research/spot_btcusdc_archive_2026_09_27/raw/`.

The 33 official BTCUSDC Spot 1m ZIP files and their 33 `.CHECKSUM` companions were copied from `backtests/imbalance_045_075_through_2026-09-27_v1/source/execution_feed_btcusdc/raw/`. They cover March through August 2026 as monthly archives and September 1–27 as daily archives. Every ZIP SHA-256 matched its companion checksum before publication. Files are stored without Git line-ending conversion.

These are exchange execution-price inputs. DeltaScout signals, enriched BTCUSDT feed, and legacy Executor feed are separate datasets at `../source_data_2026_10_02/`. The Scout Replay code and its ready-to-run historical input bundles are on branch `codex/scout-replay-backtester-v0-1`; see `docs/research/scout_replay_work_handoff_2026_10_02.md` there. For newer replays, normalize these Spot ZIPs with the backtester's `acquire_binance_spot_klines` tool and rebuild matched signal/effective-feed inputs. Do not substitute Spot for the signal feed.

The other 1,252 files in the old Executor `source/` directory were not copied wholesale; they were largely duplicate feed/source material. Use the run's `source_snapshot_manifest.json` to audit exact historical inputs. This archive stops on September 27 and does not automatically update.
