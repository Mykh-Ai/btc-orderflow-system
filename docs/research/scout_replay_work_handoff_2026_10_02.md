# Scout Replay backtester handoff — 2026-10-02

Branch: `codex/scout-replay-backtester-v0-1`. This branch contains the offline backtester code, tests, research journals, and two archived input bundles. It does not deploy or change trading services.

## Prepare inputs in a fresh GitHub Work checkout

Run from the repository root:

```bash
tar -xzf docs/research/scout_replay_inputs_2026_10_02.tar.gz
tar -xzf docs/research/scout_replay_execution_feed_2026_10_02.tar.gz
python -m pytest -q tests/offline/scout_backtester
```

The context bundle SHA-256 is `e9eb54378a7fd81d8587019a394fc9dd4918505eaf9fd3c01521a4cdd8bd4e78` (2,152 files, 11,671,715 bytes). The execution-feed bundle SHA-256 is `ae02583c66150bf79865f92ad1fb27435861505b25e946bd1b73b063fbb0860e` (730 files, 48,078,575 bytes). All 2,882 archived files were compared byte-for-byte by SHA-256 with the local source before push.

## Verified smoke run

```bash
python -m deltascout.research_bundle.scout_backtester.cli \
  --candidate-root deltascout/research_material/reviews \
  --raw-archive-root deltascout/research_material/raw_archive \
  --feed-root deltascout/research_material/effective_feed \
  --execution-feed-root deltascout/research_material/execution_feed/btcusdc_spot_1m/daily \
  --quality-sidecar-root deltascout/research_material/recovery_reports \
  --server-state-root deltascout/research_material/server_state \
  --date-from 2026-03-20 --date-to 2026-03-22 \
  --candidate-groups PEAK_EMIT_BASELINE,ALMOST_PEAK_2_OF_3 \
  --execution-policy EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2 \
  --fill-model MARKETABLE_LIMIT_NEXT_BAR_V0_1 \
  --same-bar-policy CONSERVATIVE_STOP_FIRST_V0_1 \
  --cost-model COMMISSION_TURNOVER_RATE_V0_1 \
  --replay-modes independent_opportunity,executor_portfolio \
  --experiment-id work_handoff_smoke_20261002_new
```

Use a fresh experiment id for every run. The local offline smoke with the same input paths and 2026-03-20 through 2026-03-22 dates completed successfully. The full command contract is in `docs/runbooks/SCOUT_REPLAY_BACKTESTER.md`.

## Coverage and limits

`raw_archive` has 2026-03-17 through 2026-08-18, `effective_feed` through 2026-08-19, and normalized BTCUSDC Spot execution bars in `btcusdc_spot_1m/daily` cover 2026-03-19 through 2026-08-19. Use those aligned inputs for historical replay. Other execution-feed subdirectories include later sources, but they do not by themselves provide a fully recovered later signal feed.

The separate branch `codex/research-source-data-2026-10-02` holds newer raw enriched/legacy feed and DeltaScout archives through a partial 2026-10-02. Later Scout Replay requires rebuilding the effective feed and obtaining matched official BTCUSDC Spot bars; do not treat the raw later files as a ready replay input. The archived bundles omit `node_modules` and historical LLM runtime audit dumps. They contain no production credentials according to the collection scan.
