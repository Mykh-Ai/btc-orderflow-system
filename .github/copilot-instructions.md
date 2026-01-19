# Executor AI Coding Agent Instructions

**Executor** is an automated trading execution engine for DeltaScout PEAK signals. Single-position mode with full lifecycle management: entry → stop-loss/take-profit → trailing stop → closure.

## Architecture Overview

### Module Layout & Dependency Injection
All modules in `executor_mod/` use **dependency injection** via `configure()` functions called from startup in [executor.py](executor.py). This prevents circular imports:

```python
binance_api.configure(ENV, fmt_qty=risk_math.fmt_qty, fmt_price=risk_math.fmt_price, round_qty=risk_math.round_qty)
invariants.configure(ENV, log_event_fn=log_event, send_webhook_fn=send_webhook, now_fn=_now_s, save_state_fn=save_state)
margin_guard.configure(ENV, log_event, api=binance_api)
```

**Critical rule**: Modules NEVER import `executor.py` — always pass dependencies via `configure()`.

### State Machine & Position Lifecycle
- **One position at a time**: new PEAK signals ignored while `position.status ∈ {PENDING, OPEN, OPEN_FILLED, CLOSING}`
- **Cooldown window**: waits `COOLDOWN_SEC` (default 180s) after closure before new signals accepted
- **Position lock**: `LOCK_SEC` (default 15s) after entry placed to prevent duplicate opens on restart
- State persisted atomically to `/data/state/executor_state.json` via temporary file + `os.replace()`

### Decimal Math Throughout
**All** price/quantity calculations use Python `Decimal` type via [risk_math.py](executor_mod/risk_math.py) helpers:
- `floor_to_step()`, `ceil_to_step()`, `round_nearest_to_step()` for rounding
- `fmt_price()`, `fmt_qty()` respect `TICK_SIZE` and `QTY_STEP`
- `split_qty_3legs_*()` works in integer "step units"

**Never** use raw float arithmetic: `float(price) * qty` will cause rounding errors. Example: entry calculation uses `Decimal` at [executor.py#L1450+](executor.py#L1450).

### Event Deduplication (Stable Key, Not Hash)
[event_dedup.py](executor_mod/event_dedup.py) uses stable key formula instead of hashing:

```python
dedup_key = f"{action}|{ts_minute}|{kind}|{price_rounded}"
# Example: "PEAK|2025-01-13T20:00|long|95000.0"
```

- Timestamp bucketed to minute resolution
- Price rounded to `DEDUP_PRICE_DECIMALS` (default 1)
- `dedup_fingerprint()` invalidates cache on algorithm changes
- Bootstrap from last 300 lines of DeltaScout log via `bootstrap_seen_keys_from_tail()` at startup

## Key Module Patterns

### invariants.py — Detector-Only, No Actions
13 invariant checks (I1–I13) run every `INVAR_EVERY_SEC` (default 20s):
- **I1–I10**: position state consistency (SL present, price hierarchy, qty accounting, trailing state)
- **I11–I12**: margin config and trade key consistency
- **I13**: exchange-truth debt check post-close

**Rule**: Invariants ONLY log/alert via `log_event()` and `send_webhook()`. **Never** place orders or modify state. Exception: I13 can halt executor if `I13_KILL_ON_DEBT=true`.

### margin_guard.py — Lifecycle Hooks
Provides 4 hooks for margin mode:
1. `on_startup(state)` — validates config
2. `on_before_entry(state, symbol, side, qty, plan)` — calls `margin_policy.ensure_borrow_if_needed()`
3. `on_after_entry_opened(state, trade_key)` — marks trade_key active
4. `on_after_position_closed(state, trade_key)` — calls `margin_policy.repay_if_any()`

Mode behavior:
- `MARGIN_BORROW_MODE=auto`: hooks are no-ops, Binance handles via `MARGIN_SIDE_EFFECT=AUTO_BORROW_REPAY`
- `MARGIN_BORROW_MODE=manual`: hooks call `margin_borrow()` / `margin_repay()` explicitly

### trail.py — Swing-Based Trailing Stop
Uses [aggregated.csv](aggregated.csv) (v2 schema) for swing detection:
- **LONG**: finds last swing low in `LowPrice` column via fractal logic
- **SHORT**: finds last swing high in `HiPrice` column
- Fractal: `x[i] < x[i-lr..i-1] and x[i] < x[i+1..i+lr]` (configurable `lr` via `TRAIL_SWING_LR`)
- Placement: `swing_low - TRAIL_SWING_BUFFER_USD` (LONG) or `swing_high + TRAIL_SWING_BUFFER_USD` (SHORT)

Behavior:
- **Fail-loud** on schema mismatch (header validation)
- **Fail-closed** on missing file (startup/rotation)
- Optional bar-close confirmation via `TRAIL_CONFIRM_BUFFER_USD`

### exits_flow.py — 3-Leg Exit Structure
1. Validates exit plan: `sl < entry < tp1 < tp2` (LONG) with min tick separation
2. Places 3 legs: SL (33%), TP1 (33%), TP2 (34%) with qty degradation (50/50/0 if needed)
3. Uses `STOP_LOSS_LIMIT` for SL with `limit_price = stop_price - SL_LIMIT_GAP_TICKS * TICK_SIZE` (LONG)
4. Retries every `EXITS_RETRY_EVERY_SEC` up to `FAILSAFE_EXITS_MAX_TRIES`
5. Failsafe: if retries exhausted and `FAILSAFE_FLATTEN=true`, closes via MARKET order

## Entry/Exit Order Flow

### Entry (executor.py:open_flow)
1. Validate signal freshness (`MAX_PEAK_AGE_SEC`)
2. Check dedup via `stable_event_key()` in `seen_keys`
3. Build entry price: `build_entry_price()` adds `ENTRY_OFFSET_USD`, rounds directionally
4. Calculate qty via `notional_to_qty()`, validate with `validate_qty()`
5. **Margin hook**: `margin_guard.on_before_entry()` → borrow if needed
6. Place entry order (LIMIT or MARKET per `ENTRY_MODE`)
7. Poll status every `LIVE_STATUS_POLL_EVERY` iterations
8. **Plan B**: if timeout, check executable price via `bookTicker`, abort if too far
9. On fill: calculate exits via `exits_flow.ensure_exits()`, set position lock, save state

### Exit (manage_position)
- Trailing activation triggered when: `TRAIL_ACTIVATE_AFTER_TP2=true` AND TP2 filled
- Cancels old SL, calculates new stop via `trail._trail_desired_stop_from_agg(pos)` (swing-based)
- Updates every `TRAIL_UPDATE_EVERY_SEC` if price moves favorably by `TRAIL_STEP_USD`

## Performance-Critical Patterns

### Tail Reading (No Full Scan)
[executor.py](executor.py) function `read_tail_lines(path, n)`:
- Reads last N lines **without scanning from start**
- Seeks to EOF, reads backwards in 8KB blocks
- Used for DeltaScout log (`TAIL_LINES=80`) and aggregated.csv trailing
- **Never** use `open(path).readlines()` for large logs in main loop

### Log Capping
`append_line_with_cap(path, line, cap)`:
- Appends line + truncates to last `cap` lines if file exceeds cap
- Used for `EXEC_LOG` (default `LOG_MAX_LINES=200`)

## Testing Commands & Patterns

```bash
# Run all tests
python -m pytest test/

# Run specific test file
python -m pytest test/test_executor.py::TestExecutorV15::test_swing_stop_far_uses_agg_high_low

# Run with print statements visible
python -m pytest -s test/test_executor.py

# Run with verbose + stop-on-first-fail
python -m pytest -vx test/
```

Test patterns from [test/test_executor.py](test/test_executor.py):
- `_stop_after_n_sleeps(n)` helper breaks infinite loops in `main_loop()` tests
- Mock `binance_api.*` to avoid real API calls
- Use `deepcopy(ENV)` to snapshot/restore global config in tests

## Configuration Patterns

### Environment Variable Precedence
All config built into `ENV` dict from `os.getenv()` at startup. Use typed getters in [executor.py](executor.py):
- `_get_bool(name, default)` — accepts "1", "true", "yes", "on"
- `_get_int(name, default)` — with fallback
- `_get_float(name, default)` — with fallback
- `_get_str(name, default)` — with empty string handling

**Rule**: Never read `os.getenv()` directly in modules — always pass via `ENV` dict to `configure()`.

### Trade Mode Configuration
Two valid modes:
1. **spot**: `TRADE_MODE=spot` (default)
2. **margin**: `TRADE_MODE=margin` + `MARGIN_ISOLATED=TRUE/FALSE` + `MARGIN_BORROW_MODE=manual/auto`

Validated at startup via `_validate_trade_mode()` — raises `RuntimeError` if invalid.

## Common Pitfalls & Anti-Patterns

| Pitfall | Why | Fix |
|---------|-----|-----|
| Float arithmetic on prices | Rounding errors accumulate | Use `Decimal` via `risk_math` functions |
| Module imports `executor.py` | Circular import → test failures | Use dependency injection via `configure()` |
| State mutation without `save_state()` | Changes lost on restart | Always call `save_state(st)` after modifying `st["position"]` |
| Missing `margin_guard.on_before_entry()` | Margin borrow not triggered | Check if new order placement needs margin hook |
| Changing `stable_event_key()` logic | Dedup cache invalidation missed | Update `dedup_fingerprint()` SHA256 hash |
| Invariants place orders or modify state | Violates detector-only pattern | Use `log_event()` / `send_webhook()` only |
| Raw Binance bools instead of strings | API rejects request | Use `_tf()` helper to normalize to "TRUE"/"FALSE" |

## Modifying Key Components

### Adding a New Invariant
1. Add check function `_check_iN_description(st)` in [invariants.py](executor_mod/invariants.py)
2. Call from `run(st)` after configure validation
3. Use `_emit(st, "IN", severity, message, details)` for alerts
4. Add test case in [test/test_invariants_module.py](test/test_invariants_module.py)

### Adding a Binance API Endpoint
1. Add function to [binance_api.py](executor_mod/binance_api.py) (use `_binance_signed_request()` for auth)
2. Handle margin vs spot via `ENV["TRADE_MODE"]` check
3. Inject margin params: `isIsolated`, `sideEffectType` via `_margin_side_effect(env)`
4. Add smoke test in [test/test_binance_api_smoke.py](test/test_binance_api_smoke.py) with mock

### Modifying State Structure
**High risk** — affects persistence across restarts:
1. Add migration logic in `state_store.load_state()` to handle old format
2. Use `st.setdefault(key, default)` for backward compatibility
3. Test with actual production state file (if available)
4. Update invariants checks that reference state fields

## Running the Executor

```bash
# Minimal spot trading setup
export SYMBOL=BTCUSDC
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TRADE_MODE=spot
export QTY_USD=100.0
python executor.py

# Margin trading (manual borrow/repay)
export TRADE_MODE=margin
export MARGIN_ISOLATED=FALSE
export MARGIN_BORROW_MODE=manual
export MARGIN_SIDE_EFFECT=NO_SIDE_EFFECT
python executor.py
```

---

**See also**: [CLAUDE.md](CLAUDE.md) (full deep dive), [README.md](README.md) (overview), [executor_mod/](executor_mod/) (modules).
