# LLM Trade Judge Game Research Journal

This is a research/game journal, not the Executor runtime log. It records
evidence-backed observations from local repository state, server runtime files,
durable journals, and explicit LLM review artifacts.

Do not use this file as an execution input. Do not infer missing data.

## Entry Template

```yaml
datetime_utc:
trade_key:
source_files:
pre_trade_verdict:
post_trade_review:
llm_data_requests:
request_backlog_items_created:
final_close_order_id:
final_close_fill_price:
close_qty:
commissions:
realized_pnl:
lifecycle_class:
scoring_interpretation:
excluded_from_scoring:
code_changes_commits:
incidents_errors:
conclusions:
next_actions:
```

## 2026-05-16T18:18:46Z - Evidence Baseline

### Scope

- Project: AiTrader / DeltaScout / Executor / LLM Trade Judge Game
- Purpose: document current Game v0 evidence baseline without changing
  execution logic.
- Execution code changes: none.
- Binance/API additions: none.
- Post-trade LLM implementation: none.
- Invented backlog items: none.

### Evidence Commands Run

- `git status --short`
- `git log --oneline -n 30`
- `rg -n "LLM_TRADE_JUDGE|llm_trade|trade_outcomes|last_closed|_close_slot|trade_execution_snapshot|EXITS_PLACED_V15|EmitPeak" .`
- Server file presence checks for:
  - `/root/volume-alert/data/logs/executor.log`
  - `/root/volume-alert/data/state/trade_outcomes.jsonl`
  - `/root/volume-alert/data/state/executor_state.json`
  - `/root/volume-alert/data/state/llm_trade_verdicts.jsonl`
  - `/root/volume-alert/data/state/invariants_state.json`
  - `/root/volume-alert/data/state/trade_execution_snapshots.jsonl`
- `nl -ba` excerpts on deployed server files after integration points were found.

### Repository State

- Local working tree: clean by `git status --short`.
- Local HEAD: `880b62e Add final trade execution snapshot journal`.
- Local durable runtime files under repo root and `data/`: absent.
- Local `docs/` directory: absent before this documentation patch.

### Server State

- `/root/volume-alert` exists and contains deployed Executor files, but it is not
  a Git repository.
- `/root/btc-orderflow-system` is a Git repository, but its state does not prove
  deployed Executor commit identity.
- Running container: `executor` was observed running.
- Durable host/container journal status:
  - `executor.log`: present.
  - `trade_outcomes.jsonl`: present.
  - `executor_state.json`: present.
  - `llm_trade_verdicts.jsonl`: present.
  - `invariants_state.json`: present.
  - `trade_execution_snapshots.jsonl`: absent on host and in container.
  - snapshot runtime validation: pending.
  - snapshot validation reason: no post-patch closed trade yet.
  - snapshot validation action: verify after next closed trade.

### Current Trade: EX_EN_1778813539

- trade_key: `EX_EN_1778813539`
- source files:
  - `/root/volume-alert/data/state/llm_trade_verdicts.jsonl`
  - `/root/volume-alert/data/state/trade_outcomes.jsonl`
  - `/root/volume-alert/data/state/executor_state.json`
  - `/root/volume-alert/data/logs/executor.log`
- pre_trade_verdict:
  - exists: true
  - verdict: `SUPPORT`
  - competitive_side: `BOT`
  - confidence: `0.66`
  - model: `gpt-5.5`
  - created_at: `2026-05-15T02:52:39Z`
- outcome:
  - exists: true
  - source: `_close_slot`
  - reason: `SL`
  - tp1_done: false
  - tp2_done: false
  - sl_done: true
  - closed_at: `2026-05-15T05:01:42Z`
- lifecycle_class: `plain_sl`
- post_trade_review: `not_available`
- llm_data_requests: `none_recorded`
- request_backlog_items_created: `none`
- snapshot_journal: absent
- snapshot_runtime_validation: pending
- snapshot_validation_reason: no post-patch closed trade yet
- snapshot_validation_action: verify after next closed trade
- scoring_interpretation: Game v0 can compare immutable pre-trade `SUPPORT`
  against durable `plain_sl` outcome. Snapshot-enriched analysis remains pending
  runtime validation until the next post-patch closed trade.
- excluded_from_scoring: no durable exclusion marker found for this trade in the
  available outcome evidence.
- incidents_errors:
  - `executor.log` recorded I13 WARN/ERROR about margin debt after close before
    later margin hook repayment events.
- conclusions:
  - Game v0 basic research logging is ready to document from existing verdict
    and outcome journals.
  - Snapshot-enriched analysis runtime validation is pending because there has
    been no post-patch closed trade yet.
  - Post-trade LLM self-review loop is not ready because no durable review
    artifact exists.
  - LLM data-request loop protocol can be documented, but it is not active and
    no requests are recorded.
- next_actions:
  - Keep Game v0 logging evidence-first.
  - Do not add execution logic, Binance/API calls, or post-trade LLM runtime
    until a separate TZ exists.
  - Verify snapshot journal behavior after the next post-patch closed trade.
  - Do not debug the snapshot hook unless a post-patch close event occurs
    without a snapshot record.

## 2026-05-23T17:57:59Z - Post-Close Snapshot Audit

### Scope

- Project: AiTrader / DeltaScout / Executor / LLM Trade Judge Game.
- Purpose: record post-close execution snapshot evidence for
  `EX_EN_1779438963`.
- Execution code changes: none.
- n8n workflow changes: none.
- Binance/API/order/margin/SL/TP/recon/finalization changes: none.
- Trailer quality conclusions: none; this entry records factual close fills
  only.

### Evidence Commands Run

- `git status --short`
- Server extraction from
  `/root/volume-alert/data/state/trade_execution_snapshots.jsonl` for
  `EX_EN_1779438963`.
- Server extraction of `fills` and `fill_summaries` for all recorded legs.
- Server gross PnL calculation from snapshot fill summaries using Decimal
  arithmetic.

### Current Trade: EX_EN_1779438963

- trade_key: `EX_EN_1779438963`
- source_files:
  - `/root/volume-alert/data/state/trade_execution_snapshots.jsonl`
  - `/root/volume-alert/data/state/trade_outcomes.jsonl`
  - `/root/volume-alert/data/state/llm_trade_verdicts.jsonl`
  - `/root/volume-alert/data/state/executor_state.json`
  - `/root/volume-alert/data/logs/executor.log`
- pre_trade_verdict:
  - exists: true
  - verdict: `SUPPORT`
  - competitive_side: `BOT`
  - confidence: `0.66`
  - model: `gpt-5.5`
  - created_at: `2026-05-22T08:36:30.674529+00:00`
- outcome:
  - exists: true
  - source: `_close_slot`
  - reason: `SL`
  - tp1_done: true
  - tp2_done: true
  - sl_done: true
  - trail_active: true
  - closed_at: `2026-05-23T11:24:30.714484+00:00`
- post_trade_review: `not_available`
- llm_data_requests: `none_recorded`
- request_backlog_items_created: `none`
- snapshot:
  - exists: true
  - schema: `trade_execution_snapshot_v1`
  - snapshot_status: `partial`
  - snapshot_ts: `2026-05-23T11:24:30.714484+00:00`
  - lifecycle_class: `tp1_tp2_trailing_stop`
  - excluded_from_scoring: false
  - scoring_exclusion_reason: null
- final_close_order_id: `9346238698`
- final_close_fill_price: `74797.02`
- close_qty: `0.01728`
- final_close_quote_qty: `1292.4925056`
- commissions:
  - entry: `0.00432724 BNB`
  - tp1: `0.00151226 BNB`
  - tp2: `0.0015142 BNB`
  - final_sl: `0.0015133 BNB`
  - total: `0.00886700 BNB`
- realized_pnl:
  - gross_realized_pnl_approx_usdc: `63.2481096`
  - gross_pnl_components:
    - tp1: `7.1989734 USDC`
    - tp2: `14.2524450 USDC`
    - final_sl: `41.7966912 USDC`
  - net_realized_pnl_approx_usdc: `not_available`
  - net_pnl_unavailable_reason: snapshot commissions are denominated in BNB and
    borrow interest is not recorded in the snapshot.
- lifecycle_class: `tp1_tp2_trailing_stop`
- scoring_interpretation: Game v0 can compare immutable pre-trade `SUPPORT`
  against durable `tp1_tp2_trailing_stop` outcome. Snapshot-enriched analysis is
  validated for close fill capture, but numeric net PnL remains unavailable.
- excluded_from_scoring: false
- code_changes_commits: none.
- incidents_errors:
  - Snapshot error `repay_occurs_after_snapshot`: margin repayment runs after the
    snapshot and is a future durable update.
  - Snapshot error `short_pnl_not_implemented`: snapshot PnL approximation did
    not compute short PnL.
  - Executor log shows `MARGIN_HOOK_AFTER_CLOSE` with `repaid=true` after the
    snapshot timestamp, so the snapshot did not block the close hook.
- conclusions:
  - `trade_execution_snapshots.jsonl` contains final SL fills for order
    `9346238698`.
  - Fact-based final close price is `74797.02`; no Binance fill fallback was
    required.
  - No post-trade LLM self-review artifact or LLM data-request artifact was
    found in durable state.
  - No conclusion is made here about trailer quality.
- next_actions:
  - Keep any qualitative trailer analysis separate and base it on the confirmed
    close fill price plus an explicit analysis brief.
  - If net PnL is required, add an evidence-backed conversion path for BNB
    commissions and borrow interest in a separate task.

## 2026-06-07T19:36:38Z - Market Monitor Snapshot Integration And Agent Docs Consolidation

### Scope

- Project: AiTrader / Executor / LLM Trade Judge Game.
- Purpose: attach AiTrader Market Monitor snapshot as optional pre-cutoff
  evidence for the pre-trade LLM verdict and clean up duplicated agent
  instruction files.
- Execution behavior changes: none to order placement, SL, TP, margin,
  reconciliation, finalization, or Binance/API behavior.
- Runtime restart: performed by operator after config and mount changes.

### Evidence Commands Run

- Read local `AGENTS.md`, `AGENT.md`, `CLAUDE.md`, `agend.md`,
  `ADR-LLM-Trade-Judge-Game.md`, and AiTrader
  `docs/MARKET_MONITOR_SNAPSHOT_INTEGRATION.md`.
- Server read-only checks of `shi-aggregator` container env and mounts.
- Server read-only checks of `/root/volume-alert/docker-compose.yml` and
  `/root/volume-alert/.executor.env`.
- `docker compose config --quiet` on `/root/volume-alert`.
- Local tests:
  - `python -m pytest test\test_llm_trade_judge.py`
  - `python -m pytest test/`

### Market Monitor Snapshot Integration

- Copied AiTrader `market_monitor/` package into the Executor repository.
- Added optional LLM evidence-pack enrichment in
  `executor_mod/llm_trade_judge.py`.
- Added Executor env keys:
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_MAX_ZONES`
- Snapshot behavior:
  - disabled by default in code unless env enables it;
  - uses `analysis_cutoff_ts`;
  - treats `CURRENT_FEED` as either a file or a directory;
  - when `CURRENT_FEED` is a directory, resolves
    `YYYY-MM-DD.csv` from `analysis_cutoff_ts`;
  - records missing feed/cutoff/import/build failures as `data_gaps`;
  - does not block verdict journal writes or execution cleanup.
- Prompt updated to describe `market_monitor_snapshot` as descriptive
  pre-cutoff market-state evidence, not a trading instruction.

### Server Feed Evidence

- `shi-aggregator` container observed with:
  - `FEED_DIR=/app/feed`
  - mount `/opt/aitrader/feed -> /app/feed`
- Host evidence:
  - `/opt/aitrader/feed` is a symlink to `/opt/aitrader_data/feed`.
  - `/opt/aitrader/feed/2026-06-07.csv` existed during the audit.

### Production Config Changes

- Server `/root/volume-alert/docker-compose.yml` executor service mounts added:
  - `/opt/aitrader_data/feed:/opt/aitrader/feed:ro`
  - `/root/volume-alert/market_monitor:/app/market_monitor:ro`
- Server `/root/volume-alert/.executor.env` entries added:
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED=true`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED=/opt/aitrader/feed`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED=/opt/aitrader/feed`
  - `LLM_TRADE_JUDGE_MARKET_MONITOR_MAX_ZONES=5`
- Server package copied to `/root/volume-alert/market_monitor`.
- Production backups created:
  - `/root/volume-alert/docker-compose.yml.bak_20260607192639`
  - `/root/volume-alert/.executor.env.bak_20260607192639`
- Local production env `D:\Project_V\.executor.env` was updated with the same
  Market Monitor snapshot env block.
- The local `D:\Project_V\volume-alert\docker-compose.yml` was not changed
  because it did not contain the deployed `executor` service.

### Agent Docs Consolidation

- Cause of duplicate instruction files:
  - `CLAUDE.md`: legacy Claude Code copy of the main repository instructions.
  - `AGENT.md`: narrow LLM Trade Judge Game curation profile.
  - `agend.md`: standalone permission guidance with a nonstandard filename.
  - `AGENTS.md`: Codex-facing repository guidance and the correct canonical
    file for this repository.
- Consolidation performed:
  - Merged unique `AGENT.md` curation rules into `AGENTS.md`.
  - Merged unique `agend.md` permission guidance into `AGENTS.md`.
  - Removed redundant `CLAUDE.md`, `AGENT.md`, and `agend.md`.
- Canonical agent instruction file after cleanup: `AGENTS.md`.

### Validation

- `python -m pytest test\test_llm_trade_judge.py`: passed.
- `python -m pytest test/`: passed with `261 passed`.
- `docker compose config --quiet`: passed on production server.

### Incidents Errors

- Executor was restarted by the operator after the production config and mount
  changes. Runtime validation of `market_monitor_snapshot` in the next durable
  LLM verdict remains pending.
- One attempted inline SSH/Python update command failed because PowerShell
  quoting parsed the command locally; no server config change was applied by
  that failed attempt. The successful update used a temporary script copied to
  `/tmp` and then removed.

### Conclusions

- AiTrader Market Monitor snapshot is now wired as optional pre-trade LLM
  evidence with explicit pre-cutoff and data-gap behavior.
- Production configuration is prepared and the Executor was restarted by the
  operator so the container can read the AiTrader SHI feed and import the
  Market Monitor package.
- Agent instruction sprawl was reduced to one canonical `AGENTS.md`.

### Next Actions

- After the next LLM pre-trade verdict, verify that
  `evidence_pack.market_monitor_snapshot.schema_version` is
  `market_monitor_snapshot_v1` or that any failure is recorded as a data gap.

## 2026-06-10T17:31:00Z - Production Snapshot Deployment Correction

### Scope

- Project: Executor / AiTrader Market Monitor snapshot integration.
- Purpose: verify why the first post-integration LLM verdict did not include
  `market_monitor_snapshot`, then deploy the missing code and correct the
  production compose mounts.
- Execution logic changes: none beyond deploying the already-reviewed optional
  pre-trade evidence enrichment.

### Evidence Checked

- `/root/volume-alert/data/state/llm_trade_verdicts.jsonl`
- `/root/volume-alert/data/state/executor_state.json`
- `/root/volume-alert/docker-compose.yml`
- `/root/volume-alert/.executor.env`
- Running `executor` container env, mounts, and code paths.

### Trade Checked

- trade_key: `EX_EN_1781057890`
- verdict record created_at: `2026-06-10T02:18:34.119365+00:00`
- verdict: `SUPPORT`
- direction: `short`
- confidence: `0.72`
- setup_class: `continuation_pressure`
- analysis_cutoff_ts: `2026-06-10T02:18:00Z`
- result: the model did not receive `market_monitor_snapshot`.

### Root Cause

- The prior production wiring was incomplete:
  - `/root/volume-alert/executor.py` and
    `/root/volume-alert/executor_mod/llm_trade_judge.py` had not been updated
    with the local Market Monitor snapshot integration code before the first
    post-integration verdict.
  - The first automatic compose edit inserted the new bind-mount lines under
    `environment` instead of `volumes`, so Docker interpreted them as
    environment keys rather than mounts.
- The container had Market Monitor env variables but did not have the required
  `/app/market_monitor` and `/opt/aitrader/feed` mounts at verdict time.

### Fix Applied

- Backed up production files before overwrite:
  - `/root/volume-alert/executor.py.bak_`
  - `/root/volume-alert/executor_mod/llm_trade_judge.py.bak_`
- Copied updated local files to production:
  - `executor.py`
  - `executor_mod/llm_trade_judge.py`
  - `market_monitor/`
- Corrected `/root/volume-alert/docker-compose.yml` so executor mounts are under
  `volumes`:
  - `/opt/aitrader_data/feed:/opt/aitrader/feed:ro`
  - `/root/volume-alert/market_monitor:/app/market_monitor:ro`
- Created compose backup:
  - `/root/volume-alert/docker-compose.yml.bak_fix_mounts_20260610172935`
- Recreated the executor container with:
  - `docker compose up -d --force-recreate executor`

### Validation

- Running container start time after correction:
  - `2026-06-10T17:30:12.528802697Z`
- Running executor mounts verified:
  - `/root/volume-alert/executor.py -> /app/executor.py`
  - `/root/volume-alert/executor_mod -> /app/executor_mod`
  - `/opt/aitrader_data/feed -> /opt/aitrader/feed`
  - `/root/volume-alert/market_monitor -> /app/market_monitor`
  - `/root/volume-alert/data/state -> /data/state`
- Runtime smoke inside the executor container built a snapshot for the checked
  trade cutoff:
  - schema_version: `market_monitor_snapshot_v1`
  - enabled: `True`
  - cutoff_ts: `2026-06-10T02:18:00Z`
  - current_rows: `139`
  - context_rows: `43200`
  - data_gaps: `None`

### Conclusion

- The 2026-06-10 LLM verdict did not include Market Monitor snapshot evidence.
- After the correction and container recreate, the next LLM pre-trade verdict
  should include `evidence_pack.market_monitor_snapshot` when the relevant
  cutoff-day AiTrader feed file is present.

### Next Actions

- On the next LLM verdict, verify durable
  `evidence_pack.market_monitor_snapshot.schema_version` is
  `market_monitor_snapshot_v1`.

## 2026-06-29 - LLM Trade Judge Market Structure State Evidence

- datetime_utc: 2026-06-29
- scope: pre-trade LLM Trade Judge evidence quality
- change: added AiTrader SHI_RESET_37E `market_structure_state` classifier into Executor Market Monitor snapshot as `market_structure_state` evidence.
- rationale: deployed verdict journal showed the model often recognized late-chase, local-extreme, broad-context conflict, and zone-risk flags but still returned `SUPPORT`; AiTrader latest repair fixed range/support misclassification by using `range_pct`, `close_position`, seller/buyer pressure, `dominant_side`, and `range_quality`.
- implementation: copied committed `market_monitor/market_structure_state.py`; `snapshot_builder.py` now computes a pre-cutoff in-memory market-structure summary from current feed plus significant zones and includes support/resistance, metrics, `oi_context`, candidate bias/strength, and evidence summary.
- prompt_update: LLM prompt now describes `market_structure_state` as repaired 37E evidence and explicitly warns against misreading bearish expansion as range/support; verdict calibration also discourages `SUPPORT` on late-chase/extreme/zone-conflict setups.
- tests: `python -m pytest test\test_llm_trade_judge.py` -> 47 passed; `python -m pytest test\` -> 262 passed.
- production_status: local code only in this workspace at the time of this entry; server deployment/restart not performed in this step.
