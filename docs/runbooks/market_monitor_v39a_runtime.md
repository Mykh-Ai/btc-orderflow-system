# Market Monitor v39A snapshot runtime

The v39A adapter is an additive snapshot contract. It does not replace the
existing v1 market-state engine, setup generation, order management, or outcome
logging.

The Executor hook is opt-in:

```text
LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED=false
LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_STATE_PATH=/data/state/market_monitor_state_v39a.json
```

When enabled, the hook builds the existing v1 snapshot first, then wraps it in
`market_monitor_snapshot_v39a`. The v39A snapshot adds exact closed UTC-minute
windows (5/15/30/60/240/1440), missing/duplicate checks, future-row exclusion,
per-window quality, source hashes, and an atomic persisted state envelope.
The state path must be on a writable Executor volume. The current container's
`/data/state` volume is writable; `/app/market_monitor` is a read-only code
mount.

The model-facing entry boundary still removes orders, order identifiers,
outcomes, PnL, and trailing fields. The monitor snapshot remains descriptive
evidence only.

The local proof and same-cutoff v1/v39A comparison are stored under
`outputs/market_monitor_runtime_promotion_audit_2026-09-11/`. The real-feed
midnight audit must begin from a fresh state file so a repeated run cannot
mistake an old later cutoff for the first transition.

Before enabling this flag in production, verify the deployed v39A module hash,
run one real-feed snapshot, confirm the state file is writable, and restart the
Executor with a rollback copy of the prior v1 files. The adapter still uses
v1/37E market-state and zone calculations; the unified 39A level lifecycle and
sweep classifier remain future work.
